import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import scsp_root_merge as m

def curve(a=2,b=4):
 return dict(m_Curve=[dict(time=0,value=a,inSlope=1,outSlope=1,weightedMode=0,inWeight=.3,outWeight=.3),dict(time=1,value=b,inSlope=1,outSlope=1,weightedMode=0,inWeight=.3,outWeight=.3)])
def root():return dict(root=0,rootScaling=1,pos_x=curve(),pos_z=curve(-1,1))
def body():return '  m_Name: dance_01\n  m_FloatCurves:\n  - serializedVersion: 2\n    attribute: RootT.y\n    classID: 95\n  m_PPtrCurves: []\n  m_AnimationClipSettings:\n    m_StopTime: 1\n'

class RootMergeTests(unittest.TestCase):
 def test_clip_identity_removes_internal_extensions(self):
  for name in ('dance_01','Dance_01.anim','DANCE_01.anim.anim'):
   self.assertEqual('dance_01',m.clip_identity(name))
 def test_relative_start_reference_scale_and_body_preserved(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'dance.anim';p.write_text(body());before=p.read_bytes();out=Path(td)/'dance_with_root.anim'
   report=m.merge_clip(p,out,root(),.5);text=out.read_text()
   self.assertEqual(before,p.read_bytes());self.assertIn('value: 4\n',text)
   self.assertIn('outSlope: 2\n',text);self.assertIn('attribute: MotionT.x',text);self.assertIn('attribute: MotionT.z',text)
   self.assertEqual(.5,report['reference_human_scale'])
   self.assertEqual(2,report['merge_version']);self.assertTrue(report['root_pose_compensated'])
   for prefix in ('RootT','MotionT'):
    for axis in 'xz':self.assertEqual(1,text.count('attribute: '+prefix+'.'+axis))
   self.assertEqual(body().split('  m_Name: dance_01\n')[1].split('  m_PPtrCurves:')[0],text.split('  m_Name: dance_with_root\n')[1].split('  - serializedVersion: 2\n    curve:')[0])
 def test_reject_existing_horizontal_root_or_motion(self):
  for name in ('RootT.x','MotionT.x','RootT.z','MotionT.z'):
   with self.subTest(name=name),tempfile.TemporaryDirectory() as td:
    p=Path(td)/'dance.anim';p.write_text(body().replace('RootT.y',name))
    with self.assertRaisesRegex(ValueError,'重复叠加'):m.merge_clip(p,Path(td)/'new.anim',root())
 def test_reject_unsafe_data_and_duration(self):
  bad=[]
  r=root();r['root']=1;bad.append(r)
  r=root();r['rootScaling']=float('nan');bad.append(r)
  r=root();r['rot_w']=curve();bad.append(r)
  r=root();r['pos_y']=curve();bad.append(r)
  r=root();r['pos_x']['m_Curve'][1]['time']=0;bad.append(r)
  r=root();r['pos_x']['m_Curve'][1]['time']=2;bad.append(r)
  for r in bad:
   with self.subTest(root=r),tempfile.TemporaryDirectory() as td:
    p=Path(td)/'dance.anim';p.write_text(body());out=Path(td)/'new.anim'
    with self.assertRaises(ValueError):m.merge_clip(p,out,r)
    self.assertFalse(out.exists());self.assertFalse(out.with_suffix('.anim.part').exists())
 def test_false_scaling_flag_does_not_zero_or_reject_movement(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'body.anim';p.write_text(body());out=Path(td)/'new.anim';data=root();data['rootScaling']=0
   report=m.merge_clip(p,out,data)
   self.assertFalse(report['source_root_scaling_flag']);self.assertIn('value: 2\n',out.read_text())
 def test_refuse_overwrite(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'dance.anim';p.write_text(body());out=Path(td)/'new.anim';out.write_text('user edit')
   with self.assertRaises(ValueError):m.merge_clip(p,out,root())
   self.assertEqual('user edit',out.read_text())
 def test_internal_anim_suffix_and_station_pairing(self):
  import UnityPy,runtime_paths
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'tools/PoseWorker').mkdir(parents=True);(p/'tools/PoseWorker/model.json').write_text('{"humanScale":1}')
   (p/'animations').mkdir();(p/'animations/dance_01.anim').write_text(body());raw=b'root';(p/'root').write_bytes(raw)
   data=dict(entries=[dict(id='body',type='anim',name='dance_01.anim'),dict(id='root',type='asset',name='dance_02_root.asset',file='r')],selected_ids=['body','root'],outputs=[dict(file='r',output='root',sha256=hashlib.sha256(raw).hexdigest())])
   report=dict(clips=[dict(file='animations/dance_01.anim')],sources=[dict(name='dance_01.anim',resource='dance_01.anim')])
   with patch.object(runtime_paths,'app_root',return_value=p),patch.object(UnityPy,'load',return_value=NS(objects=[])) as load:
    m.export_merged_roots(p,data,report,p/'animations');load.assert_not_called()
   self.assertEqual(1,len(report['clips']))
   data['entries'][1]['name']='dance_01_root.asset'
   obj=NS(type=NS(name='MonoBehaviour'),read_typetree=lambda:dict(rootCurveData=root()))
   with patch.object(runtime_paths,'app_root',return_value=p),patch.object(UnityPy,'load',return_value=NS(objects=[obj])):
    m.export_merged_roots(p,data,report,p/'animations')
   self.assertEqual('body_with_root',report['clips'][-1]['kind']);self.assertTrue((p/'animations/dance_01_with_root.anim').exists())

if __name__=='__main__':unittest.main()
