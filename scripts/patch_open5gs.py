"""Apply narrowly scoped laboratory changes to the pinned, pristine checkout.

Run once; every replacement checks its exact source anchor. Baseline is built
from a separate pristine copy before this script is invoked.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'upstream/open5gs'
pending = {}

def replace(name, old, new, count=1):
    path = ROOT / name
    text = pending.get(path, path.read_text())
    assert text.count(old) == count, (name, text.count(old), old[:80])
    pending[path] = text.replace(old, new)

# P1/P4: explicit session capacity, default preserves upstream pool load.
# The active reference counts successful SBI contexts until local removal.
replace('src/smf/context.h', 'typedef struct smf_sess_s {',
        'typedef struct smf_sess_s {\n    bool lab_context_created;')
replace('src/smf/context.h', 'int smf_instance_get_load(void);',
        'int smf_instance_get_load(void);\nvoid smf_lab_context_created(smf_sess_t *sess);')
replace('src/smf/context.c', 'int smf_instance_get_load(void)\n{', '''static int lab_active_contexts;

void smf_lab_context_created(smf_sess_t *sess)
{
    if (!sess->lab_context_created) {
        sess->lab_context_created = true;
        lab_active_contexts++;
    }
}

int smf_instance_get_load(void)
{
    const char *cap = getenv("LAB_CAPACITY_ABS");
    const char *alpha_s = getenv("LAB_ALPHA");
    if (cap) {
        double c = atof(cap), alpha = alpha_s ? atof(alpha_s) : 0.0;
        double reference;
        int reported;
        ogs_assert(c > 0 && alpha >= 0 && alpha <= 1);
        reference = ogs_min(100.0, 100.0 * lab_active_contexts / c);
        reported = (int)(reference * (1.0 - alpha));
        ogs_info("LAB_LOAD t=%lld nf=%s active=%d reference=%.6f reported=%d",
            (long long)ogs_get_monotonic_time(), ogs_sbi_self()->nf_instance->id,
            lab_active_contexts, reference, reported);
        return reported;
    }''')
replace('src/smf/context.c', 'void smf_sess_remove(smf_sess_t *sess)\n{',
'''void smf_sess_remove(smf_sess_t *sess)
{
    if (sess->lab_context_created) {
        /* Count once even if removal follows a failure or timeout. */
        lab_active_contexts--;
        sess->lab_context_created = false;
    }''')
# Declaration must precede removal, not just the load helper.
replace('src/smf/context.c', 'static int lab_active_contexts;\n\n', '')
replace('src/smf/context.c', '#include "context.h"', '#include "context.h"\n\nstatic int lab_active_contexts;')
replace('src/smf/sbi-path.c', '            SMF_METR_CTR_SM_PDUSESSIONCREATIONSUCC, 1);',
        '            SMF_METR_CTR_SM_PDUSESSIONCREATIONSUCC, 1);\n    smf_lab_context_created(sess);')

# P2: prevalidate the load operation before any PATCH mutation.
anchor = '            SWITCH(patch_item->path)\n'
validation = '''            if (!strcmp(patch_item->path, OGS_SBI_PATCH_PATH_LOAD)) {
                cJSON *v = patch_item->value ? patch_item->value->json : NULL;
                if (!cJSON_IsNumber(v) || v->valuedouble < 0 ||
                        v->valuedouble > 100 ||
                        v->valuedouble != (int)v->valuedouble) {
                    ogs_assert(ogs_sbi_server_send_error(stream,
                        OGS_SBI_HTTP_STATUS_BAD_REQUEST, recvmsg,
                        "load must be an integer from 0 to 100", NULL, NULL));
                    return false;
                }
            }
'''
replace('src/nrf/nnrf-handler.c', anchor, validation + anchor)
replace('src/nrf/nnrf-handler.c', '            CASE(OGS_SBI_PATCH_PATH_LOAD)\n                break;',
'''            CASE(OGS_SBI_PATCH_PATH_LOAD)
                nf_instance->load = patch_item->value->json->valueint;
                ogs_info("LAB_NRF t=%lld nf=%s stored=%d",
                    (long long)ogs_get_monotonic_time(), nf_instance->id,
                    nf_instance->load);
                break;''')

# P3: fresh selection on the NSSF->NRF path for new sessions only.
replace('src/amf/gmm-handler.c', '''                    v_smf_instance =
                        ogs_sbi_nf_instance_find_by_discovery_param(''',
'''                    v_smf_instance = getenv("LAB_SELECTOR") ? NULL :
                        ogs_sbi_nf_instance_find_by_discovery_param(''')
replace('src/amf/sbi-path.c', '#include "sbi-path.h"',
        '#include "sbi-path.h"\n#include "lab-selector.h"')
replace('src/amf/sbi-path.c', '''    nf_instance = ogs_sbi_nf_instance_find_by_discovery_param(
                    target_nf_type, requester_nf_type, discovery_option);''',
'''    nf_instance = (getenv("LAB_SELECTOR") && target_nf_type == OpenAPI_nf_type_SMF)
        ? lab_select_smf(message.SearchResult, requester_nf_type, discovery_option)
        : ogs_sbi_nf_instance_find_by_discovery_param(
                    target_nf_type, requester_nf_type, discovery_option);''')

# I1: preserve request metadata across async forwarding; trace responses at SCP.
replace('src/scp/context.h', '    char *target_apiroot;',
        '    char *target_apiroot;\n    char *lab_uri;\n    char *lab_method;')
replace('src/scp/context.c', '    ogs_pool_free(&scp_assoc_pool, assoc);',
'''    if (assoc->lab_uri) ogs_free(assoc->lab_uri);
    if (assoc->lab_method) ogs_free(assoc->lab_method);
    ogs_pool_free(&scp_assoc_pool, assoc);''')
replace('src/scp/sbi-path.c', '    /* Next-SCP client */',
'''    assoc->lab_uri = ogs_strdup(request->h.uri);
    assoc->lab_method = ogs_strdup(request->h.method);

    /* Next-SCP client */''')
replace('src/scp/sbi-path.c', '    if (assoc->nf_service_producer) {',
'''    if (getenv("LAB_TRACE")) {
        const char *location = ogs_sbi_header_get(response->http.headers, "Location");
        if (!location) location = ogs_sbi_header_get(response->http.headers, "location");
        ogs_info("LAB_SCP t=%lld method=%s uri=%s status=%d location=%s",
            (long long)ogs_get_monotonic_time(), assoc->lab_method,
            assoc->lab_uri, response->status, location ? location : "-");
    }

    if (assoc->nf_service_producer) {''')
for path, text in pending.items():
    path.write_text(text, newline='\n')
print('Applied P1/P2/P3/P4 and SCP response tracing; compilation required.')
