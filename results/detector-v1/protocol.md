# Detector validation, fixed before calibration

Authorized by the user's request to resume the experiment on 2026-10-05,
following discussion of detector calibration and validation.

Primary detector: absolute reported-load minus SCP-observed-load residual,
maximum within a complete 10-second observation window. Existing feature
extraction is retained. Other existing scores are secondary comparisons.

Calibration: nine honest SWRR runs, seeds 201–203 crossed with aggregate
loads 20%, 50%, 70%. Fix each threshold at the pooled calibration-window
99th percentile. Alarm comparison is strictly greater than the threshold.
The nominal quantile is not a guarantee of a 1% test false-alarm rate.

Retrospective evaluation: exactly the 60 runs belonging to the 30 eligible
main-v2 pairs in its ledger, excluding orphan runs and failed attempts.
No threshold tuning on these runs. Results remain retrospective because
the main series already exists.

Prospective weak-attack evaluation: 18 runs, seeds 301–303, both SWRR and
weighted random selection, loads 20%, 50%, 70%, constant alpha=0.25.
Thresholds are frozen before launching these runs. No further tuning.

All new runs: warmup 300, 3300 cycles, operational capacity 100 per SMF,
reported capacity 100, interval .01, same measured binaries as main-v2.
Calibration uses only honest scores; SMF ground truth remains audit-only.

Report false-alarm and detection window fractions by run, condition and
policy, with exploratory bootstrap intervals resampling whole runs.
Three new seeds per condition give limited uncertainty assessment.
Do not interpret correlated windows as independent replicates or count
alarm windows as separate alarm episodes. Onset latency, dynamic attacks,
heterogeneous capacity and cross-implementation evaluation are not
established by this stage.

Execution: four existing isolated workers, persistent per-run outputs,
3600-second run watchdog, 3 GiB minimum free-disk admission threshold.
Any run/audit failure stops new admission and drains current runs.
Creating results/detector-v1/pause-request.json pauses after current runs.
No automatic retries within a single invocation. Completed eligible runs
are skipped on resumption. Total fixed matrix: 27 new runs; no expansion.
