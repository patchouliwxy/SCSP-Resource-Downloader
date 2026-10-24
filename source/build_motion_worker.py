"""Rebuild the bundled offline Humanoid retarget worker (Unity needed only here)."""
import argparse,json,shutil,subprocess
from pathlib import Path

root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--unity',type=Path,required=True)
args=parser.parse_args()
project=root/'research/MotionPreviewWorker'
result=subprocess.run([str(args.unity),'-batchmode','-projectPath',str(project),'-executeMethod','BuildPoseWorker.Build','-logFile',str(project.parent/'build-worker.log')],timeout=1200)
if result.returncode:raise SystemExit(result.returncode)
output=project.parent/'worker'
if not (output/'SCSPPoseWorker.exe').is_file():raise RuntimeError('Missing built worker')
model=json.loads((output/'model.json').read_text(encoding='utf-8'))
config=json.loads((project/'preview-materials.json').read_text(encoding='utf-8'))
for mesh in model['meshes']:
    mesh['materials']=[config[name] for name in mesh['materialNames']]
(output/'model.json').write_text(json.dumps(model,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
shutil.copytree(project/'PreviewTextures',output/'textures',dirs_exist_ok=True)
shutil.copytree(output,root/'tools/PoseWorker',dirs_exist_ok=True)
print('Humanoid preview worker installed at',root/'tools/PoseWorker')
