"""Schedule the main-v2 paired experiment matrix without launching any runs.

This controller enforces the serial, per-series discipline documented in the project
protocol: one series per result set, explicit warmup, exact matched workload, and no
mixing of pilot and main-v2 runs in a single analysis table.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_plan():
    plan = []
    for policy in ['swrr', 'random']:
        for rho in [0.2, 0.5, 0.7]:
            active = int(3 * 100 * rho)
            ues = active + 12
            for seed in range(101, 106):
                for alpha in ([0.0, 0.5] if seed % 2 == 0 else [0.5, 0.0]):
                    plan.append({
                        'tag': f'{policy}-r{int(rho * 100)}-s{seed}-a{int(alpha * 100)}',
                        'series_id': 'main-v2',
                        'policy': policy,
                        'rho': rho,
                        'seed': seed,
                        'alpha': alpha,
                        'active': active,
                        'ues': ues,
                        'capacity': 100,
                        'reported_capacity': 100,
                        'attack_mode': 'constant',
                        'warmup': 300,
                        'cycles': 3300,
                        'interval': 0.01,
                        'pair_order': 'balanced_' + ('honest_first' if seed % 2 == 0 else 'attack_first'),
                    })
    return plan


def write_status(path, plan, launched=False):
    status = {
        'series_id': 'main-v2',
        'status': 'planned' if not launched else 'running',
        'pair_count': len(plan) // 2,
        'planned_runs': len(plan),
        'warmup_assignments_excluded': 300,
        'measured_assignments_per_run': 3000,
        'policies': ['swrr', 'random'],
        'rho': [0.2, 0.5, 0.7],
        'seeds': list(range(101, 106)),
        'plan': plan,
        'amendment': 'This controller is for the main-v2 series only; it does not launch experiments unless --launch is set explicitly.',
    }
    path.write_text(json.dumps(status, indent=2), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description='Generate or update the main-v2 experiment schedule.')
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'main-v2')
    p.add_argument('--dry-run', action='store_true', help='Generate schedule metadata without launching any run.')
    p.add_argument('--launch', action='store_true', help='Launch runs. This is intentionally off by default to avoid starting new experiments.')
    a = p.parse_args()

    plan = build_plan()
    a.out.mkdir(parents=True, exist_ok=True)
    write_status(a.out / 'matrix.json', plan, launched=False)

    if a.launch:
        raise SystemExit('Launching the main-v2 matrix is intentionally disabled in this repository. Use explicit run_lab.py commands only after the separate budget is approved.')

    if a.dry_run or not a.launch:
        print(json.dumps({'series_id': 'main-v2', 'pairs': len(plan) // 2, 'runs': len(plan), 'status': 'dry_run'}, indent=2))


if __name__ == '__main__':
    main()
