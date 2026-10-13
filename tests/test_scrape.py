"""Download stage tested against a throw-away local HTTP server (no internet needed)."""
import csv
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from btli import config, scrape

BIG = "<html><body><article>" + "<p>" + "Real report content about risk and strategy. " * 40 + "</p></article></body></html>"
THIN = "<html><body><div id='root'></div><script>x=1</script></body></html>"
PDF = b"%PDF-1.4\n%fake but starts with the magic bytes\n"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        routes = {"/ok": ("text/html; charset=utf-8", BIG.encode()), "/thin": ("text/html", THIN.encode()),
                  "/pdf": ("application/pdf", PDF), "/nolabel": ("application/octet-stream", PDF)}
        if self.path in routes:
            ctype, body = routes[self.path]
            self.send_response(200); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_scrape_statuses(tmp_path, server):
    csv_path = tmp_path / "in.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Firm", "Title", "Url", " Publish_date", "Trend_category"])
        for name in ("ok", "thin", "pdf", "nolabel", "missing"):
            w.writerow(["EY", f"Paper {name}", f"{server}/{name}", "2026", "Cat"])
    s = config.Settings(csv_path=csv_path, workdir=tmp_path / "out", use_playwright=False, delay=(0, 0))
    rows = {r["title"]: r for r in scrape.run(s)}
    assert rows["Paper ok"]["status"] == "saved" and rows["Paper ok"]["kind"] == "html"
    assert rows["Paper thin"]["status"] == "thin"
    assert rows["Paper pdf"]["kind"] == "pdf" and rows["Paper pdf"]["path"].endswith(".pdf")
    assert rows["Paper nolabel"]["kind"] == "pdf"                 # detected by magic bytes
    assert rows["Paper missing"]["status"] == "failed"
    assert s.failed_csv.exists() and s.scrape_manifest.exists()
    # second run resumes from cache without re-downloading
    again = {r["title"]: r for r in scrape.run(s)}
    assert again["Paper ok"]["status"] == "cached"
