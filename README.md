# SCSP 资源下载器

简体中文 | [English](README.en.md)

面向《アイドルマスター シャイニーカラーズ Song for Prism》的资源格式研究与整理工具，提供浏览器界面，支持资源检索、预览、按需获取与格式转换。

## 使用与版权声明

本项目是非官方、独立的技术研究项目，与游戏运营方及相关权利人没有隶属、合作或授权关系。游戏名称、角色、模型、贴图、音乐、语音等内容的著作权及其他权利均归各自权利人所有。

工具及源码用于格式研究、兼容性测试与个人学习；提供技术功能不代表授予任何游戏内容的使用许可。请仅在具备合法访问和使用权限的范围内使用，并遵守适用法律及相关服务条款。请勿利用本项目绕过访问权限，或未经授权传播、出售游戏内容、制作侵权产品。

开源许可仅覆盖本项目有权许可的代码，不覆盖游戏内容、第三方程序或其商标。上述声明不替代必要的授权，也不免除使用者或维护者依法应承担的责任。如权利人对本项目有异议，请通过 Issue 联系维护者，提供相关权利证明及具体内容，我们会核实并及时处理。

## 功能

- 模型：按编号文件夹导出 FBX 和贴图。 套装与发型自动包含主表声明的附带头饰，饰品支持独立头饰分类。
- 图片：原始分辨率预览、透明背景检查、缩放与 PNG 保存。
- 动作：导出独立 `.anim`；支持 Humanoid 身体动作与剧情口型预览，符合精确骨骼映射的通用动作可附加转换。
- 场景：可选 Unity 工程或每场景一个 FBX，附带可导出的贴图。
- 音频：试听、音轨选择、WAV 导出及剧情 Cue 角色索引。
- 任务：自动重试、断点继续、仅重新导出、分阶段进度及手动清理。提交下载成功后自动清空本次待下载清单；提交失败保留选择。

导出不代表完整还原游戏。原游戏 Shader、脚本、物理和动态演出需要另外适配；依赖缺项会保留在报告中。Unity 场景工程的版本兼容性以导出内容为准，不能保证直接在 Unity 2022.3 播放。

## 使用

Windows x64：从本仓库 **Releases** 下载 `SCSPDownloader-win64.zip`，解压后运行 `SCSPDownloader.exe`，浏览器打开 `http://127.0.0.1:8765/`。保留完整目录，无需安装 Python。关闭终端即可停止服务。

下载与缓存默认位于程序旁的 `web-downloads` 和 `.scsp-cache`，不依赖开发者电脑路径。下载文件实际保存在本机；“保存 ZIP”用于另存一份。模型 FBX 导出工具需要 .NET Framework 4.7.2 或兼容版本。

歌曲配套默认完整保留。默认不在 ZIP 中重复附带全部原始包，成功后清理新生成的中间工程和临时输入；原始缓存、成品及旧任务历史保留，也可选择附带原始包。输入已清理的完成任务需要重新提交选择来再次导出，可复用缓存；失败任务仍可继续。

更新下载器时，先停止旧程序，将新版完整解压到新目录，确认可启动后再迁移需要保留的 `web-downloads` 和 `.scsp-cache`；不要只替换 EXE。已有较新资源目录可在新版中重新执行资源更新。

## 更新游戏资源

1. 从游戏或插件日志取得完整版本行
2. 在没有活动下载时运行 `Update-Resources.cmd`，分别输入 Game Version 和完整 Resource Version，**保留 `@` 后全部字符，包括 `/`、`+`、`=`**。
3. 等待校验与发布完成，再刷新网页；服务没有运行时，在更新后启动即可。

更新会重新生成资源索引、歌曲名称、角色与默认编队、换装分类及套装关联，失败保留旧目录。包内索引只是随包版本，不代表自动获知官方实时最新版；新版本改变数据结构时仍可能需要更新下载器。

源码版也可执行：(仅作示例)

```powershell
cd source
.\Update-Resources.ps1 -GameVersion '2.19.0' -ResourceVersion '<完整资源版本>'
```

## 源码运行与打包

`source/` 放源码；`release/` 放本地发行产物，已被 Git 忽略。将 ZIP 上传到 GitHub Releases，不要提交到 Git 历史。缓存、游戏资源、任务历史、虚拟环境和本地索引也不提交。

