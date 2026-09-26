"""Zero-dependency demo server.
Run: python standalone_demo.py
Then open http://127.0.0.1:8000
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json, sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app.pipeline.engine import run_pipeline

class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, code, body, content_type="text/html; charset=utf-8"):
        if isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_bytes(200, (ROOT/"static"/"index.html").read_bytes()); return
        if self.path == "/health":
            self.send_bytes(200, b'{"status":"ok"}', "application/json"); return
        if self.path == "/api/sample":
            self.send_bytes(200, json.dumps({"requirements": sample_text()}).encode(), "application/json"); return
        self.send_bytes(404, b"Not found", "text/plain")
    def do_POST(self):
        if self.path != "/api/analyze": self.send_bytes(404,b"Not found","text/plain"); return
        try:
            n=int(self.headers.get("Content-Length",0)); data=json.loads(self.rfile.read(n)); text=data.get("requirements","")
            if not text.strip(): raise ValueError("Requirements cannot be empty")
            result=run_pipeline(text).to_dict()
            self.send_bytes(200,json.dumps(result).encode(),"application/json")
        except Exception as e:
            self.send_bytes(400,json.dumps({"detail":str(e)}).encode(),"application/json")

def sample_text():
    return """Users shall be able to register and log in securely.\nUsers shall browse products and search the catalog.\nUsers shall create orders and pay online.\nThe system shall send an email notification when an order is placed.\nThe system shall support high availability and audit important actions."""

if __name__ == "__main__":
    print("Req2Arch demo: http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1",8000),Handler).serve_forever()
