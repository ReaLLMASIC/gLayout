"""Read installed second-framework/PDK resources in the fixed existing EDA image."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
SCRIPT="""from pathlib import Path
import importlib.util,json
root=Path('/foss/pdks');out={'pdks':[]}
for p in sorted(root.iterdir()):
 if not p.is_dir():continue
 tech=p/'libs.tech';out['pdks'].append({'name':p.name,'tech_dirs':[q.name for q in tech.iterdir()] if tech.exists() else [],'magic_files':[q.name for q in (tech/'magic').iterdir()] if (tech/'magic').exists() else [],'ngspice_files':[q.name for q in (tech/'ngspice').iterdir()] if (tech/'ngspice').exists() else []})
out['framework_imports']={name:importlib.util.find_spec(name) is not None for name in ['laygo2','bag','gdstk']}
tools=Path('/foss/tools');out['related_tool_dirs']=[p.name for p in tools.iterdir() if any(s in p.name.lower() for s in ['laygo','bag'])] if tools.exists() else []
print(json.dumps(out))
"""


def main():
    image='hpretl/iic-osic-tools@sha256:7ef29be71a33b5b8994cde7f7476dfefd1af94f2922354242d1579346feec462'
    argv=['docker','run','--rm','--pull','never','--network','none','--cpus','.5','--memory','1g','--entrypoint','python3',image,'-c',SCRIPT]
    start=time.monotonic();r=subprocess.run(argv,capture_output=True,text=True,timeout=60)
    record={'at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Read-only inventory of already installed second-PDK and framework dependencies',
        'argv':argv,'returncode':r.returncode,'wall_seconds':time.monotonic()-start,'stdout':r.stdout,'stderr':r.stderr}
    path=ROOT/'reproducibility/additional_framework_pdk_inventory.json';path.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k!='argv'}))


if __name__=='__main__':main()
