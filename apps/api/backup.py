"""Sauvegarde, vérification et restauration des sources de fichiers.

Les contenus sont stockés compressés (gzip) dans un magasin adressé par
empreinte SHA-256 : un contenu identique n'est stocké qu'une seule fois,
quel que soit le nombre de sauvegardes ou de fichiers qui le référencent.
"""

import gzip
import hashlib
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db import BASE_DIR, database_connection, log_event

router = APIRouter(prefix="/backups", tags=["Sauvegardes"])
logger = logging.getLogger("recupba.backup")

CHUNK = 1024 * 1024


def store_dir() -> Path:
    path = Path(os.getenv("RECUPBA_BACKUP_DIR", BASE_DIR / "backups")).resolve()
    (path / "objects").mkdir(parents=True, exist_ok=True)
    (path / "tmp").mkdir(parents=True, exist_ok=True)
    return path


def object_path(sha256: str) -> Path:
    return store_dir() / "objects" / sha256[:2] / f"{sha256}.gz"


def store_file(path: Path) -> tuple[str, bool]:
    """Copie un fichier dans le magasin. Retourne (sha256, nouvel_objet)."""
    digest = hashlib.sha256()
    tmp_dir = store_dir() / "tmp"
    fd, tmp_name = tempfile.mkstemp(dir=tmp_dir, suffix=".gz")
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(CHUNK), b""):
                    digest.update(chunk)
                    out.write(chunk)
        sha = digest.hexdigest()
        target = object_path(sha)
        if target.exists():
            os.unlink(tmp_name)
            return sha, False
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_name, target)
        return sha, True
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def object_is_valid(sha256: str) -> bool:
    target = object_path(sha256)
    if not target.is_file():
        return False
    digest = hashlib.sha256()
    try:
        with gzip.open(target, "rb") as data:
            for chunk in iter(lambda: data.read(CHUNK), b""):
                digest.update(chunk)
    except (OSError, EOFError):
        return False
    return digest.hexdigest() == sha256


def iso(value):
    return value.isoformat() if value else None


def load_source_root(cursor, source_id: UUID) -> Path:
    cursor.execute(
        "SELECT configuration, enabled, source_type FROM sources WHERE id = %s",
        (source_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Source introuvable.")
    configuration, enabled, source_type = row
    if not enabled:
        raise HTTPException(status_code=409, detail="Cette source est désactivée.")
    if source_type != "filesystem":
        raise HTTPException(status_code=400, detail="Seules les sources filesystem peuvent être sauvegardées.")
    raw_path = configuration.get("path")
    try:
        root = Path(raw_path).resolve(strict=True)
    except (OSError, RuntimeError, TypeError):
        raise HTTPException(status_code=400, detail="Le chemin configuré est introuvable ou inaccessible.")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Le chemin configuré n'est pas un dossier.")
    return root


# --- Sauvegarde --------------------------------------------------------------

class BackupRequest(BaseModel):
    source_id: UUID


@router.post("/run")
def run_backup(request: BackupRequest):
    backup_id = uuid4()
    files, errors, bytes_total, bytes_new, objects_new = [], 0, 0, 0, 0

    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                root = load_source_root(cursor, request.source_id)
                configuration = cursor.execute(
                    "SELECT configuration FROM sources WHERE id = %s", (request.source_id,)
                ).fetchone()[0]
                if root == store_dir() or store_dir().is_relative_to(root):
                    raise HTTPException(
                        status_code=400,
                        detail="Le dossier de sauvegarde ne peut pas se trouver dans la source.",
                    )
            # Trace « en cours » visible immédiatement (transaction séparée).
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO backups (id, source_id, status) VALUES (%s, %s, 'running')",
                    (backup_id, request.source_id),
                )
            connection.commit()

            iterator = root.rglob("*") if configuration.get("recursive", True) else root.iterdir()
            for path in iterator:
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    resolved = path.resolve(strict=True)
                    if not resolved.is_relative_to(root):
                        errors += 1
                        continue
                    stat = resolved.stat()
                    sha, is_new = store_file(resolved)
                    bytes_total += stat.st_size
                    if is_new:
                        objects_new += 1
                        bytes_new += stat.st_size
                    files.append((
                        resolved.relative_to(root).as_posix(),
                        stat.st_size,
                        datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        sha,
                    ))
                except (OSError, ValueError):
                    logger.warning("Fichier non sauvegardé : %s", path)
                    errors += 1

            status = "completed" if errors == 0 else "completed_with_errors"
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO backup_files
                        (backup_id, relative_path, size_bytes, modified_at, sha256)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [(backup_id, *item) for item in files],
                )
                cursor.execute(
                    """
                    UPDATE backups
                    SET status = %s, files_count = %s, bytes_total = %s,
                        bytes_new = %s, objects_new = %s, errors_count = %s,
                        finished_at = clock_timestamp()
                    WHERE id = %s
                    """,
                    (status, len(files), bytes_total, bytes_new, objects_new, errors, backup_id),
                )
                log_event(cursor, "backup.completed", "backup", backup_id, {
                    "source_id": str(request.source_id),
                    "files_count": len(files),
                    "bytes_total": bytes_total,
                    "bytes_new": bytes_new,
                    "errors_count": errors,
                })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Échec de la sauvegarde %s", backup_id)
        mark_failed("backups", backup_id, "backup.failed", f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="La sauvegarde a échoué. Vérifiez les journaux du serveur.")

    return {
        "backup_id": str(backup_id),
        "status": status,
        "files_count": len(files),
        "bytes_total": bytes_total,
        "bytes_new": bytes_new,
        "objects_new": objects_new,
        "errors_count": errors,
    }


