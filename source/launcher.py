import sys,webbrowser,json
from runtime_paths import app_root
def main():
    command=sys.argv[1] if len(sys.argv)>1 else ''
    if command=='--check':
        import UnityPy,numpy,PIL,cryptography,lz4
        root=app_root()
        index=json.loads((root/'official-current-index.json').read_text(encoding='utf-8'))
        tools=['tools/AssetStudioMod/cli/AssetStudioModCLI_net472_win32_64/AssetStudioModCLI.exe','tools/AssetRipper/2.0.0/AssetRipper.GUI.Free.exe','tools/vgmstream/r2117/vgmstream-cli.exe']
        assert all((root/p).is_file() for p in tools)
        print(json.dumps(dict(root=str(root),game_version=index['game_version'],resource_version=index['resource_version'],tools_ok=True,unitypy=UnityPy.__version__),ensure_ascii=False));return 0
    if command=='--update':
        sys.argv.pop(1)
        import scsp_update
        return scsp_update.main()
    if command=='--cli':
        sys.argv.pop(1)
        import scsp_download
        return scsp_download.main()
    open_browser = '--no-browser' not in sys.argv
    if not open_browser:
        sys.argv.remove('--no-browser')
    import scsp_web
    return scsp_web.main(on_ready=webbrowser.open if open_browser else None)
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:
        print('Startup failed:',e,file=sys.stderr);raise
