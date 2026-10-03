"""Export the complete measured derivative, including newly added headers."""
from pathlib import Path
import subprocess
import difflib
import hashlib
import json
R=Path(__file__).resolve().parents[1]
out=R/'patches';out.mkdir(exist_ok=True)
manifest={}
for repo,name in [('open5gs','open5gs-v2.8.0-lab'),('UERANSIM','ueransim-v3.2.7-cli')]:
    root=R/'upstream'/repo
    diff=subprocess.check_output(['git','-C',str(root),'-c','core.autocrlf=true','diff','--binary','HEAD'])
    if repo=='open5gs':
        path='src/amf/lab-selector.h'
        # This header may be untracked or ignored in the nested checkout.
        tracked=subprocess.run(['git','-C',str(root),'ls-files','--error-unmatch',path],capture_output=True).returncode==0
        if not tracked:
            body=(root/path).read_text().splitlines(keepends=True)
            diff+=('diff --git a/'+path+' b/'+path+'\nnew file mode 100644\n'+
                   ''.join(difflib.unified_diff([],body,fromfile='/dev/null',tofile='b/'+path))).encode()
    (out/f'{name}.patch').write_bytes(diff)
    manifest[repo]={'commit':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),
                    'patch_sha256':hashlib.sha256(diff).hexdigest()}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2))
