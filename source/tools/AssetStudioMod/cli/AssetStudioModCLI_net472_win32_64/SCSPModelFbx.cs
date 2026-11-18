using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using AssetStudio;
using Newtonsoft.Json;

// Uses the bundled AssetStudio libraries, but selects the prefab's source file
// before resolving its GameObject. Dependency FBX roots are never export targets.
public class PrefabFbx {
 public class Request {
  public string[] inputs;
  public string prefab_input, name, output, carrier_input, carrier_name;
  public bool carrier_already_selected;
  public string[] scoped_geometry_inputs;
 }
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
 static void Inspect(GameObject go, HashSet<long> seen, List<string> unresolved, List<string> empty, ref int renderers, Dictionary<string,List<MeshHit>> meshIndex,
                     HashSet<string> scopedFiles, List<string> rebound) {
  if(!seen.Add(go.m_PathID))return;
  Mesh mesh;
  if(go.m_SkinnedMeshRenderer!=null){
   var ptr=go.m_SkinnedMeshRenderer.m_Mesh;
   if(ptr==null||(ptr.m_FileID==0&&ptr.m_PathID==0)){
    if(meshIndex==null)empty.Add(go.m_Name);
    else{
     renderers++;
     List<MeshHit> all;
     if(!meshIndex.TryGetValue(go.m_Name??"",out all))all=new List<MeshHit>();
     var scoped=all.Where(hit=>hit.file!=null&&scopedFiles.Contains(Norm(hit.file.originalPath))).ToList();
     var candidates=scoped.Count>0?scoped:all;
     if(candidates.Count!=1)unresolved.Add(go.m_Name);
     else{
      var hit=candidates[0];
      go.m_SkinnedMeshRenderer.m_Mesh=MakePtr(ptr,hit.mesh);
      rebound.Add(go.m_Name+":"+hit.mesh.m_Name+"@"+Path.GetFileName(hit.file.originalPath));
     }
    }
   }else{renderers++;if(!ptr.TryGet(out mesh))unresolved.Add(go.m_Name);}
  }else if(go.m_MeshRenderer!=null){
   if(go.m_MeshFilter==null)unresolved.Add(go.m_Name+" (missing MeshFilter)");
   else if(go.m_MeshFilter.m_Mesh.m_FileID==0&&go.m_MeshFilter.m_Mesh.m_PathID==0)empty.Add(go.m_Name);
   else {renderers++;if(!go.m_MeshFilter.m_Mesh.TryGet(out mesh))unresolved.Add(go.m_Name);}
  }
  if(go.m_Transform==null)return;
  foreach(var p in go.m_Transform.m_Children){Transform child;GameObject obj;
   if(!p.TryGet(out child)||!child.m_GameObject.TryGet(out obj))throw new Exception("Unresolved prefab child transform");
   Inspect(obj,seen,unresolved,empty,ref renderers,meshIndex,scopedFiles,rebound);
  }
 }
 static GameObject FindRoot(AssetsManager manager, string source, string name) {
  var roots=new List<GameObject>();
  foreach(var file in manager.AssetsFileList){
   if(!String.Equals(Path.GetFullPath(file.originalPath),source,StringComparison.OrdinalIgnoreCase))continue;
   foreach(var go in file.Objects.OfType<GameObject>()){
    if(!String.Equals(go.m_Name,name,StringComparison.OrdinalIgnoreCase)||go.m_Transform==null)continue;
    Transform father;if(!go.m_Transform.m_Father.TryGet(out father))roots.Add(go);
   }
  }
  if(roots.Count!=1)throw new Exception("Selected prefab root is missing or ambiguous: "+roots.Count);
  return roots[0];
 }

 static IEnumerable<GameObject> Descendants(GameObject root) {
  yield return root;
  if(root.m_Transform==null)yield break;
  foreach(var pointer in root.m_Transform.m_Children) {
   Transform child;
   GameObject node;
   if(!pointer.TryGet(out child)||!child.m_GameObject.TryGet(out node))
    throw new Exception("Unresolved prefab child transform");
   foreach(var descendant in Descendants(node))yield return descendant;
  }
 }

 static string NodePath(GameObject node) {
  Transform parent;
  GameObject parentNode;
  if(node.m_Transform.m_Father.TryGet(out parent)&&parent.m_GameObject.TryGet(out parentNode))
   return NodePath(parentNode)+"/"+node.m_Name;
  return node.m_Name;
 }

 static bool SameMaterials(Renderer source, Renderer candidate) {
  if(source.m_Materials.Count==0||source.m_Materials.Count!=candidate.m_Materials.Count)return false;
  for(int i=0;i<source.m_Materials.Count;i++) {
   Material a,b;
   if(!source.m_Materials[i].TryGet(out a)||!candidate.m_Materials[i].TryGet(out b)||!object.ReferenceEquals(a,b))
    return false;
  }
  return true;
 }

