# Delay and population-step experiment

User authorized continuation after discussion of delivery delays and workload
changes. Fixed matrix: 36 runs, seeds 701–703 x two selectors x three scenarios
x honest/constant alpha=.25. Primary score residual_quantized, frozen zero
threshold from detector-v1, strict greater-than. No tuning on this series.

Scenarios: SMF3 NFM upstream transport delay only; population steps only;
both together. The delay is an application TCP proxy at 127.0.0.250:7777,
forwarding to isolated NRF 127.0.0.10:7777. It delays each upstream read chunk
200 ms, preserving byte order. Reverse bytes have no intentional delay.
Registration and other SMF3 NFM traffic also pass through the proxy.
Actual SEND-to-NRF timing is recorded and median must exceed 150 ms in
each delayed run; a bypass fails the run. This is not an emulation of all
network properties. A short smoke run precedes admission.

Population starts at 150; warmup 300 churn cycles. During 3000 measured
cycles, every 300 cycles target [210,90,150,210,90,150,210,90,150,150].
Create/release operations are serialized real UE commands; transitions
have measurable duration, not instantaneous bursts. Extra measured creates
are counted explicitly (360 planned), so audits include them. Final active
population returns to 150. UE pool 222 for step scenarios, 162 otherwise.
Operational capacity 100 per SMF, heartbeat 1 s. Constant-population runs
retain 3000 measured creates; step runs have 3360. Report cohorts separately.

Per-run quality checks, frozen binaries, disk threshold 3 GiB, run deadline
3600 s, four isolated workers. Failures stop admission and drain active runs.
Pause request at results/delay-burst-v1/pause-request.json. No automatic
increase of repetitions. Save per-run alarm-window fractions; uncertain
rates use run-level resampling. No guarantee inferred from three seeds.

Known scope: offline detector trace evaluation. Delay robustness is allowed
to fail; it is not a reason to increase the frozen threshold on this data.
Any age-aware correction must use a separately documented evaluation stage.
