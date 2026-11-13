using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using AssetStudio;
using Newtonsoft.Json;

// Uses the bundled AssetStudio libraries, but selects the prefab's source file
// before resolving its GameObject. Dependency FBX roots are never export targets.
public class PrefabFbx {
 public class Request { public string[] inputs; public string prefab_input; public string name; public string output;
                       public string[] scoped_geometry_inputs; }
 // Mesh by name, remembering the owning SerializedFile so we can scope candidates
 // to the geometry bundles explicitly attached to this prefab.
 public class MeshHit { public Mesh mesh; public SerializedFile file; }
 static Dictionary<string, List<MeshHit>> BuildMeshIndex(AssetsManager manager) {
  var index = new Dictionary<string, List<MeshHit>>(StringComparer.OrdinalIgnoreCase);
  foreach (var file in manager.AssetsFileList) {
   foreach (var mesh in file.Objects.OfType<Mesh>()) {
    var key = mesh.m_Name ?? "";
    List<MeshHit> list;
    if (!index.TryGetValue(key, out list)) { list = new List<MeshHit>(); index[key] = list; }
    list.Add(new MeshHit { mesh = mesh, file = file });
   }
  }
  return index;
 }
 static string Norm(string p) { try { return Path.GetFullPath(p); } catch { return p; } }
 static void Inspect(GameObject go, HashSet<long> seen, List<string> unresolved, ref int renderers,
                     Dictionary<string, List<MeshHit>> meshIndex, HashSet<string> scopedFiles, List<string> rebound) {
  if(!seen.Add(go.m_PathID))return;
  Mesh mesh;
  if(go.m_SkinnedMeshRenderer!=null){
   renderers++;
   var ptr=go.m_SkinnedMeshRenderer.m_Mesh;
   bool isNull=ptr==null||(ptr.m_FileID==0&&ptr.m_PathID==0);
   if(isNull){
    // Only null references fall back to name-based lookup. Preference order:
    //  (1) meshes in the geometry bundles attached to THIS prefab (scopedFiles);
    //      unique in scope -> use; multiple in scope -> error.
    //  (2) otherwise, unique across the whole loaded pool -> use.
    //  (3) otherwise -> unresolved (unchanged behaviour).
    List<MeshHit> all;
    meshIndex.TryGetValue(go.m_Name??"", out all);
    if(all==null) all=new List<MeshHit>();
    List<MeshHit> scoped = scopedFiles.Count>0
        ? all.Where(h => h.file!=null && scopedFiles.Contains(Norm(h.file.originalPath))).ToList()
        : new List<MeshHit>();
    if(scoped.Count==1){
     go.m_SkinnedMeshRenderer.m_Mesh=MakePtr(ptr,scoped[0].mesh);
     rebound.Add(go.m_Name+":"+scoped[0].mesh.m_Name+"@"+Path.GetFileName(scoped[0].file.originalPath));
    } else if(scoped.Count>1){
     unresolved.Add(go.m_Name); // ambiguous within attached geometry
    } else if(all.Count==1){
     go.m_SkinnedMeshRenderer.m_Mesh=MakePtr(ptr,all[0].mesh);
     rebound.Add(go.m_Name+":"+all[0].mesh.m_Name);
    } else {
     unresolved.Add(go.m_Name);
    }
   } else if(!ptr.TryGet(out mesh)){ unresolved.Add(go.m_Name); }
  }
  else if(go.m_MeshRenderer!=null){renderers++;if(go.m_MeshFilter==null||!go.m_MeshFilter.m_Mesh.TryGet(out mesh))unresolved.Add(go.m_Name);}
  if(go.m_Transform==null)return;
  foreach(var p in go.m_Transform.m_Children){Transform child;GameObject obj;
   if(!p.TryGet(out child)||!child.m_GameObject.TryGet(out obj))throw new Exception("Unresolved prefab child transform");
   Inspect(obj,seen,unresolved,ref renderers,meshIndex,scopedFiles,rebound);
  }
 }
 static PPtr<Mesh> MakePtr(PPtr<Mesh> original, Mesh mesh) {
  var ptr = new PPtr<Mesh>();
  var owner = mesh.assetsFile;
  var holder = original != null ? original.AssetsFile : null;
  if (holder != null && owner != null && !ReferenceEquals(holder, owner)) {
   FileIdentifier found = null;
   foreach (var ext in holder.m_Externals) {
    if (string.Equals(ext.fileName, owner.fileName, StringComparison.OrdinalIgnoreCase)) { found = ext; break; }
   }
   if (found == null) {
    found = new FileIdentifier();
    found.fileName = owner.fileName;
    found.pathName = owner.originalPath;
    holder.m_Externals.Add(found);
   }
   ptr.AssetsFile = holder;
   ptr.m_FileID = holder.m_Externals.IndexOf(found) + 1;
   ptr.m_PathID = mesh.m_PathID;
  } else {
   ptr.AssetsFile = owner;
   ptr.m_FileID = 0;
   ptr.m_PathID = mesh.m_PathID;
  }
  return ptr;
 }
 public static int Main(string[] args){try{
  var request=JsonConvert.DeserializeObject<Request>(File.ReadAllText(args[0]));
  var manager=new AssetsManager();manager.OptionLoaders.Clear();manager.LoadFilesAndFolders(request.inputs);
  var source=Path.GetFullPath(request.prefab_input);
  var meshIndex=BuildMeshIndex(manager);
  var scopedFiles=new HashSet<string>();
  if(request.scoped_geometry_inputs!=null){foreach(var s in request.scoped_geometry_inputs)scopedFiles.Add(Norm(s));}
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
  int renderers=0;var unresolved=new List<string>();var rebound=new List<string>();
  Inspect(root,new HashSet<long>(),unresolved,ref renderers,meshIndex,scopedFiles,rebound);
  if(unresolved.Count>0)throw new Exception("Unresolved mesh references: "+String.Join(", ",unresolved));
  var convert=new ModelConverter(root,ImageFormat.Png,new List<AnimationClip>());
  if(renderers>0&&convert.MeshList.Count==0)throw new Exception("Mesh renderers exist but geometry could not be converted");
  Directory.CreateDirectory(request.output);
  var settings=new Fbx.Settings{ScaleFactor=1,ExportAnimations=false};
  if(convert.MeshList.Count>0)ModelExporter.ExportFbx(Path.Combine(request.output,root.m_Name+".fbx"),convert,settings);
  File.WriteAllText(Path.Combine(request.output,"geometry-report.json"),JsonConvert.SerializeObject(new{
   input=source,root=root.m_Name,path_id=root.m_PathID,meshes=convert.MeshList.Count,
   materials=convert.MaterialList.Count,textures=convert.TextureList.Count,animations=convert.AnimationList.Count,
   selection="source_prefab_root",geometry_checked=true,source_mesh_renderers=renderers,
   unresolved_mesh_references=unresolved,null_mesh_rebound=rebound,scoped_geometry_files=scopedFiles.Count
  },Formatting.Indented));
  manager.Clear();Console.WriteLine("SCSP_PREFAB_FBX_OK");return 0;
 }catch(Exception error){Console.Error.WriteLine(error);return 1;}}
}
