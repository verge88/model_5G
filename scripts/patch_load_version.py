"""Add exact SMF -> NRF -> AMF load-version correlation to the current lab patch.

Run AFTER scripts/patch_open5gs.py and BEFORE compilation.
Pinned target: Open5GS v2.8.0 / commit 157f611.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1] / "upstream/open5gs"
EXPECTED_COMMIT_PREFIX = "157f611"

VERSION_PATH = "/x-lab-load-version"
VERSIONS_HEADER = "X-Lab-Load-Versions"

pending = {}


def replace(name, old, new, count=1):
    path = ROOT / name
    text = pending.get(path, path.read_text())

    actual = text.count(old)
    assert actual == count, (name, actual, old[:120])

    pending[path] = text.replace(old, new)


def verify_checkout():
    assert ROOT.exists(), ROOT

    if (ROOT / ".git").exists():
        head = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip()

        assert head.startswith(EXPECTED_COMMIT_PREFIX), (
            f"Expected {EXPECTED_COMMIT_PREFIX}, got {head}"
        )


LAB_SELECTOR = r'''/* Laboratory SMF selection and load-version tracing. */
#ifndef LAB_SELECTOR_H
#define LAB_SELECTOR_H

#define LAB_LOAD_VERSIONS_HEADER "X-Lab-Load-Versions"


/*
 * Parse the laboratory NRF Discovery response header:
 *
 *   X-Lab-Load-Versions:
 *       <nf-uuid-1>=17,<nf-uuid-2>=20,<nf-uuid-3>=19
 *
 * and attach the correlation number to the AMF-local
 * ogs_sbi_nf_instance_t objects.
 *
 * This field is laboratory-only and is not part of 3GPP NFProfile.
 */
static void lab_apply_load_versions(const char *header)
{
    char *copy = NULL;
    char *saveptr = NULL;
    char *token = NULL;

    if (!header || !*header)
        return;

    copy = ogs_strdup(header);
    ogs_assert(copy);

    for (token = strtok_r(copy, ",", &saveptr);
            token;
            token = strtok_r(NULL, ",", &saveptr)) {

        char *eq = strchr(token, '=');
        ogs_sbi_nf_instance_t *nf = NULL;
        unsigned long long version;

        if (!eq)
            continue;

        *eq = '\0';

        if (!*token || !*(eq + 1))
            continue;

        version = strtoull(eq + 1, NULL, 10);

        nf = ogs_sbi_nf_instance_find(token);
        if (nf)
            nf->lab_load_version = (uint64_t)version;
    }

    ogs_free(copy);
}


/*
 * Laboratory SMF selector.
 *
 * Candidate filtering remains the normal Open5GS/3GPP discovery filtering.
 * Among candidates with the best priority, use:
 *
 *      weight_i = capacity_i * (100 - load_i)
 *
 * LAB_SELECTOR=random -> probabilistic weighted selection
 * otherwise           -> smooth weighted round-robin
 */
static ogs_sbi_nf_instance_t *lab_select_smf(
        OpenAPI_search_result_t *result,
        OpenAPI_nf_type_e requester,
        ogs_sbi_discovery_option_t *option)
{
    static struct {
        char id[64];
        double score;
    } state[64];

    static uint32_t rng;

    ogs_sbi_nf_instance_t *nodes[64];
    ogs_sbi_nf_instance_t *nf;

    double weights[64];
    double total = 0;
    double best = -1e100;

    int slots[64];
    int n = 0;
    int i;
    int j;
    int pick = 0;
    int priority = 65536;

    OpenAPI_lnode_t *entry;

    const char *policy = getenv("LAB_SELECTOR");
    bool random_policy;

    if (!policy || !*policy)
        policy = "swrr";

    random_policy = !strcmp(policy, "random");

    if (!rng) {
        const char *seed = getenv("LAB_SEED");

        rng = seed ? (uint32_t)strtoul(seed, NULL, 10) : 1;

        if (!rng)
            rng = 1;
    }


    /*
     * Candidate filtering.
     */
    OpenAPI_list_for_each(result->nf_instances, entry) {
        OpenAPI_nf_profile_t *profile = entry->data;

        nf = ogs_sbi_nf_instance_find(profile->nf_instance_id);

        if (!nf ||
                !ogs_sbi_discovery_param_is_matched(
                    nf,
                    OpenAPI_nf_type_SMF,
                    requester,
                    option))
            continue;


        /*
         * Lower numeric priority means better priority.
         *
         * If we encounter a better priority, discard candidates
         * collected at the previous priority level.
         */
        if (nf->priority < priority) {
            priority = nf->priority;
            n = 0;
        }

        if (nf->priority != priority)
            continue;

        if (n == 64)
            return NULL;

        nodes[n++] = nf;
    }


    if (!n)
        return NULL;


    /*
     * Stable UUID ordering makes the result independent
     * of NRF SearchResult list order.
     */
    for (i = 0; i < n; i++) {
        for (j = i + 1; j < n; j++) {
            if (strcmp(nodes[i]->id, nodes[j]->id) > 0) {
                nf = nodes[i];
                nodes[i] = nodes[j];
                nodes[j] = nf;
            }
        }
    }


    /*
     * Experimental load-aware weight.
     *
     * Scaling by 100 is irrelevant to relative probabilities,
     * therefore division by 100 is intentionally omitted.
     */
    for (i = 0; i < n; i++) {

        weights[i] =
            nodes[i]->capacity *
            (100.0 - nodes[i]->load);

        if (weights[i] < 0)
            weights[i] = 0;

        total += weights[i];
    }


    /*
     * Overload fallback:
     * 1. capacity only;
     * 2. equal weights.
     *
     * Such cases should be labelled separately in analysis.
     */
    if (total == 0) {
        for (i = 0; i < n; i++) {
            weights[i] = nodes[i]->capacity;
            total += weights[i];
        }
    }

    if (total == 0) {
        for (i = 0; i < n; i++) {
            weights[i] = 1;
            total++;
        }
    }


    /*
     * Log every candidate with the exact NRF load_version
     * which AMF is using for this decision.
     */
    for (i = 0; i < n; i++) {

        ogs_info(
            "LAB_CANDIDATE "
            "t=%lld "
            "nf=%s "
            "version=%llu "
            "priority=%d "
            "load=%d "
            "capacity=%d "
            "weight=%.6f "
            "policy=%s",

            (long long)ogs_get_monotonic_time(),
            nodes[i]->id,
            (unsigned long long)nodes[i]->lab_load_version,
            nodes[i]->priority,
            nodes[i]->load,
            nodes[i]->capacity,
            weights[i],
            policy);
    }


    /*
     * Probabilistic weighted policy.
     */
    if (random_policy) {

        double draw;

        /* xorshift32 */
        rng ^= rng << 13;
        rng ^= rng >> 17;
        rng ^= rng << 5;

        draw =
            ((double)rng / 4294967296.0) *
            total;

        for (i = 0; i < n; i++) {

            draw -= weights[i];

            if (draw < 0) {
                pick = i;
                break;
            }
        }

    } else {

        /*
         * Smooth weighted round-robin.
         */
        for (i = 0; i < n; i++) {

            for (j = 0; j < 64; j++) {

                if (!state[j].id[0] ||
                        !strcmp(
                            state[j].id,
                            nodes[i]->id))
                    break;
            }

            if (j == 64)
                return NULL;


            if (!state[j].id[0]) {

                ogs_cpystrn(
                    state[j].id,
                    nodes[i]->id,
                    sizeof(state[j].id));
            }


            slots[i] = j;

            state[j].score +=
                weights[i] / total;


            if (state[j].score > best) {

                best = state[j].score;
                pick = i;
            }
        }


        state[slots[pick]].score -= 1;
    }


    /*
     * Exact decision log.
     */
    ogs_info(
        "LAB_SELECT "
        "t=%lld "
        "nf=%s "
        "version=%llu "
        "priority=%d "
        "load=%d "
        "capacity=%d "
        "weight=%.6f "
        "policy=%s",

        (long long)ogs_get_monotonic_time(),
        nodes[pick]->id,
        (unsigned long long)nodes[pick]->lab_load_version,
        nodes[pick]->priority,
        nodes[pick]->load,
        nodes[pick]->capacity,
        weights[pick],
        policy);


    return nodes[pick];
}


#endif
'''


def main():
    verify_checkout()


    # -------------------------------------------------------------
    # 1. Shared laboratory correlation field
    # -------------------------------------------------------------

    replace(
        "lib/sbi/context.h",

        """    int priority;
    int capacity;
    int load;
