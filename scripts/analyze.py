"""Analyze real Open5GS laboratory traces.

The analyzer never substitutes synthetic records for missing traces.

Legacy runs without load_version remain readable.

For new runs the exact correlation key is:

    (NF instance ID, load_version)

This allows exact SMF -> NRF -> AMF timing measurements.
"""

import argparse
import json
import gzip
import math
from pathlib import Path
import re
from statistics import median
from urllib.parse import urlsplit


EVENT = re.compile(
    r"LAB_(LOAD|SEND|NRF|SELECT|CANDIDATE|SCP) "
    r"(.*?)(?: \([^\n]*\))?$"
)

FIELD = re.compile(
    r"(\w+)=([^\s]+)"
)


def read_trace(path):
    if not path.exists() and Path(str(path)+'.gz').exists():
        path=Path(str(path)+'.gz')
    if path.suffix=='.gz':
        with gzip.open(path,'rt',errors='replace') as stream:return stream.read()
    return path.read_text(errors='replace')


def events(path):
    """Yield parsed laboratory log records."""

    for line in read_trace(path).splitlines():

        match = EVENT.search(line)

        if not match:
            continue


        fields = dict(
            FIELD.findall(
                match[2]))


        if "t" not in fields:
            continue


        yield {
            "kind": match[1],
            "source": path.name.removesuffix('.gz'),
            **fields,
        }


def context_key(uri, target=""):
    """Normalize an SM-context resource URI."""

    if uri.startswith("http"):
        return uri.rstrip("/")

    return (
        target.rstrip("/") +
        "/" +
        uri.lstrip("/")
    )


def percentile(values, q):
    """Linear interpolated percentile."""

    if not values:
        return None

    xs = sorted(values)

    if len(xs) == 1:
        return xs[0]


    pos = (len(xs) - 1) * q

    lo = math.floor(pos)
    hi = math.ceil(pos)


    if lo == hi:
        return xs[lo]


    return (
        xs[lo] +
        (xs[hi] - xs[lo]) *
        (pos - lo)
    )


def stats_ms(values):
    """Summary for a millisecond-valued sample."""

    if not values:
        return None


    return {
        "n": len(values),

        "min_ms":
            min(values),

        "median_ms":
            median(values),

        "p90_ms":
            percentile(
                values,
                0.90),

        "p95_ms":
            percentile(
                values,
                0.95),

        "p99_ms":
            percentile(
                values,
                0.99),

        "max_ms":
            max(values),
    }


def ivalue(event, key):
    """Safely read an integer event field."""

    if not event:
        return None

    try:
        return int(event[key])

    except (
            KeyError,
            TypeError,
            ValueError):
        return None


def version_key(event):
    """Return exact correlation key or None for legacy logs."""

    nf = event.get("nf")

    version = ivalue(
        event,
        "version")


    if not nf or version is None:
        return None


    return (
        nf,
        version,
    )


def propagation(rows):
    """Correlate exact load versions across SMF, NRF and AMF.

    ogs_get_monotonic_time() values are handled as microseconds.

    Returned durations are milliseconds.

    Important distinction:

    compute_to_nrf:
        actual propagation/update delay.

    age_at_candidate / age_at_selection:
        age of a self-report when AMF later uses it.

    The latter contains waiting time until a subsequent NF Discovery
    and therefore must not be called network latency.
    """

    grouped = {}


    for event in rows:

        if event["kind"] not in {
                "LOAD",
                "SEND",
                "NRF",
                "CANDIDATE",
                "SELECT"}:
            continue


        key = version_key(event)

        if key is None:
            continue


        grouped.setdefault(
            key,
            {}).setdefault(
                event["kind"],
                []).append(event)


    chains = []

    compute_to_send = []
    send_to_nrf = []
    compute_to_nrf = []

    age_at_candidate = []
    age_at_selection = []


    for (
            nf,
            version), by_kind in sorted(
                grouped.items()):


        loads = sorted(
            by_kind.get(
                "LOAD",
                []),

            key=lambda x:
                int(x["t"]))


        sends = sorted(
            by_kind.get(
                "SEND",
                []),

            key=lambda x:
                int(x["t"]))


        nrfs = sorted(
            by_kind.get(
                "NRF",
                []),

            key=lambda x:
                int(x["t"]))


        candidates = sorted(
            by_kind.get(
                "CANDIDATE",
                []),

            key=lambda x:
                int(x["t"]))


        selections = sorted(
            by_kind.get(
                "SELECT",
                []),

            key=lambda x:
                int(x["t"]))


        # A heartbeat should normally have one SEND.
        #
        # LOAD can occur more than once with the same version because
        # upstream Open5GS recalculates load for several SBI timer cases.
        #
        # Therefore choose the latest LOAD not later than the heartbeat SEND.

        send = (
            sends[0]
            if sends
            else None
        )


        if send:

            send_t = int(
                send["t"])


            eligible = [
                event
                for event in loads
                if int(event["t"]) <=
                    send_t
            ]


            load = (
                eligible[-1]
                if eligible
                else (
                    loads[-1]
                    if loads
                    else None
                )
            )

        else:

            load = (
                loads[-1]
                if loads
                else None
            )


        nrf = (
            nrfs[0]
            if nrfs
            else None
        )


        row = {
            "nf":
                nf,

            "version":
                version,

            "load_t":
                ivalue(
                    load,
                    "t"),

            "send_t":
                ivalue(
                    send,
                    "t"),

            "nrf_t":
                ivalue(
                    nrf,
                    "t"),

            "reported":
                ivalue(
                    load,
                    "reported"),

            "stored":
                ivalue(
                    nrf,
                    "stored"),

            "candidate_count":
                len(candidates),

            "selection_count":
                len(selections),
        }


        if load and send:

            value = (
                int(send["t"]) -
                int(load["t"])
            ) / 1000.0


            row[
                "compute_to_send_ms"
            ] = value


            compute_to_send.append(
                value)


        if send and nrf:

            value = (
                int(nrf["t"]) -
                int(send["t"])
            ) / 1000.0


            row[
                "send_to_nrf_ms"
            ] = value


            send_to_nrf.append(
                value)


        if load and nrf:

            value = (
                int(nrf["t"]) -
                int(load["t"])
            ) / 1000.0


            row[
                "compute_to_nrf_ms"
            ] = value


            compute_to_nrf.append(
                value)


        if load:

            load_t = int(
                load["t"])


            for event in candidates:

                value = (
                    int(event["t"]) -
                    load_t
                ) / 1000.0


                if value >= 0:

                    age_at_candidate.append(
                        value)


            for event in selections:

                value = (
                    int(event["t"]) -
                    load_t
                ) / 1000.0


                if value >= 0:

                    age_at_selection.append(
                        value)


        chains.append(
            row)


    return {
        "chains":
            chains,

        "compute_to_send":
            stats_ms(
                compute_to_send),

        "send_to_nrf":
            stats_ms(
                send_to_nrf),

        "compute_to_nrf":
            stats_ms(
                compute_to_nrf),

        "age_at_candidate":
            stats_ms(
                age_at_candidate),

        "age_at_selection":
            stats_ms(
                age_at_selection),
    }