def mark_failed(table: str, row_id: UUID, event: str, message: str) -> None:
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'failed', finished_at = clock_timestamp(), error_message = %s
                    WHERE id = %s
                    """,
                    (message[:1000], row_id),
                )
                if cursor.rowcount:
                    log_event(cursor, event, table.rstrip("s"), row_id, {"error": message[:300]})
    except Exception:
        logger.exception("Impossible d'enregistrer l'échec %s", row_id)


# --- Consultation ------------------------------------------------------------

BACKUP_COLUMNS = """b.id, b.source_id, s.name, b.status, b.files_count, b.bytes_total,
    b.bytes_new, b.objects_new, b.errors_count, b.started_at, b.finished_at,
    b.verified_at, b.verification_status, b.error_message"""


def backup_from_row(row) -> dict:
    return {
        "backup_id": str(row[0]),
        "source_id": str(row[1]),
        "source_name": row[2],
        "status": row[3],
        "files_count": row[4],
        "bytes_total": row[5],
        "bytes_new": row[6],
        "objects_new": row[7],
        "errors_count": row[8],
        "started_at": iso(row[9]),
        "finished_at": iso(row[10]),
        "verified_at": iso(row[11]),
        "verification_status": row[12],
        "error_message": row[13],
    }


@router.get("")
def list_backups(source_id: UUID | None = None, limit: int = 50):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="La limite doit être comprise entre 1 et 200.")
    try:
        with database_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT {BACKUP_COLUMNS}
                FROM backups b JOIN sources s ON s.id = b.source_id
                WHERE %(source)s::uuid IS NULL OR b.source_id = %(source)s::uuid
                ORDER BY b.started_at DESC LIMIT %(limit)s
                """,
                {"source": source_id, "limit": limit},
            ).fetchall()
    except Exception:
        logger.exception("Échec de la lecture des sauvegardes")
        raise HTTPException(status_code=500, detail="Impossible de consulter les sauvegardes.")
    return [backup_from_row(row) for row in rows]


def fetch_backup(connection, backup_id: UUID) -> dict:
    row = connection.execute(
        f"SELECT {BACKUP_COLUMNS} FROM backups b JOIN sources s ON s.id = b.source_id WHERE b.id = %s",
        (backup_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sauvegarde introuvable.")
    return backup_from_row(row)


@router.get("/stats")
def backup_store_stats():
    try:
        with database_connection() as connection:
            count, logical = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(bytes_total), 0) FROM backups WHERE status LIKE 'completed%%'"
            ).fetchone()
    except Exception:
        logger.exception("Échec des statistiques de sauvegarde")
        raise HTTPException(status_code=500, detail="Statistiques indisponibles.")
    stored = sum(f.stat().st_size for f in (store_dir() / "objects").rglob("*.gz"))
    return {
        "backups_completed": count,
        "bytes_protected": logical,
        "bytes_stored": stored,
        "store_path": str(store_dir()),
    }


