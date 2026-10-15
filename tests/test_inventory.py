import hashlib
from datetime import datetime
from uuid import uuid4

import pytest

import inventory
from conftest import AUTO_DIR, DEMO_SOURCE_ID


# --- Tests unitaires (sans base) ---------------------------------------------

def test_sha256_file(tmp_path):
    file = tmp_path / "a.txt"
    file.write_bytes(b"recupba")
    assert inventory.sha256_file(file) == hashlib.sha256(b"recupba").hexdigest()


def test_routes_published(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/",
        "/health",
        "/sources",
        "/inventory/run",
        "/inventory/compare/{source_id}",
        "/inventory/history/{source_id}",
    ):
        assert path in paths


@pytest.mark.parametrize("url", [
    "/inventory/history/pas-un-uuid",
    "/inventory/compare/pas-un-uuid",
])
def test_invalid_uuid_rejected(client, url):
    assert client.get(url).status_code == 422


def test_run_invalid_uuid_rejected(client):
    assert client.post("/inventory/run", json={"source_id": "x"}).status_code == 422


@pytest.mark.parametrize("limit", [0, 101])
def test_history_limit_out_of_range(client, limit):
    response = client.get(f"/inventory/history/{DEMO_SOURCE_ID}?limit={limit}")
    assert response.status_code == 400


# --- Tests d'intégration (base PostgreSQL requise, lecture seule) -------------

def test_history_demo_source(client, database_available):
    response = client.get(f"/inventory/history/{DEMO_SOURCE_ID}?limit=2")
    assert response.status_code == 200
    body = response.json()
    assert body["source_id"] == DEMO_SOURCE_ID
    assert body["count"] == len(body["runs"]) <= 2
    starts = [run["started_at"] for run in body["runs"]]
    assert starts == sorted(starts, reverse=True)


def test_history_unknown_source_is_empty(client, database_available):
    body = client.get(f"/inventory/history/{uuid4()}").json()
    assert body["count"] == 0 and body["runs"] == []


def test_run_unknown_source(client, database_available):
    response = client.post("/inventory/run", json={"source_id": str(uuid4())})
    assert response.status_code == 404


def test_compare_unknown_source(client, database_available):
    assert client.get(f"/inventory/compare/{uuid4()}").status_code == 404


# --- Scénario complet sur la source dédiée aux tests -------------------------

def test_full_inventory_cycle(client, auto_source_id):
    for old in AUTO_DIR.rglob("*"):
        if old.is_file():
            old.unlink()
    (AUTO_DIR / "stable.txt").write_text("stable", encoding="utf-8")
    (AUTO_DIR / "modifie.txt").write_text("v1", encoding="utf-8")
    (AUTO_DIR / "supprime.txt").write_text("bientôt supprimé", encoding="utf-8")

    first = client.post("/inventory/run", json={"source_id": auto_source_id})
    assert first.status_code == 200, first.text
    assert first.json()["files_scanned"] == 3

    (AUTO_DIR / "modifie.txt").write_text("v2", encoding="utf-8")
    (AUTO_DIR / "supprime.txt").unlink()
    (AUTO_DIR / "nouveau.txt").write_text("nouveau", encoding="utf-8")

    second = client.post("/inventory/run", json={"source_id": auto_source_id})
    assert second.status_code == 200, second.text

    comparison = client.get(f"/inventory/compare/{auto_source_id}").json()
    assert comparison["latest_run_id"] == second.json()["run_id"]
    assert comparison["new_files"] == ["nouveau.txt"]
    assert [f["path"] for f in comparison["modified_files"]] == ["modifie.txt"]
    assert comparison["deleted_files"] == ["supprime.txt"]
    assert comparison["unchanged_files"] == ["stable.txt"]

    history = client.get(f"/inventory/history/{auto_source_id}?limit=1").json()
    run = history["runs"][0]
    assert run["run_id"] == second.json()["run_id"]
    started = datetime.fromisoformat(run["started_at"])
    finished = datetime.fromisoformat(run["finished_at"])
    assert finished > started  # clock_timestamp() : fin réelle, pas début de transaction