 static ModelConverter ConvertCarrier(GameObject source, GameObject carrier, List<string> empty, List<string> paths) {
  var sourceNodes=Descendants(source).Where(node=>node.m_SkinnedMeshRenderer!=null).ToList();
  if(sourceNodes.Count!=empty.Count||sourceNodes.Count==0)
   throw new Exception("Carrier export requires exclusively empty skinned mesh renderers");
  var candidates=Descendants(carrier).Where(node=>node.m_SkinnedMeshRenderer!=null).ToList();
  foreach(var node in sourceNodes) {
   var matches=candidates.Where(candidate=>candidate.m_Name==node.m_Name
    &&SameMaterials(node.m_SkinnedMeshRenderer,candidate.m_SkinnedMeshRenderer)).ToList();
   Mesh mesh;
   if(matches.Count!=1||!matches[0].m_SkinnedMeshRenderer.m_Mesh.TryGet(out mesh))
    throw new Exception("Missing or ambiguous accessory geometry on associated hair: "+node.m_Name);
   paths.Add(NodePath(matches[0]));
  }
  var converter=new ModelConverter(carrier,ImageFormat.Png,new List<AnimationClip>());
  converter.MeshList.RemoveAll(mesh=>!paths.Contains(mesh.Path));
  converter.MorphList.RemoveAll(morph=>!paths.Contains(morph.Path));
  if(paths.Distinct().Count()!=paths.Count||converter.MeshList.Count!=paths.Count)
   throw new Exception("Associated hair geometry could not be converted");
  var materials=new HashSet<string>(converter.MeshList.SelectMany(mesh=>mesh.SubmeshList).Select(submesh=>submesh.Material));
  converter.MaterialList.RemoveAll(material=>!materials.Contains(material.Name));
  var textures=new HashSet<string>(converter.MaterialList.Where(material=>material.Textures!=null)
   .SelectMany(material=>material.Textures).Select(texture=>texture.Name));
  converter.TextureList.RemoveAll(texture=>!textures.Contains(texture.Name));
  return converter;
 }

 public static int Main(string[] args){try{
  var request=JsonConvert.DeserializeObject<Request>(File.ReadAllText(args[0]));
  var manager=new AssetsManager();manager.OptionLoaders.Clear();manager.LoadFilesAndFolders(request.inputs);
  var source=Path.GetFullPath(request.prefab_input);
  var root=FindRoot(manager,source,request.name);
  int renderers=0;var unresolved=new List<string>();var empty=new List<string>();
  var scopedFiles=new HashSet<string>((request.scoped_geometry_inputs??new string[0]).Select(Norm),
   StringComparer.OrdinalIgnoreCase);
  // Keep scoped rebinding for older manifests and the existing head/hair flow.
  // A verified accessory carrier uses its own renderer and binding instead.
  bool canRebind=String.IsNullOrEmpty(request.carrier_input)
   &&(scopedFiles.Count>0||request.name.StartsWith("m_head_",StringComparison.OrdinalIgnoreCase)
    ||request.name.StartsWith("m_hair_",StringComparison.OrdinalIgnoreCase));
  var rebound=new List<string>();
  Inspect(root,new HashSet<long>(),unresolved,empty,ref renderers,
   canRebind?BuildMeshIndex(manager):null,scopedFiles,rebound);
  if(unresolved.Count>0)throw new Exception("Unresolved mesh references: "+String.Join(", ",unresolved));
  var carrierNodes=new List<string>();
  bool carrierReused=false;
  ModelConverter convert;
  if(renderers==0&&empty.Count>0&&!String.IsNullOrEmpty(request.carrier_input)) {
   var carrier=FindRoot(manager,Path.GetFullPath(request.carrier_input),request.carrier_name);
   convert=ConvertCarrier(root,carrier,empty,carrierNodes);
   carrierReused=request.carrier_already_selected;
  }else{
   convert=new ModelConverter(root,ImageFormat.Png,new List<AnimationClip>());
  }
  if(renderers>0&&convert.MeshList.Count==0)throw new Exception("Mesh renderers exist but geometry could not be converted");
  Directory.CreateDirectory(request.output);
  var settings=new Fbx.Settings{ScaleFactor=1,ExportAnimations=false};
  if(convert.MeshList.Count>0&&!carrierReused)ModelExporter.ExportFbx(Path.Combine(request.output,root.m_Name+".fbx"),convert,settings);
  File.WriteAllText(Path.Combine(request.output,"geometry-report.json"),JsonConvert.SerializeObject(new{
   input=source,root=root.m_Name,path_id=root.m_PathID,meshes=convert.MeshList.Count,
   materials=convert.MaterialList.Count,textures=convert.TextureList.Count,animations=convert.AnimationList.Count,
   selection="source_prefab_root",geometry_checked=true,source_mesh_renderers=renderers,unresolved_mesh_references=unresolved,skipped_empty_mesh_renderers=empty,
   carrier_nodes=carrierNodes,carrier_reused=carrierReused,
   null_mesh_rebound=rebound,scoped_geometry_files=scopedFiles.Count
  },Formatting.Indented));
  manager.Clear();Console.WriteLine("SCSP_PREFAB_FBX_OK");return 0;
 }catch(Exception error){Console.Error.WriteLine(error);return 1;}}
}
