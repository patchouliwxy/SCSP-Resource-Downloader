"""Build the local prefab FBX helper against the prepared AssetStudio runtime."""
import os
from pathlib import Path
import subprocess


def build_model_helper():
    tool = Path(__file__).resolve().parent / (
        "tools/AssetStudioMod/cli/AssetStudioModCLI_net472_win32_64"
    )
    compiler = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    libraries = ("AssetStudio.dll", "AssetStudioUtility.dll", "AssetStudioFBXWrapper.dll", "Newtonsoft.Json.dll")
    missing = [path for path in (compiler, *(tool / name for name in libraries)) if not path.is_file()]
    if missing:
        raise SystemExit("Model helper build prerequisites missing: " + ", ".join(map(str, missing)))
    temporary = tool / "SCSPModelFbx.new.exe"
    subprocess.run(
        [str(compiler), "/nologo", "/target:exe", f"/out:{temporary.name}",
         *(f"/r:{name}" for name in libraries), "SCSPModelFbx.cs"],
        cwd=tool, check=True,
    )
    temporary.replace(tool / "SCSPModelFbx.exe")


if __name__ == "__main__":
    build_model_helper()