def analyze(folder):
    """Analyze one experiment directory."""

    manifest = json.loads(
        (
            folder /
            "manifest.json"
        ).read_text()
    )


    rows = sorted(

        [
            event

            for logfile
            in list(folder.glob("*.log")) + list(folder.glob("*.log.gz"))

            for event
            in events(logfile)
        ],

        key=lambda event:
            int(event["t"]),
    )


    active = {}
    callbacks = {}
    created = {}
    releases = {}

    anomalies = []


    # ---------------------------------------------------------
    # SCP independent session accounting
    # ---------------------------------------------------------

    for event in rows:

        if event["kind"] != "SCP":
            continue


        status = int(
            event["status"])


        location = event.get(
            "location",
            "-")


        # Successful CreateSMContext
        if (
                status == 201 and
                "/sm-contexts/" in
                location):


            key = context_key(
                location)


            smf = urlsplit(
                key).hostname


            if key in active:

                anomalies.append({
                    "type":
                        "duplicate_create",

                    **event,
                })


            else:

                active[key] = smf


                created[smf] = (
                    created.get(
                        smf,
                        0) +
                    1
                )


                if event.get(
                        "callback",
                        "-") != "-":


                    callbacks[
                        urlsplit(
                            event[
                                "callback"]
                        ).path
                    ] = key


        # Successful release path
        if 200 <= status < 300:

            key = None


            if event.get(
                    "released") == "1":


                key = callbacks.get(
                    urlsplit(
                        event["uri"]
                    ).path
                )


            elif event[
                    "uri"].endswith(
                        "/release"):


                key = context_key(

                    event["uri"][:-8],

                    event.get(
                        "target",
                        "")
                )


            if key in active:

                smf = active.pop(
                    key)


                releases[smf] = (
                    releases.get(
                        smf,
                        0) +
                    1
                )


    # ---------------------------------------------------------
    # Selection / load statistics
    # ---------------------------------------------------------

    loads = [
        event
        for event in rows
        if event["kind"] ==
            "LOAD"
    ]


    selections = [
        event
        for event in rows
        if event["kind"] ==
            "SELECT"
    ]


    candidates = [
        event
        for event in rows
        if event["kind"] ==
            "CANDIDATE"
    ]


    versioned = [
        event
        for event in rows
        if version_key(event)
        is not None
    ]


    ue_stdout = read_trace(
        folder /
        "ue.stdout"
    )


    prop = propagation(
        rows)


    result = {

        "mode":
            manifest["mode"],

        "run_complete":
            manifest["complete"],


        "scp_created":
            created,

        "scp_released":
            releases,


        "scp_active": {

            host:
                list(
                    active.values()
                ).count(host)

            for host
            in created
        },


        "selections":
            len(selections),

        "candidates":
            len(candidates),

        "load_samples":
            len(loads),

        "versioned_events":
            len(versioned),


        "propagation": {

            key: value

            for key, value
            in prop.items()

            if key !=
                "chains"
        },


        "anomalies":
            anomalies,


        "ueransim_established":
            len(
                re.findall(
                    "PDU Session "
                    "establishment "
                    "is successful",

                    ue_stdout,
                )
            ),
    }


    # ---------------------------------------------------------
    # Persist machine-readable outputs
    # ---------------------------------------------------------

    (
        folder /
        "events.jsonl"
    ).write_text(

        "".join(

            json.dumps(
                event,
                ensure_ascii=False
            ) + "\n"

            for event
            in rows
        )
    )


    (
        folder /
        "load_version_chains.jsonl"
    ).write_text(

        "".join(

            json.dumps(
                chain,
                ensure_ascii=False
            ) + "\n"

            for chain
            in prop["chains"]
        )
    )


    (
        folder /
        "summary.json"
    ).write_text(

        json.dumps(
            result,
            indent=2,
            ensure_ascii=False
        )
    )


    return result


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "folder",
        type=Path)

    args = parser.parse_args()


    print(
        json.dumps(
            analyze(
                args.folder),
            indent=2,
            ensure_ascii=False
        )
    )