""",

        """    int priority;
    int capacity;
    int load;

    /* Laboratory-only heartbeat correlation sequence. */
    uint64_t lab_load_version;
""",
    )


    # -------------------------------------------------------------
    # 2. Increment load_version only for an actual heartbeat
    #
    # smf_instance_get_load() is still called normally.
    # The increment happens immediately before load calculation,
    # therefore LAB_LOAD and the following heartbeat share the same
    # version.
    # -------------------------------------------------------------

    replace(
        "src/smf/smf-sm.c",

        """            ogs_sbi_self()->nf_instance->load = smf_instance_get_load();
            ogs_fsm_dispatch(&nf_instance->sm, e);""",

        """            if (e->h.timer_id ==
                    OGS_TIMER_NF_INSTANCE_HEARTBEAT_INTERVAL &&
                    getenv("LAB_TRACE"))
                ogs_sbi_self()->nf_instance->lab_load_version++;

            ogs_sbi_self()->nf_instance->load =
                smf_instance_get_load();

            ogs_fsm_dispatch(&nf_instance->sm, e);""",
    )


    # -------------------------------------------------------------
    # 3. Add version to existing LAB_LOAD log
    #
    # This anchor expects the current laboratory patch from
    # patch_open5gs.py to have already been applied.
    # -------------------------------------------------------------

    replace(
        "src/smf/context.c",

        """        ogs_info("LAB_LOAD t=%lld nf=%s active=%d reference=%.6f reported=%d",
            (long long)ogs_get_monotonic_time(), ogs_sbi_self()->nf_instance->id,
            lab_active_contexts, reference, reported);""",

        """        ogs_info(
            "LAB_LOAD "
            "t=%lld "
            "nf=%s "
            "version=%llu "
            "active=%d "
            "reference=%.6f "
            "reported=%d",

            (long long)ogs_get_monotonic_time(),
            ogs_sbi_self()->nf_instance->id,
            (unsigned long long)
                ogs_sbi_self()->nf_instance->lab_load_version,
            lab_active_contexts,
            reference,
            reported);""",
    )


    # -------------------------------------------------------------
    # 4. Put load_version into the same Nnrf_NFManagement PATCH
    #
    # We deliberately use a laboratory JSON Patch path instead of
    # altering the 3GPP NFProfile/OpenAPI schema.
    # -------------------------------------------------------------

    replace(
        "lib/sbi/nnrf-build.c",

        """    OpenAPI_patch_item_t StatusItem;
    OpenAPI_patch_item_t LoadItem;""",

        """    OpenAPI_patch_item_t StatusItem;
    OpenAPI_patch_item_t VersionItem;
    OpenAPI_patch_item_t LoadItem;""",
    )


    replace(
        "lib/sbi/nnrf-build.c",

        """    memset(&StatusItem, 0, sizeof(StatusItem));
    memset(&LoadItem, 0, sizeof(LoadItem));""",

        """    memset(&StatusItem, 0, sizeof(StatusItem));
    memset(&VersionItem, 0, sizeof(VersionItem));
    memset(&LoadItem, 0, sizeof(LoadItem));""",
    )


    replace(
        "lib/sbi/nnrf-build.c",

        """    OpenAPI_list_add(PatchItemList, &StatusItem);

    LoadItem.op = OpenAPI_patch_operation_replace;""",

        f"""    OpenAPI_list_add(PatchItemList, &StatusItem);

    if (getenv("LAB_TRACE")) {{

        VersionItem.op =
            OpenAPI_patch_operation_replace;

        VersionItem.path =
            (char *)"{VERSION_PATH}";

        VersionItem.value =
            OpenAPI_any_type_create_number(
                (double)nf_instance->lab_load_version);

        if (!VersionItem.value) {{

            ogs_error(
                "No lab load-version item.value");

            goto end;
        }}

        OpenAPI_list_add(
            PatchItemList,
            &VersionItem);
    }}

    LoadItem.op = OpenAPI_patch_operation_replace;""",
    )


    replace(
        "lib/sbi/nnrf-build.c",

        """    request = ogs_sbi_build_request(&message);
    ogs_expect(request);
