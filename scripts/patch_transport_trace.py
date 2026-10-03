"""Attach a lab-only version to HTTP headers, leaving heartbeat JSON standard.

Apply to the laboratory source after P1--P4. The alternative legacy
patch_load_version.py uses a nonstandard JSON Patch path; do not combine them.
"""
from pathlib import Path
R=Path(__file__).resolve().parents[1]/'upstream/open5gs'
pending={}
def change(name,old,new,count=1):
    p=R/name; text=pending.get(p,p.read_text())
    assert text.count(old)==count,(name,text.count(old),old[:60])
    pending[p]=text.replace(old,new)

change('lib/sbi/context.h','    int load;\n\n    ogs_list_t nf_service_list;',
'''    int load;
    uint64_t lab_load_version;
    uint64_t lab_pending_version;

    ogs_list_t nf_service_list;''')
change('src/smf/smf-sm.c','            ogs_sbi_self()->nf_instance->load = smf_instance_get_load();',
'''            if (getenv("LAB_TRACE") && e->h.timer_id == OGS_TIMER_NF_INSTANCE_HEARTBEAT_INTERVAL)
                ogs_sbi_self()->nf_instance->lab_load_version++;
            ogs_sbi_self()->nf_instance->load = smf_instance_get_load();''')
change('src/smf/context.c','''        ogs_info("LAB_LOAD t=%lld nf=%s active=%d reference=%.6f reported=%d",
            (long long)ogs_get_monotonic_time(), ogs_sbi_self()->nf_instance->id,
            lab_active_contexts, reference, reported);''',
'''        ogs_info("LAB_LOAD t=%lld nf=%s version=%llu active=%d reference=%.6f reported=%d",
            (long long)ogs_get_monotonic_time(), ogs_sbi_self()->nf_instance->id,
            (unsigned long long)ogs_sbi_self()->nf_instance->lab_load_version,
            lab_active_contexts, reference, reported);''')
change('lib/sbi/nnrf-path.c','''    if (getenv("LAB_TRACE") &&
            ogs_sbi_self()->nf_instance->nf_type == OpenAPI_nf_type_SMF)
        ogs_info("LAB_SEND t=%lld nf=%s load=%d",
            (long long)ogs_get_monotonic_time(),
            ogs_sbi_self()->nf_instance->id,
            ogs_sbi_self()->nf_instance->load);''',
'''    if (getenv("LAB_TRACE") &&
            ogs_sbi_self()->nf_instance->nf_type == OpenAPI_nf_type_SMF) {
        char version[32];
        ogs_snprintf(version, sizeof(version), "%llu",
            (unsigned long long)ogs_sbi_self()->nf_instance->lab_load_version);
        ogs_sbi_header_set(request->http.headers, "x-lab-load-version", version);
        ogs_info("LAB_SEND t=%lld nf=%s version=%s load=%d",
            (long long)ogs_get_monotonic_time(),
            ogs_sbi_self()->nf_instance->id, version,
            ogs_sbi_self()->nf_instance->load);
    }''')
change('src/nrf/nrf-sm.c','''                    if (nf_instance) {
                        e->nf_instance = nf_instance;''',
'''                    if (nf_instance) {
                        const char *v = ogs_sbi_header_get(request->http.headers, "x-lab-load-version");
                        nf_instance->lab_pending_version = 0;
                        if (getenv("LAB_TRACE") && v && strlen(v) < 20 && strspn(v, "0123456789") == strlen(v))
                            nf_instance->lab_pending_version = strtoull(v, NULL, 10);
                        e->nf_instance = nf_instance;''')
change('src/nrf/nnrf-handler.c','''                ogs_info("LAB_NRF t=%lld nf=%s stored=%d",
                    (long long)ogs_get_monotonic_time(), nf_instance->id,
                    nf_instance->load);''',
'''                nf_instance->lab_load_version = nf_instance->lab_pending_version;
                ogs_info("LAB_NRF t=%lld nf=%s version=%llu stored=%d",
                    (long long)ogs_get_monotonic_time(), nf_instance->id,
                    (unsigned long long)nf_instance->lab_load_version, nf_instance->load);''')
