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
  var convert=new ModelConverter(root,ImageFormat.Png,new List<AnimationClip>());
  if(convert.MeshList.Count==0)throw new Exception("Selected prefab has no exportable meshes");
  Directory.CreateDirectory(request.output);
  var settings=new Fbx.Settings{ScaleFactor=1,ExportAnimations=false};
  ModelExporter.ExportFbx(Path.Combine(request.output,root.m_Name+".fbx"),convert,settings);
  File.WriteAllText(Path.Combine(request.output,"geometry-report.json"),JsonConvert.SerializeObject(new{
   input=source,root=root.m_Name,path_id=root.m_PathID,meshes=convert.MeshList.Count,
   materials=convert.MaterialList.Count,textures=convert.TextureList.Count,animations=convert.AnimationList.Count,
   selection="source_prefab_root"
  },Formatting.Indented));
  manager.Clear();Console.WriteLine("SCSP_PREFAB_FBX_OK");return 0;
 }catch(Exception error){Console.Error.WriteLine(error);return 1;}}
}
