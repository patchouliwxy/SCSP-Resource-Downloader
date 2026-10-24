import sys,threading,time,webbrowser,json
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
    if '--no-browser' in sys.argv:sys.argv.remove('--no-browser')
    else:
        port=sys.argv[sys.argv.index('--port')+1] if '--port' in sys.argv else '8765'
        def open_browser():
            import urllib.request
            for _ in range(90):
                try:
                    urllib.request.urlopen('http://127.0.0.1:'+port+'/api/meta',timeout=1).close();webbrowser.open('http://127.0.0.1:'+port+'/');return
                except OSError:time.sleep(1)
        threading.Thread(target=open_browser,daemon=True).start()
    import scsp_web
    scsp_web.main()
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:
        print('Startup failed:',e,file=sys.stderr);raise