change('src/nrf/nnrf-handler.c','''        ogs_assert(true == ogs_sbi_server_send_response(stream, response));

        goto cleanup;''',
'''        if (getenv("LAB_TRACE")) {
            char *versions = ogs_strdup("");
            OpenAPI_lnode_t *it;
            OpenAPI_list_for_each(SearchResult->nf_instances, it) {
                OpenAPI_nf_profile_t *profile = it->data;
                ogs_sbi_nf_instance_t *nf = ogs_sbi_nf_instance_find(profile->nf_instance_id);
                if (nf) {
                    char *next = ogs_msprintf("%s%s%s=%llu", versions,
                        *versions ? "," : "", nf->id, (unsigned long long)nf->lab_load_version);
                    ogs_free(versions); versions = next;
                }
            }
            ogs_sbi_header_set(response->http.headers, "x-lab-load-versions", versions);
            ogs_free(versions);
        }
        ogs_assert(true == ogs_sbi_server_send_response(stream, response));

        goto cleanup;''',count=2)
change('src/amf/lab-selector.h','#define LAB_SELECTOR_H',
'''#define LAB_SELECTOR_H
static void lab_apply_versions(OpenAPI_search_result_t *result, const char *header)
{
    OpenAPI_lnode_t *it;
    char *copy, *save = NULL, *token;
    OpenAPI_list_for_each(result->nf_instances, it) {
        OpenAPI_nf_profile_t *p = it->data;
        ogs_sbi_nf_instance_t *nf = ogs_sbi_nf_instance_find(p->nf_instance_id);
        if (nf) nf->lab_load_version = 0;
    }
    if (!header) return;
    copy = ogs_strdup(header);
    for (token = strtok_r(copy, ",", &save); token; token = strtok_r(NULL, ",", &save)) {
        char *eq = strchr(token, '=');
        if (eq) {
            ogs_sbi_nf_instance_t *nf;
            *eq++ = 0;
            nf = ogs_sbi_nf_instance_find(token);
            if (nf && strlen(eq) < 20 && strspn(eq, "0123456789") == strlen(eq))
                nf->lab_load_version = strtoull(eq, NULL, 10);
        }
    }
    ogs_free(copy);
}''')
change('src/amf/lab-selector.h','''        ogs_info("LAB_CANDIDATE t=%lld nf=%s load=%d capacity=%d",
            (long long)ogs_get_monotonic_time(), nf->id, nf->load, nf->capacity);''',
'''        ogs_info("LAB_CANDIDATE t=%lld nf=%s version=%llu load=%d capacity=%d",
            (long long)ogs_get_monotonic_time(), nf->id,
            (unsigned long long)nf->lab_load_version, nf->load, nf->capacity);''')
change('src/amf/lab-selector.h','''    ogs_info("LAB_SELECT t=%lld nf=%s load=%d capacity=%d policy=%s",
        (long long)ogs_get_monotonic_time(), nodes[pick]->id,
        nodes[pick]->load, nodes[pick]->capacity, getenv("LAB_SELECTOR"));''',
'''    ogs_info("LAB_SELECT t=%lld nf=%s version=%llu load=%d capacity=%d policy=%s",
        (long long)ogs_get_monotonic_time(), nodes[pick]->id,
        (unsigned long long)nodes[pick]->lab_load_version,
        nodes[pick]->load, nodes[pick]->capacity, getenv("LAB_SELECTOR"));''')
change('src/amf/sbi-path.c','    ogs_nnrf_disc_handle_nf_discover_search_result(message.SearchResult);',
'''    ogs_nnrf_disc_handle_nf_discover_search_result(message.SearchResult);
    if (getenv("LAB_TRACE")) lab_apply_versions(message.SearchResult,
        ogs_sbi_header_get(response->http.headers, "x-lab-load-versions"));''')
for p,text in pending.items(): p.write_text(text,newline='\n')
print('Applied header-only load version tracing.')
