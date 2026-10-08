# Prospective quantization validation

Continuation authorized by user after robustness-v1. Hypothesis selected
after seeing the heterogeneous-control failure of raw residual: matching
the integer load representation reduces benign alarms without losing
constant alpha=.25 detection. Prior robustness results are exploratory.

Primary detector: residual_quantized = abs(reported - floor(observed)),
evaluated at target NRF updates, maximum over complete 10-second windows.
Retain frozen detector-v1 threshold 0 and strict greater-than comparison.
Raw residual remains a secondary comparator. This is analysis of traces,
not a deployed online detector. No threshold re-fitting on new data.

Exactly 12 new runs: seeds 501–503 x SWRR/random x honest/alpha=.25.
SMF3 trusted operational capacity 70, other SMFs 100; active population
150 gives aggregate utilization 55.6%. Heartbeat 1 second, warmup 300,
3000 measured cycles. New seeds are disjoint from all previous stages.
No additional scenarios or adaptive sample extension.

Report all per-run fractions, macro averages, and exploratory run-level
uncertainty by policy and attack state. Criteria fixed before launch:
mean per-run benign alarm-window fraction <=1% and mean attack alarm-window
fraction >=95% for each policy. These are empirical acceptance criteria,
not guarantees of population error rates with three runs per condition.

Inherited safeguards: audit unchanged, complete run archiving, 3600-second
per-run deadline, minimum 3 GiB free disk for new admission, stop admission
on any run/audit failure and drain active runs. A pause-request.json in
this directory drains current runs. Completed eligible runs are retained.