end:
    if (LoadItem.value)""",

        """    request = ogs_sbi_build_request(&message);
    ogs_expect(request);

    if (request && getenv("LAB_TRACE")) {

        ogs_info(
            "LAB_SEND "
            "t=%lld "
            "nf=%s "
            "version=%llu "
            "load=%d",

            (long long)ogs_get_monotonic_time(),
            nf_instance->id,
            (unsigned long long)
                nf_instance->lab_load_version,
            nf_instance->load);
    }

end:
    if (LoadItem.value)""",
    )


    replace(
        "lib/sbi/nnrf-build.c",

        """    if (StatusItem.value)
        OpenAPI_any_type_free(StatusItem.value);""",

        """    if (VersionItem.value)
        OpenAPI_any_type_free(VersionItem.value);

    if (StatusItem.value)
        OpenAPI_any_type_free(StatusItem.value);""",
    )


    # -------------------------------------------------------------
    # 5. NRF:
    #    - accept laboratory version operation;
    #    - store it before /load;
    #    - log the exact version together with stored load.
    #
    # Current patch_open5gs.py has already added load validation.
    # -------------------------------------------------------------

    replace(
        "src/nrf/nnrf-handler.c",

        """            if (!strcmp(patch_item->path, OGS_SBI_PATCH_PATH_LOAD)) {""",

        f"""            if (!strcmp(
                    patch_item->path,
                    "{VERSION_PATH}")) {{

                cJSON *v =
                    patch_item->value ?
                    patch_item->value->json :
                    NULL;

                if (!cJSON_IsNumber(v) ||
                        v->valuedouble < 0 ||
                        v->valuedouble !=
                            (uint64_t)v->valuedouble) {{

                    ogs_assert(
                        ogs_sbi_server_send_error(
                            stream,
                            OGS_SBI_HTTP_STATUS_BAD_REQUEST,
                            recvmsg,
                            "lab load version must be "
                            "a non-negative integer",
                            NULL,
                            NULL));

                    return false;
                }}


                nf_instance->lab_load_version =
                    (uint64_t)v->valuedouble;

                /*
                 * Laboratory field handled locally.
                 * Do not pass it to the normal 3GPP path switch.
                 */
                continue;
            }}


            if (!strcmp(
                    patch_item->path,
                    OGS_SBI_PATCH_PATH_LOAD)) {{""",
    )


    replace(
        "src/nrf/nnrf-handler.c",

        """                ogs_info("LAB_NRF t=%lld nf=%s stored=%d",
                    (long long)ogs_get_monotonic_time(), nf_instance->id,
                    nf_instance->load);""",

        """                ogs_info(
                    "LAB_NRF "
                    "t=%lld "
                    "nf=%s "
                    "version=%llu "
                    "stored=%d",

                    (long long)
                        ogs_get_monotonic_time(),
                    nf_instance->id,
                    (unsigned long long)
                        nf_instance->lab_load_version,
                    nf_instance->load);""",
    )


    # -------------------------------------------------------------
    # 6. NRF Discovery response:
    #
    # SearchResult remains standard 3GPP JSON.
    # Correlation data goes into a laboratory HTTP header:
    #
    # X-Lab-Load-Versions:
    #   uuid1=17,uuid2=18,uuid3=16
    # -------------------------------------------------------------

    replace(
        "src/nrf/nnrf-handler.c",

        """        response = ogs_sbi_build_response(&sendmsg, OGS_SBI_HTTP_STATUS_OK);
        ogs_assert(response);
        ogs_assert(true == ogs_sbi_server_send_response(stream, response));

        goto cleanup;""",

        f"""        response =
            ogs_sbi_build_response(
                &sendmsg,
                OGS_SBI_HTTP_STATUS_OK);

        ogs_assert(response);


        if (getenv("LAB_TRACE")) {{

            char *versions =
                ogs_strdup("");

            OpenAPI_lnode_t *lab_node =
                NULL;

            ogs_assert(versions);


            OpenAPI_list_for_each(
                    SearchResult->nf_instances,
                    lab_node) {{

                OpenAPI_nf_profile_t *profile =
                    lab_node->data;

                ogs_sbi_nf_instance_t *lab_nf =
                    NULL;

                char *next = NULL;


                if (!profile ||
                        !profile->nf_instance_id)
                    continue;


                lab_nf =
                    ogs_sbi_nf_instance_find(
                        profile->nf_instance_id);

                if (!lab_nf)
                    continue;


                next =
                    ogs_msprintf(
                        "%s%s%s=%llu",

                        versions,

                        *versions ?
                            "," :
                            "",

                        lab_nf->id,

                        (unsigned long long)
                            lab_nf->lab_load_version);


                ogs_assert(next);

                ogs_free(versions);

                versions = next;
            }}


            if (*versions) {{

                ogs_sbi_header_set(
                    response->http.headers,
                    "{VERSIONS_HEADER}",
                    versions);
            }}


            ogs_free(versions);
        }}


        ogs_assert(
            true ==
            ogs_sbi_server_send_response(
                stream,
                response));


        goto cleanup;""",

        count=1,
    )


    # -------------------------------------------------------------
    # 7. AMF:
    #
    # The current patch already invokes lab_select_smf().
    # After standard SearchResult parsing, attach the NRF versions
    # to the corresponding local NF instances.
    # -------------------------------------------------------------

    replace(
        "src/amf/sbi-path.c",

        """    ogs_nnrf_disc_handle_nf_discover_search_result(message.SearchResult);

    nf_instance = (getenv("LAB_SELECTOR") && target_nf_type == OpenAPI_nf_type_SMF)""",

        f"""    ogs_nnrf_disc_handle_nf_discover_search_result(
        message.SearchResult);


    if (getenv("LAB_TRACE")) {{

        lab_apply_load_versions(
            ogs_sbi_header_get(
                response->http.headers,
                "{VERSIONS_HEADER}"));
    }}


    nf_instance =
        (getenv("LAB_SELECTOR") &&
         target_nf_type ==
            OpenAPI_nf_type_SMF)""",
    )


    # -------------------------------------------------------------
    # Write modified upstream files.
    # -------------------------------------------------------------

    for path, text in pending.items():

        path.write_text(
            text,
            newline="\n")


    # Replace the previous selector completely.
    #
    # This removes the archive inconsistency where patch_open5gs.py
    # included lab-selector.h but did not itself create the file.
    selector_path = ROOT / "src/amf/lab-selector.h"

    selector_path.write_text(
        LAB_SELECTOR,
        newline="\n")


    print(
        "Applied exact load_version correlation patch; "
        "rebuild Open5GS."
    )


if __name__ == "__main__":
    main()