import os
import subprocess
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(repo_root, "ui", "dist")
    out_dir = os.path.join(repo_root, "docs", "responsive_audit")
    os.makedirs(out_dir, exist_ok=True)

    port = 5522
    handler = partial(SimpleHTTPRequestHandler, directory=dist_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_exe = next((p for p in edge_paths if os.path.exists(p)), None)
    if not edge_exe:
        print("Microsoft Edge not found.")
        server.shutdown()
        return

    pages = [
        ("accounts", f"http://127.0.0.1:{port}/?demo=1&page=accounts&clean=1"),
        ("sessions", f"http://127.0.0.1:{port}/?demo=1&page=sessions&clean=1"),
        ("migrate", f"http://127.0.0.1:{port}/?demo=1&page=migrate&from=domestic&to=international&plan=1&clean=1"),
        ("tokens", f"http://127.0.0.1:{port}/?demo=1&page=tokens&range=7d&clean=1"),
        ("about", f"http://127.0.0.1:{port}/?demo=1&page=about&clean=1"),
    ]

    widths = [1280, 1100, 980, 750, 600]

    try:
        for page_name, url in pages:
            for w in widths:
                out_path = os.path.join(out_dir, f"{page_name}_{w}px.png")
                cmd = [
                    edge_exe,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--virtual-time-budget=2000",
                    f"--window-size={w},820",
                    f"--screenshot={out_path}",
                    url,
                ]
                subprocess.run(cmd, check=True)
                print(f"Captured {page_name} @ {w}px -> {out_path}")
    finally:
        server.shutdown()

    print("\nAll responsive screenshots captured.")

if __name__ == "__main__":
    main()
