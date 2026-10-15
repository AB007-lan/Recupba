import gzip
import hashlib
from uuid import uuid4

import backup
from conftest import AUTO_DIR


def write_fixture_files():
    for old in AUTO_DIR.rglob("*"):
        if old.is_file():
            old.unlink()
    (AUTO_DIR / "sous-dossier").mkdir(parents=True, exist_ok=True)
    (AUTO_DIR / "a.txt").write_text("contenu A", encoding="utf-8")
    (AUTO_DIR / "copie-de-a.txt").write_text("contenu A", encoding="utf-8")
    (AUTO_DIR / "sous-dossier" / "b.bin").write_bytes(bytes(range(256)) * 50)


def test_store_file_deduplicates(tmp_path):
    first = tmp_path / "1.txt"
    second = tmp_path / "2.txt"
    first.write_text("identique", encoding="utf-8")
    second.write_text("identique", encoding="utf-8")
    sha1, new1 = backup.store_file(first)
    sha2, new2 = backup.store_file(second)
    assert sha1 == sha2 == hashlib.sha256(b"identique").hexdigest()
    assert (new1, new2) == (True, False)
    assert backup.object_is_valid(sha1)


def test_backup_unknown_source(client, database_available):
    response = client.post("/backups/run", json={"source_id": str(uuid4())})
    assert response.status_code == 404


def test_backup_verify_restore_cycle(client, auto_source_id, tmp_path):
    write_fixture_files()

    # 1. Sauvegarde : 3 fichiers, mais seulement 2 contenus distincts.
    first = client.post("/backups/run", json={"source_id": auto_source_id})
    assert first.status_code == 200, first.text
    first = first.json()
    assert first["status"] == "completed"
    assert first["files_count"] == 3

    # 2. Deuxième sauvegarde sans changement : rien de nouveau à stocker.
    second = client.post("/backups/run", json={"source_id": auto_source_id}).json()
    assert second["bytes_new"] == 0 and second["objects_new"] == 0

    detail = client.get(f"/backups/{first['backup_id']}").json()
    assert sorted(f["path"] for f in detail["files"]) == [
        "a.txt", "copie-de-a.txt", "sous-dossier/b.bin",
    ]
    listing = client.get(f"/backups?source_id={auto_source_id}&limit=2").json()
    assert listing[0]["backup_id"] == second["backup_id"]

    # 3. Vérification d'intégrité.
    verify = client.post(f"/backups/{first['backup_id']}/verify").json()
    assert verify["verification_status"] == "ok"
    assert verify["files_checked"] == 3

    # 4. Le fichier source change : la sauvegarde garde l'ancienne version.
    (AUTO_DIR / "a.txt").write_text("contenu A modifié", encoding="utf-8")
    download = client.get(f"/backups/{first['backup_id']}/download", params={"path": "a.txt"})
    assert download.status_code == 200
    assert download.content == "contenu A".encode("utf-8")

    # 5. Restauration complète dans un dossier vide.
    target = tmp_path / "restauration"
    restore = client.post(f"/backups/{first['backup_id']}/restore",
                          json={"target_path": str(target)}).json()
    assert restore["status"] == "completed"
    assert restore["files_restored"] == 3
    assert (target / "a.txt").read_text(encoding="utf-8") == "contenu A"
    assert (target / "sous-dossier" / "b.bin").read_bytes() == bytes(range(256)) * 50

    # 6. Sans « overwrite », les fichiers existants ne sont jamais écrasés.
    (target / "a.txt").write_text("ne pas écraser", encoding="utf-8")
    again = client.post(f"/backups/{first['backup_id']}/restore",
                        json={"target_path": str(target), "paths": ["a.txt"]}).json()
    assert again["files_restored"] == 0 and again["files_skipped"] == ["a.txt"]
    assert (target / "a.txt").read_text(encoding="utf-8") == "ne pas écraser"

    overwrite = client.post(f"/backups/{first['backup_id']}/restore",
                            json={"target_path": str(target), "paths": ["a.txt"], "overwrite": True}).json()
    assert overwrite["files_restored"] == 1
    assert (target / "a.txt").read_text(encoding="utf-8") == "contenu A"

    history = client.get(f"/backups/{first['backup_id']}").json()["restores"]
    assert len(history) == 3

    # 7. Corruption détectée par la vérification.
    sha_a = hashlib.sha256("contenu A".encode("utf-8")).hexdigest()
    stored = backup.object_path(sha_a)
    original = stored.read_bytes()
    try:
        stored.write_bytes(gzip.compress(b"altere"))
        broken = client.post(f"/backups/{first['backup_id']}/verify").json()
        assert broken["verification_status"] == "corrupted"
        assert broken["invalid_files"] == ["a.txt", "copie-de-a.txt"]
    finally:
        stored.write_bytes(original)
    assert client.post(f"/backups/{first['backup_id']}/verify").json()["verification_status"] == "ok"


def test_restore_safety_rules(client, auto_source_id, tmp_path):
    write_fixture_files()
    backup_id = client.post("/backups/run", json={"source_id": auto_source_id}).json()["backup_id"]
    url = f"/backups/{backup_id}/restore"

    # Jamais dans la source elle-même.
    assert client.post(url, json={"target_path": str(AUTO_DIR)}).status_code == 400
    assert client.post(url, json={"target_path": str(AUTO_DIR / "sous-dossier")}).status_code == 400
    # Chemin relatif refusé.
    assert client.post(url, json={"target_path": "relatif/dossier"}).status_code == 400
    # Fichier inconnu dans la sauvegarde.
    response = client.post(url, json={"target_path": str(tmp_path / "x"), "paths": ["inexistant.txt"]})
    assert response.status_code == 400
    # Sauvegarde inconnue.
    assert client.post(f"/backups/{uuid4()}/restore",
                       json={"target_path": str(tmp_path / "y")}).status_code == 404
    assert client.get(f"/backups/{backup_id}/download", params={"path": "inexistant"}).status_code == 404


def test_backup_audit_and_stats(client, auto_source_id):
    write_fixture_files()
    backup_id = client.post("/backups/run", json={"source_id": auto_source_id}).json()["backup_id"]
    events = client.get("/audit?limit=20").json()
    assert any(e["event_type"] == "backup.completed" and e["entity_id"] == backup_id for e in events)
    stats = client.get("/backups/stats").json()
    assert stats["backups_completed"] >= 1
    assert stats["bytes_stored"] > 0
