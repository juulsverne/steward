"""Client-route fallback must never shadow the API and must be absent without a build."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_api_auth import ORIGIN, SIGNING, TOKEN


@pytest.fixture
def config(tmp_path):
    from agent.config import ApiSettings

    return ApiSettings(store_path=tmp_path / "demo.sqlite3", origin=ORIGIN, local_http=True,
                       session_secret=SIGNING, service_token=TOKEN, frontend_dist=None)


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Steward</title><div id=root></div>", encoding="utf-8")
    (root / "assets" / "app-abc123.js").write_text("console.log('steward')", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    return root


def test_without_dist_root_and_deep_paths_stay_json_404(config):
    from agent.api import create_app

    with TestClient(create_app(config), base_url=ORIGIN) as client:
        for path in ("/", "/issues/x"):
            response = client.get(path)
            assert response.status_code == 404
            assert response.json()["reason_code"] == "RESOURCE_NOT_FOUND"


def test_with_dist_client_routes_return_index_and_api_stays_json(config, dist):
    from agent.api import create_app

    with TestClient(create_app(replace(config, frontend_dist=dist)), base_url=ORIGIN) as client:
        for path in ("/", "/issues/demo-couch", "/inbox", "/crew/jobs/j1", "/report"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["content-type"].startswith("text/html")
            assert "id=root" in response.text
        assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg")
        asset = client.get("/assets/app-abc123.js")
        assert asset.status_code == 200 and "steward" in asset.text
        unknown_api = client.get("/api/unknown")
        assert unknown_api.status_code == 404 and unknown_api.json()["reason_code"] == "RESOURCE_NOT_FOUND"
        assert client.get("/health").json()["data"] == {"ok": True}
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/..%2Fpyproject.toml").status_code in {200, 404}
        assert "hatchling" not in client.get("/..%2Fpyproject.toml").text
