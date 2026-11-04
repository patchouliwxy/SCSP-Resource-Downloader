using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using AssetStudio;
using Newtonsoft.Json;

// Uses the bundled AssetStudio libraries, but selects the prefab's source file
// before resolving its GameObject. Dependency FBX roots are never export targets.
public class PrefabFbx {
 public class Request { public string[] inputs; public string prefab_input; public string name; public string output; }
 static void Inspect(GameObject go, HashSet<long> seen, List<string> unresolved, ref int renderers) {
  if(!seen.Add(go.m_PathID))return;
  Mesh mesh;
  if(go.m_SkinnedMeshRenderer!=null){renderers++;if(!go.m_SkinnedMeshRenderer.m_Mesh.TryGet(out mesh))unresolved.Add(go.m_Name);}
  else if(go.m_MeshRenderer!=null){renderers++;if(go.m_MeshFilter==null||!go.m_MeshFilter.m_Mesh.TryGet(out mesh))unresolved.Add(go.m_Name);}
  if(go.m_Transform==null)return;
  foreach(var p in go.m_Transform.m_Children){Transform child;GameObject obj;
   if(!p.TryGet(out child)||!child.m_GameObject.TryGet(out obj))throw new Exception("Unresolved prefab child transform");
   Inspect(obj,seen,unresolved,ref renderers);
  }
 }
 public static int Main(string[] args){try{
  var request=JsonConvert.DeserializeObject<Request>(File.ReadAllText(args[0]));
  var manager=new AssetsManager();manager.OptionLoaders.Clear();manager.LoadFilesAndFolders(request.inputs);
  var source=Path.GetFullPath(request.prefab_input);
  var roots=new List<GameObject>();
  foreach(var file in manager.AssetsFileList){
   if(!String.Equals(Path.GetFullPath(file.originalPath),source,StringComparison.OrdinalIgnoreCase))continue;
   foreach(var go in file.Objects.OfType<GameObject>()){
    if(!String.Equals(go.m_Name,request.name,StringComparison.OrdinalIgnoreCase)||go.m_Transform==null)continue;
    Transform father;if(!go.m_Transform.m_Father.TryGet(out father))roots.Add(go);
   }
  }
  if(roots.Count!=1)throw new Exception("Selected prefab root is missing or ambiguous: "+roots.Count);
  var root=roots[0];
  int renderers=0;var unresolved=new List<string>();
  Inspect(root,new HashSet<long>(),unresolved,ref renderers);
  if(unresolved.Count>0)throw new Exception("Unresolved mesh references: "+String.Join(", ",unresolved));
  var convert=new ModelConverter(root,ImageFormat.Png,new List<AnimationClip>());
  if(renderers>0&&convert.MeshList.Count==0)throw new Exception("Mesh renderers exist but geometry could not be converted");
  Directory.CreateDirectory(request.output);
  var settings=new Fbx.Settings{ScaleFactor=1,ExportAnimations=false};
  if(convert.MeshList.Count>0)ModelExporter.ExportFbx(Path.Combine(request.output,root.m_Name+".fbx"),convert,settings);
  File.WriteAllText(Path.Combine(request.output,"geometry-report.json"),JsonConvert.SerializeObject(new{
   input=source,root=root.m_Name,path_id=root.m_PathID,meshes=convert.MeshList.Count,
   materials=convert.MaterialList.Count,textures=convert.TextureList.Count,animations=convert.AnimationList.Count,
   selection="source_prefab_root",geometry_checked=true,source_mesh_renderers=renderers,unresolved_mesh_references=unresolved
  },Formatting.Indented));
  manager.Clear();Console.WriteLine("SCSP_PREFAB_FBX_OK");return 0;
 }catch(Exception error){Console.Error.WriteLine(error);return 1;}}
}
