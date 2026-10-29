# SCSP Resource Downloader

[简体中文](README.md) | English

A browser-based tool for researching and organizing resource formats used by *THE IDOLM@STER SHINY COLORS Song for Prism*. It supports resource search, previews, on-demand retrieval, and format conversion.

## Usage and Copyright Notice

This is an unofficial, independent research project. It is not affiliated with, endorsed by, or authorized by the game's operator or other rights holders. All rights to game names, characters, models, textures, music, voices, and other game content belong to their respective owners.

The tool and its source code are intended for format research, compatibility testing, and personal learning. Providing a technical capability does not grant permission to use game content. Use it only where you have lawful access and the necessary permissions, and comply with applicable laws and relevant terms of service. Do not use this project to bypass access restrictions, distribute or sell game content without authorization, or create infringing products.

The open-source license covers only code that this project is entitled to license. It does not cover game content, third-party programs, or their trademarks. This notice does not replace required permissions or waive any legal responsibilities of users or maintainers. Rights holders with concerns may contact the maintainers through an Issue, identifying the relevant content and providing supporting information. We will review and address substantiated concerns promptly.

## Features

- **Models:** export FBX files and textures into folders organized by asset number. Outfits and hairstyles include their explicitly linked headwear, also available as a separate accessory category.
- **Images:** original-resolution previews, transparency inspection, zoom, and PNG saving.
- **Motions:** standalone `.anim` exports, Humanoid body-motion and story mouth previews, plus optional conversion for generic motions with exact skeleton bindings.
- **Scenes:** export a Unity project or one FBX per scene, with available textures.
- **Audio:** previews, track selection, WAV conversion, and character indexing for story audio Cues.
- **Tasks:** automatic retries, resume, export-only retries, progress by phase, and manual cleanup. Successfully submitting a task clears the submitted selection; failed submissions keep it.

Exports do not reconstruct the complete game. Original shaders, scripts, physics, and dynamic performances require additional adaptation. Missing dependencies remain in the reports. Unity compatibility depends on the exported content; direct playback in Unity 2022.3 is not guaranteed.

## Getting Started

On Windows x64, download `SCSPDownloader-win64.zip` from this repository's **Releases**, extract it, and run `SCSPDownloader.exe`. Open `http://127.0.0.1:8765/` in your browser. Keep the entire extracted folder together. Python is not required. Close the terminal to stop the server.

Downloads and cache files are stored beside the application in `web-downloads` and `.scsp-cache` by default. Paths are not tied to the developer's computer. Files are saved locally; **Save ZIP** saves an additional copy. The model FBX exporter requires .NET Framework 4.7.2 or a compatible version.

All song companions are kept by default. The ZIP does not include a duplicate copy of every original bundle unless requested. Newly generated intermediate projects and temporary inputs are cleaned up after success; the original cache, delivered files, and old task history remain. Completed tasks whose inputs were cleaned up must be submitted again to export again, reusing the cache where possible. Failed tasks can still be resumed.

To update the downloader, stop the old application and extract the complete new release into a new directory. After verifying it starts, migrate `web-downloads` and `.scsp-cache` if needed. Do not replace only the EXE. If you used a newer resource catalog, run the resource update again in the new release.

## Updating Game Resources

1. Obtain the complete version line from the game or plugin log
2. With no active downloads, run `Update-Resources.cmd`. Enter the Game Version and the complete Resource Version separately. **Keep every character after `@`, including `/`, `+`, and `=`.**
3. Wait for validation and publication to finish, then refresh the page. If the server is not running, start it after the update.

The update rebuilds the resource index, song names, character and default lineup mappings, wardrobe categories, and outfit set associations. If it fails, the previous catalog is retained. The bundled index represents its packaged version; it does not automatically establish the latest official version. Changes to the game's data structures may require an updated downloader.

## Running and Building from Source

`source/` contains the source code. `release/` contains local distribution files and is ignored by Git. Upload the ZIP to GitHub Releases rather than committing it to Git history. Do not commit caches, game assets, task history, virtual environments, or local indexes.

