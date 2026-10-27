using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.Build.Reporting;
using UnityEngine;

[Serializable] public class RigNode {public string name;public int parent;public float[] position,rotation,scale;}
[Serializable] public class RigGroup {public int start,count,material;}
[Serializable] public class RigMorph {public string name;public float[] positions;}
[Serializable] public class RigMesh {public string name;public int node;public float[] positions,normals,uv,weights,bindPoses;public int[] indices,joints,bones;public RigGroup[] groups;public string[] materialNames;public RigMorph[] morphs;}
[Serializable] public class RigModel {public int schema=1;public string id="chiyoko-preview-v1",name="園田 智代子";public bool humanoid;public float humanScale;public RigNode[] nodes;public RigMesh[] meshes;public string[] muscles;}
public static class BuildPoseWorker {
 static float[] V(Vector3 v){return new[]{v.x,v.y,v.z};}
 public static void Build(){
  var importer=(ModelImporter)AssetImporter.GetAtPath("Assets/Resources/PreviewActor.fbx");importer.isReadable=true;importer.importAnimation=false;importer.SaveAndReimport();
  var prefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Resources/PreviewActor.fbx");
  var actor=UnityEngine.Object.Instantiate(prefab);var animator=actor.GetComponent<Animator>();
  if(!animator||!animator.avatar||!animator.avatar.isHuman||!animator.avatar.isValid)throw new Exception("Invalid preview humanoid");
  var ts=actor.GetComponentsInChildren<Transform>(true);
  var model=new RigModel{humanoid=true,humanScale=animator.humanScale,muscles=HumanTrait.MuscleName,
   nodes=ts.Select(t=>new RigNode{name=t.name,parent=t==actor.transform?-1:Array.IndexOf(ts,t.parent),position=V(t.localPosition),rotation=new[]{t.localRotation.x,t.localRotation.y,t.localRotation.z,t.localRotation.w},scale=V(t.localScale)}).ToArray()};
  model.meshes=actor.GetComponentsInChildren<SkinnedMeshRenderer>(true).Where(r=>r.sharedMesh&&r.gameObject.activeInHierarchy).Select(r=>{
   var m=r.sharedMesh;var weights=m.boneWeights;
   int cursor=0;var groups=Enumerable.Range(0,m.subMeshCount).Select(i=>{var g=new RigGroup{start=cursor,count=m.GetTriangles(i).Length,material=i};cursor+=g.count;return g;}).ToArray();
   var morphs=Enumerable.Range(0,m.blendShapeCount).Where(i=>new[]{"A","I","U","E","O","eye_L_close","eye_R_close","eye_L_smile","eye_R_smile"}.Contains(m.GetBlendShapeName(i))).Select(i=>{var dp=new Vector3[m.vertexCount];var dn=new Vector3[m.vertexCount];var dt=new Vector3[m.vertexCount];int frame=m.GetBlendShapeFrameCount(i)-1;m.GetBlendShapeFrameVertices(i,frame,dp,dn,dt);float weight=m.GetBlendShapeFrameWeight(i,frame);return new RigMorph{name=m.GetBlendShapeName(i),positions=dp.SelectMany(v=>V(v*(weight==0?1:100f/weight))).ToArray()};}).ToArray();
   return new RigMesh{morphs=morphs,name=r.name,node=Array.IndexOf(ts,r.transform),positions=m.vertices.SelectMany(V).ToArray(),normals=m.normals.SelectMany(V).ToArray(),uv=m.uv.SelectMany(v=>new[]{v.x,v.y}).ToArray(),indices=m.triangles,groups=groups,materialNames=r.sharedMaterials.Select(mat=>mat?mat.name:"").ToArray(),
    weights=weights.SelectMany(w=>new[]{w.weight0,w.weight1,w.weight2,w.weight3}).ToArray(),joints=weights.SelectMany(w=>new[]{w.boneIndex0,w.boneIndex1,w.boneIndex2,w.boneIndex3}).ToArray(),
    bones=r.bones.Select(t=>Array.IndexOf(ts,t)).ToArray(),bindPoses=m.bindposes.SelectMany(b=>Enumerable.Range(0,16).Select(i=>b[i])).ToArray()};
  }).ToArray();
  string output=Path.GetFullPath("../worker");Directory.CreateDirectory(output);File.WriteAllText(Path.Combine(output,"model.json"),JsonUtility.ToJson(model));
  UnityEngine.Object.DestroyImmediate(actor);
  if(PoseWorker.Option("--model-only")=="1"){EditorApplication.Exit(0);return;}
  EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);new GameObject("Pose worker").AddComponent<PoseWorker>();EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene(),"Assets/Worker.unity");
  PlayerSettings.companyName="SCSPTools";PlayerSettings.productName="SCSPPoseWorker";PlayerSettings.runInBackground=true;PlayerSettings.SetScriptingBackend(BuildTargetGroup.Standalone,ScriptingImplementation.Mono2x);
  var result=BuildPipeline.BuildPlayer(new[]{"Assets/Worker.unity"},Path.Combine(output,"SCSPPoseWorker.exe"),BuildTarget.StandaloneWindows64,BuildOptions.None);
  if(result.summary.result!=BuildResult.Succeeded)throw new Exception("Worker build failed "+result.summary.result);
  Debug.Log("SCSP_POSE_BUILD_OK nodes="+model.nodes.Length+" meshes="+model.meshes.Length+" humanScale="+model.humanScale);EditorApplication.Exit(0);
 }
}