@router.get("/{backup_id}")
def backup_detail(backup_id: UUID):
    try:
        with database_connection() as connection:
            backup = fetch_backup(connection, backup_id)
            files = connection.execute(
                """
                SELECT relative_path, size_bytes, modified_at, sha256
                FROM backup_files WHERE backup_id = %s ORDER BY relative_path
                """,
                (backup_id,),
            ).fetchall()
            restores = connection.execute(
                """
                SELECT id, target_path, status, files_restored, errors_count,
                       started_at, finished_at, error_message
                FROM restores WHERE backup_id = %s ORDER BY started_at DESC
                """,
                (backup_id,),
            ).fetchall()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Échec de la lecture de la sauvegarde %s", backup_id)
        raise HTTPException(status_code=500, detail="Impossible de consulter la sauvegarde.")

    backup["files"] = [
        {"path": f[0], "size_bytes": f[1], "modified_at": iso(f[2]), "sha256": f[3].strip()}
        for f in files
    ]
    backup["restores"] = [
        {
            "restore_id": str(r[0]),
            "target_path": r[1],
            "status": r[2],
            "files_restored": r[3],
            "errors_count": r[4],
            "started_at": iso(r[5]),
            "finished_at": iso(r[6]),
            "error_message": r[7],
        }
        for r in restores
    ]
    return backup


@router.get("/{backup_id}/download")
def download_file(backup_id: UUID, path: str):
    """Télécharge un fichier tel qu'il était au moment de la sauvegarde."""
    try:
        with database_connection() as connection:
            row = connection.execute(
                "SELECT sha256 FROM backup_files WHERE backup_id = %s AND relative_path = %s",
                (backup_id, path),
            ).fetchone()
    except Exception:
        logger.exception("Échec de la lecture du fichier sauvegardé")
        raise HTTPException(status_code=500, detail="Impossible de lire le fichier sauvegardé.")
    if row is None:
        raise HTTPException(status_code=404, detail="Fichier absent de cette sauvegarde.")
    target = object_path(row[0].strip())
    if not target.is_file():
        raise HTTPException(status_code=410, detail="Le contenu sauvegardé est introuvable dans le magasin.")

    def stream():
        with gzip.open(target, "rb") as data:
            yield from iter(lambda: data.read(CHUNK), b"")

    filename = quote(path.rsplit("/", 1)[-1])
    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# --- Vérification ------------------------------------------------------------