Python 3.13 and Windows x64 are required. From the repository root:

```powershell
# Extract the matching release into release/SCSPDownloader first.
# A release ZIP can also be supplied instead.
py -3.13 source/prepare_runtime.py --release release/SCSPDownloader
cd source
.\setup.ps1
.\Start-Web.ps1

# Run checks and build a release.
& .\.venv\Scripts\python.exe -m unittest -v
.\Build-Release.ps1
```

Runtime preparation copies only tools and metadata from the release. It does not copy downloads or fetch the entire game's resources. From `source/`, `prepare_runtime.py` also accepts `--release ../release/SCSPDownloader-win64.zip`. Move any existing `release/SCSPDownloader` folder aside before rebuilding: the build script refuses to overwrite it and its user data. Output is written to `release/SCSPDownloader` and `release/SCSPDownloader-win64.zip`.

`source/` includes the Python and Web code, the scene FBX helper's C# source, and the motion preview Worker's C# source and Unity project configuration. Third-party tools and the precompiled Worker are reused from the release. Rebuilding the Worker requires Unity and a compatible Humanoid preview model; use `build_motion_worker.py --unity <Unity.exe>`. Models and textures are not included in the Git source tree.

## Changelog

### v0.1.3 · 2026-10-29

- Add combined body and root-motion exports.
- Fix missed root-motion matches, incorrect displacement, and sliding after merging.
- Fix same-name FBX export conflicts.
- Fix repackaging after temporary files are cleaned up.

Enable **Apply Root Motion** for merged clips without additional parent movement. Reimport older clips into Unity.

### v0.1.2 · 2026-10-27

- Add image previews and PNG saving.
- Reduce song download size while keeping required companion data.
- Improve story mouth previews and Humanoid conversion for supported clips.
- Fix texture name conflicts, incorrect mouth detection, and missing audio tracks.

### v0.1.1 · 2026-10-25

- Fix missing headwear in outfits and hairstyles; add a headwear category.

### v0.1.0 · 2026-10-24

- Initial release with resource browsing, exports, previews, and task management.

## References and Dependencies

Thanks to the following projects. Referencing their protocols and formats does not imply their endorsement or support of this tool.

| Project | Purpose |
| --- | --- |
| [LukeFZ/PrismCatalogDownloader](https://github.com/LukeFZ/PrismCatalogDownloader) | Resource catalog and format research reference |
| [chinosk6/scsp-localify](https://github.com/chinosk6/scsp-localify) | Game version information, text, and data structure research reference |
| [1498zl-coder/SCSPGameData](https://github.com/1498zl-coder/SCSPGameData) | Public resource snapshots and version entry reference |
| [songforprism-acb-finder](https://github.com/asd123fdssal/songforprism-acb-finder) | CRI audio resource research reference |
| [aelurum/AssetStudioMod](https://github.com/aelurum/AssetStudioMod) | Model, scene FBX, and texture export |
| [AssetRipper](https://github.com/AssetRipper/AssetRipper) | Unity scene project recovery |
| [vgmstream](https://github.com/vgmstream/vgmstream) | Audio track decoding and WAV conversion |
| [UnityPy](https://github.com/K0lb3/UnityPy) | Unity asset parsing |
| [three.js](https://github.com/mrdoob/three.js) | Web 3D previews |

This project's source code is licensed under GPL-3.0; see `LICENSE`. Third-party components retain their own licenses, included with the tools. Game content remains the property of its rights holders and is not covered by the source code license. The bundled AssetStudioMod files identify as version 0.19.0.0; their exact source commit was not recorded. We do not claim that every third-party binary can be reproduced from this repository.

This project was built through vibe coding. **Issues** and **Pull Requests** are welcome. For an Issue, include the downloader version, game and resource versions, resource name, reproduction steps, and error logs. Do not include account credentials. For a PR, explain the change and how it was verified, and run the relevant tests. Prefer reusable rules for version parameters, classification, and mappings.
