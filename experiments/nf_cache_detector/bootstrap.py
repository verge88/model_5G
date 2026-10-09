"""Offline state-machine telemetry. NOT Open5GS traffic or a reproduced exploit."""
import hashlib
import json
import random
from pathlib import Path

from detector import extract

HONEST = ('steady', 'legitimate_change', 'failover')
SCENARIOS = HONEST + ('persistent_poison', 'short_poison', 'intermittent_poison')
VISIBILITY = ('full', 'no_cache', 'no_registry', 'no_notify')
SOURCE_ROLES = {
    'nrf-audit': 'registry', 'ausf-cache-audit': 'cache',
    'sbi-route-tap': 'route', 'notify-ingress-tap': 'notify',
    'nrf-subscription-audit': 'subscription',
}


def write_jsonl(path, rows):
    with path.open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, allow_nan=False) + '\n')


def simulate(seed, scenario, visibility, duration=240):
    if scenario not in SCENARIOS or visibility not in VISIBILITY or duration < 120:
        raise ValueError('Unsupported synthetic scenario/visibility/duration')
    rng = random.Random(seed)
    # Addresses and consumer names have no class prefix and never become ML features.
    addresses = [f'http://nf-{rng.getrandbits(48):012x}.example:7777' for _ in range(3)]
    entity = dict(consumer=f'ausf-{rng.getrandbits(48):012x}', nf_type='UDM', service='nudm-ueau')
    onset = duration // 3 + rng.randrange(-8, 9)
    delay = rng.randrange(1, 11)
    period = rng.randrange(25, 36)
    width = rng.randrange(2, 8)
    events, truth = [], {}

    def add(t, source, kind, **data):
        if visibility == 'no_' + SOURCE_ROLES[source]:
            return
        events.append(dict(observed_at=t, source=source, kind=kind, entity=entity, data=data))

    last_cache = addresses[0]
    for t in range(duration + 1):
        poison = (
            scenario == 'persistent_poison' and onset <= t < duration - 30
            or scenario == 'short_poison' and onset <= t < onset + width
            or scenario == 'intermittent_poison' and onset <= t < duration - 30 and (t-onset) % period < width
        )
        authorized_change = scenario in ('legitimate_change', 'failover')
        registry = addresses[1] if authorized_change and t >= onset else addresses[0]
        cache = addresses[1] if authorized_change and t >= onset + delay else addresses[0]
        if poison:
            cache = addresses[2]
        # In failover the old endpoint remains authorized for a transition interval.
        allowed = [registry]
        if scenario == 'failover' and onset <= t <= onset + delay + 5:
            allowed.append(addresses[0])
        truth[t] = int(poison)
        add(t, 'nrf-audit', 'registry_snapshot', complete=True, endpoints=allowed)
        add(t, 'nrf-subscription-audit', 'subscription_snapshot', complete=True,
            bindings=[dict(callback_context='audited-callback', valid_until=duration + 60)])
        # Periodic refresh is a simulation simplification, applied to both classes.
        # Provenance is deliberately unknown, not an oracle exposing the attack label.
        if t % 10 == 0 or cache != last_cache or (authorized_change and t == onset):
            add(t, 'notify-ingress-tap', 'notification', endpoints=[cache],
                sender_verified=None, callback_context='audited-callback')
        add(t, 'ausf-cache-audit', 'cache_snapshot', complete=True, endpoints=[cache])
        add(t, 'sbi-route-tap', 'route', endpoint=cache)
        last_cache = cache
    return events, truth


def generate(out, config, seed_offset=20261010, duration=240):
    if out.exists():
        raise ValueError('Refuse to overwrite a generated dataset')
    out.mkdir(parents=True)
    runs = []
    for split, start, count in [('train', 0, 4), ('calibration', 100, 3), ('test', 200, 3)]:
        scenarios = HONEST if split == 'calibration' else SCENARIOS
        for number in range(count):
            seed = seed_offset + start + number
            for scenario in scenarios:
                for visibility in VISIBILITY:
                    run_id = f'{split}-{seed}-{scenario}-{visibility}'
                    events, truth = simulate(seed, scenario, visibility, duration)
                    rows = list(extract(events, config))
                    labels = [dict(observed_at=r['observed_at'], entity=r['entity'],
                                   label=truth[int(r['observed_at'])]) for r in rows]
                    files = {name: f'{run_id}.{name}.jsonl' for name in ('events', 'features', 'labels')}
                    for name, data in [('events', events), ('features', rows), ('labels', labels)]:
                        write_jsonl(out / files[name], data)
                    runs.append(dict(run_id=run_id, seed=seed, split=split, scenario=scenario,
                                     visibility=visibility, **files))
    manifest = dict(schema_version=1, data_origin='synthetic-bootstrap',
                    disclaimer='Offline state machine; not a reproduced Open5GS vulnerability; not article evidence.',
                    generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    seed_offset=seed_offset, duration_seconds=duration, runs=runs)
    path = out / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return path