需要 Python 3.13 和 Windows x64。在仓库根目录执行：

```powershell
# 先解压同版本发行版到 release/SCSPDownloader；也可以传入 ZIP 路径。
py -3.13 source/prepare_runtime.py --release release/SCSPDownloader
cd source
.\setup.ps1
.\Start-Web.ps1

# 检查与重新打包
& .\.venv\Scripts\python.exe -m unittest -v
.\Build-Release.ps1
```

首次准备只复制发行版中的运行工具和元数据，不复制下载内容、不全量下载游戏。`prepare_runtime.py` 也支持 `--release ../release/SCSPDownloader-win64.zip`。重新打包前先移走已有的 `release/SCSPDownloader`，脚本不会覆盖其中的用户数据。打包输出到 `release/SCSPDownloader` 及 `release/SCSPDownloader-win64.zip`。

Python/Web 源码、场景 FBX 辅助程序的 C# 源码、动作预览 Worker 的 C# 和 Unity 工程配置均在 `source/`。第三方工具及预编译 Worker 从发行版复用；自行重建 Worker 需要 Unity 和适配的 Humanoid 预览模型，使用 `build_motion_worker.py --unity <Unity.exe>`。模型与贴图不包含在 Git 源码中。

## 更新日志

### v0.1.3 · 2026-10-29

- 新增身体动作与根位移合并导出。
- 修复根动作配对遗漏及合并后的位移异常、滑步。
- 修复模型同名 FBX 导出冲突。
- 修复清理临时文件后无法重新打包的问题。

合并动作需启用 **Apply Root Motion**，不要叠加外层走位；旧文件需重新导入 Unity。

### v0.1.2 · 2026-10-27

- 新增图片预览与 PNG 保存。
- 优化歌曲下载体积，保留所需配套数据。
- 改进剧情口型预览及部分动作的 Humanoid 转换。
- 修复贴图重名、口型误识别和部分音轨遗漏。

### v0.1.1 · 2026-10-25

- 修复套装、发型的头饰遗漏，新增头饰分类。

### v0.1.0 · 2026-10-24

- 首次发布资源浏览、导出、预览与任务管理功能。

## 参考与依赖

感谢以下项目。参考协议和数据格式不表示这些项目为本工具提供支持。

| 项目 | 用途 |
| --- | --- |
| [LukeFZ/PrismCatalogDownloader](https://github.com/LukeFZ/PrismCatalogDownloader) | 资源目录及格式研究参考 |
| [chinosk6/scsp-localify](https://github.com/chinosk6/scsp-localify) | 游戏版本信息、文本及数据结构研究参考 |
| [1498zl-coder/SCSPGameData](https://github.com/1498zl-coder/SCSPGameData) | 公开资源快照及版本入口参考 |
| [songforprism-acb-finder](https://github.com/asd123fdssal/songforprism-acb-finder) | CRI 音频资源研究参考 |
| [aelurum/AssetStudioMod](https://github.com/aelurum/AssetStudioMod) | 模型、场景 FBX 和贴图导出 |
| [AssetRipper](https://github.com/AssetRipper/AssetRipper) | Unity 场景工程恢复 |
| [vgmstream](https://github.com/vgmstream/vgmstream) | 音轨解码及 WAV 转换 |
| [UnityPy](https://github.com/K0lb3/UnityPy) | Unity 资源解析 |
| [three.js](https://github.com/mrdoob/three.js) | Web 3D 预览 |

本项目源码采用 GPL-3.0，见 `LICENSE`。第三方组件遵循各自许可，随工具保留原始许可；游戏资源的权利归原权利人，源码许可不覆盖游戏资源。AssetStudioMod 使用现有 0.19.0.0 发行文件，其精确源提交未记录；不宣称第三方二进制全部可从本仓库复现。

项目为vibe coding产物，欢迎提交 **Issue** 和 **Pull Request**。Issue 请附下载器版本、游戏及资源版本、资源名称、复现步骤和错误日志，勿附账号凭据；PR 请说明改动与验证方式，并运行相关测试。资源版本参数、分类和映射应尽量采用可复用规则。
