"""One reproducible training entry point for local execution and GitHub Actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

from bootstrap import generate
from model import train

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def repository_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A nonempty repository-relative manifest path is required')
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError('Manifest must be an existing file inside this checkout')
    return path


def validate_dataset_paths(manifest):
    data = json.loads(manifest.read_text(encoding='utf-8'))
    for run in data['runs']:
        for field in ('features', 'labels'):
            path = (manifest.parent / run[field]).resolve()
            if not path.is_relative_to(manifest.parent) or not path.is_file():
                raise ValueError('Dataset members must be files inside the manifest directory')
    return data


def summary(report, evaluation, origin):
    lines = ['# NF cache detector training', '', f'Data origin: **{origin}**', '',
             'Synthetic results are software validation, not evidence of real attack detection.'
             if origin == 'synthetic-bootstrap' else 'Real-capture provenance is supplied by the dataset author; it is not automatically attested.',
             '', f"Calibrated specialist masks: {', '.join(report['thresholds']['specialist']) or 'NONE'}", '',
             '| Model | Label | Windows | Scored | Abstained | ML alarms | Rules on same windows |',
             '|---|---|---:|---:|---:|---:|---:|']
    for model, runs in evaluation['by_model'].items():
        for label in ['0', '1']:
            fields = ['total', 'scored', 'abstained', 'ml_alarms', 'rules_alarms_on_same_scored_rows']
            totals = [sum(run['labels'][label][f] for run in runs) for f in fields]
            lines.append('| ' + ' | '.join(map(str, [model, label, *totals])) + ' |')
    lines += ['', 'Label 0 = honest state; label 1 = poisoned state. Counts are correlated windows.',
              'No deployment readiness or ML superiority claim. Full per-run evaluation is in the artifact.',
              'Calibration targets empirical FPR 0.1%; this is not a guarantee on new traffic.', '']
    return '\n'.join(lines)


def run(request_path, out):
    request = json.loads(request_path.read_text(encoding='utf-8'))
    mode = request.get('mode')
    if mode not in ('synthetic-bootstrap', 'real-capture'):
        raise ValueError('Unknown training mode')
    if out.exists():
        raise ValueError('Output must be a new directory; never overwrite previous results')
    out.mkdir(parents=True)
    if mode == 'synthetic-bootstrap':
        manifest = generate(out / 'dataset', json.loads((HERE/'observer_config.json').read_text()),
                            seed_offset=int(request['seed_offset']), duration=int(request['duration_seconds']))
    else:
        manifest = repository_path(request.get('manifest'))
        data = validate_dataset_paths(manifest)
        if data.get('data_origin') != 'real-capture' or not data.get('provenance'):
            raise ValueError('Real-capture mode needs explicit provenance; synthetic data cannot silently substitute')
    report = train(manifest, out/'model', HERE/'observer_config.json')
    (out/'dataset-manifest.json').write_bytes(manifest.read_bytes())
    evaluation = json.loads((out/'model'/'test-evaluation.json').read_text())
    (out/'SUMMARY.md').write_text(summary(report, evaluation, mode), encoding='utf-8')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    record = dict(mode=mode, python=platform.python_version(), commit=commit, request=request,
                  github_run_id=os.environ.get('GITHUB_RUN_ID'), github_run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'),
                  request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),
                  workflow_sha256=hashlib.sha256((ROOT/'.github/workflows/nf-cache-training.yml').read_bytes()).hexdigest(),
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'bootstrap.py', HERE/'run_training.py', HERE/'requirements-ci.txt']},
                  data_origin=json.loads(manifest.read_text())['data_origin'])
    (out/'training-run.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print((out/'SUMMARY.md').read_text(encoding='utf-8'))
    if not report['thresholds']['specialist']:
        raise ValueError('Training produced no calibrated masks; inspect the saved diagnostics')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, default=HERE/'training_request.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.request, args.out)
