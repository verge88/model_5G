"""Create checksums for raw evidence and a conservative compute budget summary."""
from pathlib import Path
import hashlib,json
R=Path(__file__).resolve().parents[1]
audit=json.loads((R/'results/article-evaluation/audit.json').read_text())
names=[r['run'] for r in audit['runs'] if r['eligible']]+['b0-order123-v2','b0-order231-v2','b0-order312-v2']
checks={}
for name in names:
    folder=R/'runs'/name
    for p in sorted(folder.rglob('*')):
        if not p.is_file():continue
        if not (p.suffix in ('.log','.stdout','.pcap','.yaml','.txt') or p.name in ('manifest.json','workload.jsonl')):continue
        digest=hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
        checks[p.relative_to(R).as_posix()]={'bytes':p.stat().st_size,'sha256':digest.hexdigest()}
(R/'results/evidence-sha256.json').write_text(json.dumps(checks,indent=2))
raw=0
for path in (R/'runs').glob('*/manifest.json'):
    m=json.loads(path.read_text());raw+=max(0,m.get('finished',m['started'])-m['started'])
accounted=max(json.loads(p.read_text()).get('active_seconds',0) for p in (R/'results').glob('article*/matrix.json'))
budget={'approved_seconds':14400,'raw_manifest_active_seconds':raw,'conservative_controller_seconds':accounted,
        'within_budget':max(raw,accounted)<=14400,'eligible_article_runs':len(audit['runs']),
        'successful_article_establishments':sum(r['established'] for r in audit['runs'] if r['eligible']),
        'matched_pairs':sum(e['independent_pairs'] for e in audit['effects']),
        'hashed_raw_files':len(checks),'note':'Cumulative active experiments including debug and failed attempts; parallel workers do not each receive a separate four-hour budget. Idle overnight containers and document preparation excluded.'}
(R/'results/budget-summary.json').write_text(json.dumps(budget,indent=2))
print(json.dumps(budget,indent=2));assert budget['within_budget']
