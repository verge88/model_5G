"""Check exported patches against pristine archives and the measured sources."""
from pathlib import Path
import hashlib,json,re,subprocess
R=Path('/work');result={}
for repo,directory,patch,live in [
    ('open5gs','open5gs','open5gs-v2.8.0-lab.patch','/build/pristine'),
    ('UERANSIM','ueransim','ueransim-v3.2.7-cli.patch','/build/model5g-ueransim')]:
    root=Path('/tmp/model5g-verify')/directory
    text=(R/'patches'/patch).read_text()
    for rel in re.findall(r'^--- a/(.+)$',text,re.M):
        p=root/rel;p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
    subprocess.run(['git','apply','--check',str(R/'patches'/patch)],cwd=root,check=True)
    checks={}
    for rel in re.findall(r'^\+\+\+ b/(.+)$',text,re.M):
        expected=(R/'upstream'/repo/rel).read_bytes().replace(b'\r\n',b'\n')
        actual=(Path(live)/rel).read_bytes().replace(b'\r\n',b'\n')
        checks[rel]={'equal':expected==actual,'sha256':hashlib.sha256(actual).hexdigest()}
    result[repo]={'pristine_patch_check':'passed','live_source_matches':all(v['equal'] for v in checks.values()),'files':checks}
(R/'results/reproducibility.json').write_text(json.dumps(result,indent=2))
print(json.dumps({repo:{k:v for k,v in r.items() if k!='files'} for repo,r in result.items()},indent=2))
assert all(r['live_source_matches'] for r in result.values())
