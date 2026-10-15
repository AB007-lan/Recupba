import os
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

DEMO_SOURCE_ID = "e791cc06-27c2-44c0-b096-b826d06d6ed7"
AUTO_SOURCE_NAME = "RECUPBA - Tests automatiques"
AUTO_DIR = Path(__file__).resolve().parent / "fixtures" / "inventory-auto"


@pytest.fixture(scope="session")
def client():
    return TestClient(main.app)


@pytest.fixture(scope="session", autouse=True)
def isolated_backup_store(tmp_path_factory):
    """Les tests n'écrivent jamais dans le vrai magasin de sauvegardes."""
    os.environ["RECUPBA_BACKUP_DIR"] = str(tmp_path_factory.mktemp("backup-store"))


@pytest.fixture(scope="session")
def database_available():
    try:
        with main.database_connection() as connection:
            connection.execute("SELECT 1")
        main.apply_migrations()
    except Exception:
        pytest.skip("Base PostgreSQL RECUPBA indisponible.")


@pytest.fixture(scope="session")
def auto_source_id(database_available):
    """Source dédiée aux tests, réutilisée d'une session à l'autre (jamais supprimée)."""
    AUTO_DIR.mkdir(parents=True, exist_ok=True)
    with main.database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM sources WHERE name = %s", (AUTO_SOURCE_NAME,))
            row = cursor.fetchone()
            if row:
                return str(row[0])
    response = TestClient(main.app).post(
        "/sources",
        json={
            "name": AUTO_SOURCE_NAME,
            "source_type": "filesystem",
            "configuration": {"path": str(AUTO_DIR), "recursive": True},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
