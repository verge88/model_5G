# Fixed robustness extension

Authorized by the user to continue after detector-v1 completed.
24 new runs: four scenarios x two selection policies x seeds 401,402,403.
All use active population 150, 300 warmup cycles, 3000 measured cycles,
same measured binaries, and the existing per-run quality audit.

Scenarios: honest 5-second NRF heartbeat; constant alpha .25 with 5-second
heartbeat; honest SMF3 operational capacity 70 (other SMFs 100); alpha .25
on/off attack, switching every 30 load versions with a 1-second heartbeat.
Both SWRR and weighted random selection are tested. The nominal population
is fixed at 150: heterogeneous total operational capacity is 270, so its
aggregate utilization is 55.6%, not 50%. Treat it as a separate control.

Thresholds are copied unchanged from detector-v1 before admission. Primary
score is residual; quantization-aware residual and other scores remain
secondary. No recalibration, threshold optimization, or automatic extra runs.
The heterogeneous case specifically tests normal integer load rounding.

Report per-run alarm-window fractions and eligibility. For on/off attacks,
overall alarm fraction includes inactive intervals and cannot be described
as detection probability. Event-level onset/offset analysis is separate.
Heartbeat interval is slower reporting, not injected network transport delay.
This stage does not test another 5G implementation or bursty total population.

Stop admission on run/audit failure or less than 3 GiB free disk; drain other
current runs. Each run has a 3600-second deadline. Pause requests at
results/robustness-v1/pause-request.json drain current runs. Persist complete
outputs and skip eligible results on an explicit resume.