@router.post("/{backup_id}/verify")
def verify_backup(backup_id: UUID):
    try:
        with database_connection() as connection:
            fetch_backup(connection, backup_id)
            rows = connection.execute(
                "SELECT relative_path, sha256 FROM backup_files WHERE backup_id = %s",
                (backup_id,),
            ).fetchall()
            checked: dict[str, bool] = {}
            invalid = []
            for relative_path, sha in rows:
                sha = sha.strip()
                if sha not in checked:
                    checked[sha] = object_is_valid(sha)
                if not checked[sha]:
                    invalid.append(relative_path)
            status = "ok" if not invalid else "corrupted"
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE backups SET verified_at = clock_timestamp(), verification_status = %s
                    WHERE id = %s
                    """,
                    (status, backup_id),
                )
                log_event(cursor, f"backup.verified_{status}", "backup", backup_id, {
                    "files_checked": len(rows),
                    "invalid_files": len(invalid),
                })
    except HTTPException:
        raise
    except Exception:
        logger.exception("Échec de la vérification de %s", backup_id)
        raise HTTPException(status_code=500, detail="La vérification a échoué.")

    return {
        "backup_id": str(backup_id),
        "verification_status": status,
        "files_checked": len(rows),
        "invalid_files": sorted(invalid),
    }


# --- Restauration ------------------------------------------------------------

class RestoreRequest(BaseModel):
    target_path: str = Field(min_length=3)
    paths: list[str] | None = Field(
        default=None,
        description="Fichiers à restaurer. Vide : toute la sauvegarde.",
    )
    overwrite: bool = Field(
        default=False,
        description="Remplacer les fichiers déjà présents dans le dossier cible.",
    )


def check_restore_target(target_raw: str, source_root: Path | None) -> Path:
    target = Path(target_raw)
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="Le dossier cible doit être un chemin absolu.")
    target = target.resolve()
    if target.exists() and not target.is_dir():
        raise HTTPException(status_code=400, detail="Le chemin cible existe et n'est pas un dossier.")
    store = store_dir()
    if target == store or target.is_relative_to(store) or store.is_relative_to(target):
        raise HTTPException(status_code=400, detail="Impossible de restaurer dans le dossier de sauvegarde.")
    if source_root and (target == source_root or target.is_relative_to(source_root)
                        or source_root.is_relative_to(target)):
        raise HTTPException(
            status_code=400,
            detail="Par sécurité, la restauration dans le dossier source est interdite. "
                   "Choisissez un autre dossier.",
        )
    return target


@router.post("/{backup_id}/restore")
def restore_backup(backup_id: UUID, request: RestoreRequest):
    restore_id = uuid4()
    restored, errors, skipped = 0, 0, []

    try:
        with database_connection() as connection:
            backup = fetch_backup(connection, backup_id)
            if not backup["status"].startswith("completed"):
                raise HTTPException(status_code=409, detail="Seule une sauvegarde terminée peut être restaurée.")
            configuration = connection.execute(
                "SELECT configuration FROM sources WHERE id = %s", (backup["source_id"],)
            ).fetchone()[0]
            source_path = configuration.get("path")
            source_root = Path(source_path).resolve() if source_path else None
            target = check_restore_target(request.target_path, source_root)

            rows = connection.execute(
                "SELECT relative_path, sha256, modified_at FROM backup_files WHERE backup_id = %s",
                (backup_id,),
            ).fetchall()
            if request.paths:
                wanted = set(request.paths)
                rows = [r for r in rows if r[0] in wanted]
                missing = wanted - {r[0] for r in rows}
                if missing:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{len(missing)} fichier(s) demandé(s) absent(s) de la sauvegarde.",
                    )
            if not rows:
                raise HTTPException(status_code=400, detail="Aucun fichier à restaurer.")

            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO restores (id, backup_id, target_path, status) VALUES (%s, %s, %s, 'running')",
                    (restore_id, backup_id, str(target)),
                )
            connection.commit()

            target.mkdir(parents=True, exist_ok=True)
            for relative_path, sha, modified_at in rows:
                destination = (target / relative_path).resolve()
                if not destination.is_relative_to(target):
                    errors += 1
                    continue
                if destination.exists() and not request.overwrite:
                    skipped.append(relative_path)
                    continue
                try:
                    restore_object(sha.strip(), destination, modified_at)
                    restored += 1
                except (OSError, ValueError, EOFError):
                    logger.warning("Fichier non restauré : %s", relative_path)
                    errors += 1

            errors += len(skipped)
            status = "completed" if errors == 0 else "completed_with_errors"
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE restores
                    SET status = %s, files_restored = %s, errors_count = %s,
                        finished_at = clock_timestamp(),
                        error_message = %s
                    WHERE id = %s
                    """,
                    (
                        status, restored, errors,
                        f"{len(skipped)} fichier(s) existant(s) non remplacé(s)." if skipped else None,
                        restore_id,
                    ),
                )
                log_event(cursor, "restore.completed", "restore", restore_id, {
                    "backup_id": str(backup_id),
                    "target_path": str(target),
                    "files_restored": restored,
                    "errors_count": errors,
                })
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Échec de la restauration %s", restore_id)
        mark_failed("restores", restore_id, "restore.failed", f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail="La restauration a échoué. Vérifiez les journaux du serveur.")

    return {
        "restore_id": str(restore_id),
        "backup_id": str(backup_id),
        "target_path": str(target),
        "status": status,
        "files_restored": restored,
        "files_skipped": sorted(skipped),
        "errors_count": errors,
    }


def restore_object(sha256: str, destination: Path, modified_at: datetime) -> None:
    """Décompresse un objet vers sa destination en vérifiant son empreinte."""
    source = object_path(sha256)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=destination.parent, prefix=".recupba-")
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out, gzip.open(source, "rb") as data:
            for chunk in iter(lambda: data.read(CHUNK), b""):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sha256:
            raise ValueError(f"Empreinte invalide pour {destination.name}")
        os.replace(tmp_name, destination)
        timestamp = modified_at.timestamp()
        os.utime(destination, (timestamp, timestamp))
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def purge_tmp() -> None:
    """Supprime les fichiers temporaires laissés par une sauvegarde interrompue."""
    shutil.rmtree(store_dir() / "tmp", ignore_errors=True)
    store_dir()
