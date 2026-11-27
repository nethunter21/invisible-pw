"""GeoLens desktop entry point.

Starts the local backend and opens the UI in a native window (pywebview / Edge WebView2
on Windows). Falls back to the default browser if no native web view is available.

    GeoLens.exe                 native window
    GeoLens.exe --browser       open in the default browser instead
    GeoLens.exe --no-vision     skip the neural model (metadata, OCR, reverse search only)
"""
from __future__ import annotations

import argparse
import os
import sys
import time


def main() -> None:
    ap = argparse.ArgumentParser(prog="GeoLens")
    ap.add_argument("--browser", action="store_true", help="open the UI in the default browser")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--no-preload", action="store_true")
    args = ap.parse_args()

    from .server import data_dir, serve
    if sys.stdout is None or sys.stderr is None:  # windowed .exe: give tqdm/HF somewhere to write
        f = open(os.path.join(data_dir(), "geolens.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    httpd = serve(args.port, use_vision=not args.no_vision)
    from . import server
    if not args.no_preload:
        server.STATE.preload()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"GeoLens running at {url}  (data: {data_dir()})", flush=True)

    if not args.browser:
        try:
            import webview  # pywebview
            try:
                webview.settings["ALLOW_DOWNLOADS"] = True
            except Exception:
                pass
            webview.create_window("GeoLens — GEOINT Image Analyser", url, width=1480, height=920,
                                  min_size=(1000, 680), background_color="#0b0d12")
            webview.start()
            return
        except Exception as e:  # pragma: no cover
            print(f"Native window unavailable ({e}); opening browser.", file=sys.stderr)
    import webbrowser
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
