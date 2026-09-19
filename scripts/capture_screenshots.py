import os
import subprocess
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

def run():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_dir = os.path.join(repo_root, "ui", "dist")
    out_dir = os.path.join(repo_root, "docs", "images")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(os.path.join(dist_dir, "index.html")):
        print("dist/index.html not found, building first...")
        subprocess.run(["npm", "run", "build", "--prefix", "ui"], cwd=repo_root, check=True)

    port = 5515
    handler = partial(SimpleHTTPRequestHandler, directory=dist_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"Temporary preview server started on http://127.0.0.1:{port}")
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

    targets = [
        ("account-center.png", f"http://127.0.0.1:{port}/?demo=1&page=accounts&clean=1"),
        ("sessions.png", f"http://127.0.0.1:{port}/?demo=1&page=sessions&clean=1"),
        ("migration.png", f"http://127.0.0.1:{port}/?demo=1&page=migrate&from=domestic&to=international&plan=1&clean=1"),
        ("token-usage.png", f"http://127.0.0.1:{port}/?demo=1&page=tokens&range=7d&clean=1"),
    ]

    try:
        for filename, url in targets:
            out_path = os.path.join(out_dir, filename)
            cmd = [
                edge_exe,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--virtual-time-budget=2000",
                "--window-size=1280,820",
                f"--screenshot={out_path}",
                url,
            ]
            print(f"Capturing {filename} from {url}...")
            subprocess.run(cmd, check=True)
            time.sleep(1.0)
    finally:
        print("Shutting down preview server...")
        server.shutdown()

    print("\nScreenshots generated successfully in docs/images/:")
    for f in os.listdir(out_dir):
        fp = os.path.join(out_dir, f)
        print(f" - {f} ({os.path.getsize(fp)} bytes)")

if __name__ == "__main__":
    run()
