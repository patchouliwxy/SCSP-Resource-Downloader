using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using AssetStudio;
using Newtonsoft.Json;

// Reuses the exact bundled AssetStudioMod assemblies; no Unity Editor needed.
public class SceneFbx
{
    public class Request { public string[] inputs; public string scene_input; public string name; public string output; }
    public static int Main(string[] args)
    {
        try { return Run(args); }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
    static int Run(string[] args)
    {
        var request = JsonConvert.DeserializeObject<Request>(File.ReadAllText(args[0]));
        var manager = new AssetsManager();
        manager.OptionLoaders.Clear();
        manager.LoadFilesAndFolders(request.inputs);
        var source = Path.GetFullPath(request.scene_input);
        var roots = new List<GameObject>();
        var files = new List<object>();
        int sourceRenderers = 0;
        var unresolvedMeshes = new List<string>();
        foreach (var file in manager.AssetsFileList)
        {
            bool selected = String.Equals(Path.GetFullPath(file.originalPath), source, StringComparison.OrdinalIgnoreCase);
            files.Add(new { path = file.originalPath, selected = selected, objects = file.Objects.Count });
            if (!selected) continue;
            foreach (var go in file.Objects.OfType<GameObject>())
            {
                if (go.m_MeshRenderer != null || go.m_SkinnedMeshRenderer != null)
                {
                    sourceRenderers++;
                    Mesh mesh;
                    bool resolved = go.m_SkinnedMeshRenderer != null
                        ? go.m_SkinnedMeshRenderer.m_Mesh.TryGet(out mesh)
                        : go.m_MeshFilter != null && go.m_MeshFilter.m_Mesh.TryGet(out mesh);
                    if (!resolved) unresolvedMeshes.Add(go.m_Name);
                }
                if (go.m_Transform == null) continue;
                Transform father;
                if (!go.m_Transform.m_Father.TryGet(out father)) roots.Add(go);
            }
        }
        Directory.CreateDirectory(request.output);
        File.WriteAllText(Path.Combine(request.output, "load-report.json"), JsonConvert.SerializeObject(new { files = files, roots = roots.Select(g => g.m_Name).ToArray() }, Formatting.Indented));
        if (roots.Count == 0) throw new Exception("Selected scene has no resolvable root transforms");
        var convert = new ModelConverter(request.name, roots, ImageFormat.Png, new List<AnimationClip>());
        if (convert.MeshList.Count == 0) throw new Exception("Selected scene contains no exportable mesh geometry");
        var settings = new Fbx.Settings { ScaleFactor = 1, ExportAnimations = false };
        ModelExporter.ExportFbx(Path.Combine(request.output, request.name + ".fbx"), convert, settings);
        File.WriteAllText(Path.Combine(request.output, "geometry-report.json"), JsonConvert.SerializeObject(new {
            meshes = convert.MeshList.Count, materials = convert.MaterialList.Count,
            textures = convert.TextureList.Count, roots = roots.Select(g => g.m_Name).ToArray(),
            animations = convert.AnimationList.Count, input = source,
            source_mesh_renderers = sourceRenderers,
            mesh_count_matches_renderers = sourceRenderers == convert.MeshList.Count,
            unresolved_mesh_references = unresolvedMeshes
        }, Formatting.Indented));
        Console.WriteLine("SCSP_SCENE_FBX_OK");
        manager.Clear();
        return 0;
    }
}
