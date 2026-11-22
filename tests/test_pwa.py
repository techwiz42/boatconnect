"""The installable app: its manifest and icons are right, the server hands out the worker and manifest properly, and the worker never touches the API."""
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from boatconnect import server

PUBLIC = Path(__file__).resolve().parent.parent / "web" / "public"


def test_the_manifest_names_the_app_and_every_icon_exists_at_its_size():
    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text())
    assert manifest["name"] == "boatconnect" and manifest["display"] == "standalone" and manifest["start_url"] == "/" and manifest["scope"] == "/"
    sizes = {(i["sizes"], i["purpose"]) for i in manifest["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes and ("512x512", "maskable") in sizes      # what Chrome needs to offer installing
    for icon in manifest["icons"]:
        image = Image.open(PUBLIC / icon["src"].lstrip("/"))
        assert f"{image.width}x{image.height}" == icon["sizes"]
    assert Image.open(PUBLIC / "apple-touch-icon.png").size == (180, 180)


def test_the_worker_never_handles_the_api():
    worker = (PUBLIC / "sw.js").read_text()
    assert 'url.pathname.startsWith("/api/")) return' in worker                  # the first thing it does with a request is let API calls go by untouched
    assert "request.method !== \"GET\"" in worker


def test_the_server_serves_the_worker_and_manifest_so_a_deploy_shows_at_once(store, tmp_path, monkeypatch):
    for name in ("index.html", "sw.js", "manifest.webmanifest"):
        (tmp_path / name).write_bytes((PUBLIC / name).read_bytes() if name != "index.html" else b"<!doctype html><title>x</title>")
    monkeypatch.setattr(server, "WEB_DIST", tmp_path)
    client = TestClient(server.create_app(store=store))
    worker = client.get("/sw.js")
    assert worker.status_code == 200 and "javascript" in worker.headers["content-type"] and worker.headers["cache-control"] == "no-cache"
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and "manifest+json" in manifest.headers["content-type"] and manifest.headers["cache-control"] == "no-cache"
    assert "default-src 'self'" in worker.headers["content-security-policy"]       # a worker and a manifest from the site's own address are allowed by it
