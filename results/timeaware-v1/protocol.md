# Fixed age-aware detector, before prospective validation

The detector compares integer reported load with the minimum/maximum integer
SCP-observed load in the preceding 500 ms. Score is distance outside that
range, with threshold 0 and maximum over the existing complete 10-second
windows. A range includes the state at its left boundary and no future events.
SMF LOAD timestamps, values and load versions do not enter the score.
Only NF-ID inventory mapping uses instrumentation. NRF receipt and SCP
events use a common laboratory monotonic clock.

500 ms is an engineering assumption fixed before replay/validation: it covers
the configured 200 ms transport delay with margin. It is not a proven general
bound. No search over history lengths, no threshold fitting on these runs.
Replay of previous delay-burst-v1 is development evidence, not independent
confirmation. Baseline scores must reproduce saved quantized scores exactly.

Prospective matrix: 24 runs, seeds 1001–1003 x two policies x delay-only /
delay-plus-population-steps x honest / alpha=.25. Same runner and binaries,
300 warmup and 3000 measured churn cycles. Step runs have 360 extra creates.
Delay proxy 200 ms and actual delay validation retained. No replacement or
addition of conditions based on observed detector outcomes.

Primary per-policy, per-scenario criteria: mean benign alarm-window fraction
<=1%, mean attack alarm-window fraction >=95%. Report per-run outcomes even
if a mean passes. Three-run evidence does not guarantee these population rates.

Known limitations: larger history can hide weaker attacks; no testing yet
of report ages beyond 500 ms, independent collector latency or clock skew.
This remains offline trace analysis, not a deployed online implementation.
Scientific audits, 3 GiB disk floor, 3600-second run deadline and pause marker
are inherited. Pause path: results/timeaware-v1/pause-request.json.
