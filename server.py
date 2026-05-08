#!/usr/bin/env python3
"""HTTP server that runs histogram.py on the latest log and serves the result."""

import glob
import html
import os
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8088
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def find_latest_log():
    logs = sorted(glob.glob(os.path.join(BASE_DIR, "log_*.txt")))
    return logs[-1] if logs else None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/img/"):
            self._serve_image()
        else:
            self._serve_report()

    def _serve_report(self):
        log = find_latest_log()
        if not log:
            self._send(404, "text/plain", b"No log files found.")
            return

        png = log.rsplit(".", 1)[0] + ".png"
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "histogram.py"), log,
             "--out", png],
            capture_output=True, text=True,
        )
        output = (result.stdout or "") + (result.stderr or "")

        img_tag = ""
        if os.path.exists(png):
            img_name = os.path.basename(png)
            img_tag = f'<img src="/img/{img_name}" style="max-width:100%">'

        page = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>pingwatch</title>
<style>
  body {{ font-family: monospace; font-size: 16px; margin: 2em; background: #fff; color: #000; }}
  pre  {{ background: #f4f4f4; padding: 1em; overflow-x: auto; }}
  img  {{ margin-top: 1em; }}
</style>
</head><body>
<h2>{html.escape(os.path.basename(log))}</h2>
<pre>{html.escape(output)}</pre>
{img_tag}
</body></html>"""
        self._send(200, "text/html", page.encode())

    def _serve_image(self):
        name = os.path.basename(self.path)
        path = os.path.join(BASE_DIR, name)
        if not os.path.exists(path):
            self._send(404, "text/plain", b"Not found")
            return
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, "image/png", data)

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving on http://0.0.0.0:{port}")
    server.serve_forever()
