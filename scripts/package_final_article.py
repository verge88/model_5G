"""Create a compact, checksummed manuscript and analysis snapshot (no raw traces)."""
import csv, hashlib, json, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/SMF_Article_20261007.zip'
files = set()
def add(path):
    if path.is_file(): files.add(path)

for name in ['article/ARTICLE_FINAL_20261007.md', 'article/REPRODUCIBILITY.md',
             'output/pdf/SMF_Load_Veracity_Final_20261007.pdf', 'Dockerfile', 'compose.yaml']:
    add(ROOT / name)
for folder in ['scripts', 'patches', 'article/figures/final20261007', 'results/article-final-20261007']:
    for path in (ROOT / folder).rglob('*'):
        if '__pycache__' not in path.parts: add(path)
for cohort in json.loads((ROOT / 'results/article-final-20261007/summary.json').read_text())['cohorts']:
    folder = ROOT / 'results' / cohort['stage']
    for path in folder.iterdir():
        if path.suffix in {'.json', '.md', '.csv'} and not any(x in path.name for x in ['.features.', '.timeaware.']):
            add(path)
    for path in (folder / 'main-evaluation').glob('*'): add(path)
with (ROOT / 'results/article-final-20261007/selected-runs.csv').open() as stream:
    for row in csv.DictReader(stream): add(ROOT / 'runs' / row['run'] / 'manifest.json')
hashes = []
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        name = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        archive.writestr(name, data)
        hashes.append(hashlib.sha256(data).hexdigest() + '  ' + name)
    archive.writestr('SHA256SUMS.txt', '\n'.join(hashes) + '\n')
with zipfile.ZipFile(OUT) as archive:
    assert archive.testzip() is None
    for line in archive.read('SHA256SUMS.txt').decode().splitlines():
        digest, name = line.split('  ', 1)
        assert hashlib.sha256(archive.read(name)).hexdigest() == digest
print(f'{OUT}: {len(files)} files, {OUT.stat().st_size:,} bytes; checksums verified')
