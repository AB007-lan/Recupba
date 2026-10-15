import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from psycopg.types.json import Jsonb

from db import database_connection, log_event

router = APIRouter(prefix="/inventory", tags=["Inventaire"])

logger = logging.getLogger("recupba.inventory")


def record_failed_run(run_id: UUID, source_id: UUID, message: str) -> None:
    """Trace une exécution échouée dans une transaction séparée."""
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO inventory_runs
                        (id, source_id, status, started_at, finished_at,
                         error_message)
                    VALUES (%s, %s, 'failed', clock_timestamp(),
                            clock_timestamp(), %s)
                    """,
                    (run_id, source_id, message[:1000]),
                )
                log_event(cursor, "inventory.failed", "inventory_run", run_id,
                          {"source_id": str(source_id), "error": message[:300]})
    except Exception:
        logger.exception("Impossible d'enregistrer l'échec de l'inventaire %s", run_id)


class InventoryRequest(BaseModel):
    source_id: UUID


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.post("/run")
def run_inventory(request: InventoryRequest):
    run_id = uuid4()
    files_found = []
    errors = 0

    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT configuration, enabled, source_type
                    FROM sources
                    WHERE id = %s
                    """,
                    (request.source_id,),
                )
                source = cursor.fetchone()

                if source is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Source introuvable.",
                    )

                configuration, enabled, source_type = source

                if not enabled:
                    raise HTTPException(
                        status_code=409,
                        detail="Cette source est désactivée.",
                    )

                if source_type != "filesystem":
                    raise HTTPException(
                        status_code=400,
                        detail="Cette source n'est pas de type filesystem.",
                    )

                raw_path = configuration.get("path")
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise HTTPException(
                        status_code=400,
                        detail="Le chemin de la source est absent.",
                    )

                try:
                    root = Path(raw_path).resolve(strict=True)
                except (OSError, RuntimeError):
                    raise HTTPException(
                        status_code=400,
                        detail="Le chemin configuré est introuvable ou inaccessible.",
                    )

                if not root.is_dir():
                    raise HTTPException(
                        status_code=400,
                        detail="Le chemin configuré n'est pas un dossier.",
                    )

                cursor.execute(
                    """
                    INSERT INTO inventory_runs (id, source_id, status, started_at)
                    VALUES (%s, %s, 'running', clock_timestamp())
                    """,
                    (run_id, request.source_id),
                )

                recursive = configuration.get("recursive", True)
                iterator = root.rglob("*") if recursive else root.iterdir()

                for path in iterator:
                    try:
                        if path.is_symlink() or not path.is_file():
                            continue

                        resolved = path.resolve(strict=True)
                        if not resolved.is_relative_to(root):
                            errors += 1
                            continue

                        stat = resolved.stat()
                        digest = sha256_file(resolved)

                        files_found.append({
                            "id": uuid4(),
                            "relative_path": resolved.relative_to(root).as_posix(),
                            "size_bytes": stat.st_size,
                            "modified_at": datetime.fromtimestamp(
                                stat.st_mtime, tz=timezone.utc
                            ),
                            "sha256": digest,
                        })
                    except (OSError, ValueError):
                        logger.warning("Fichier ignoré lors de l'inventaire : %s", path)
                        errors += 1

                for item in files_found:
                    cursor.execute(
                        """
                        INSERT INTO inventory_files
                            (id, run_id, relative_path, size_bytes,
                             modified_at, sha256)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            item["id"],
                            run_id,
                            item["relative_path"],
                            item["size_bytes"],
                            item["modified_at"],
                            item["sha256"],
                        ),
                    )

                cursor.execute(
                    """
                    UPDATE inventory_runs
                    SET status = %s,
                        files_scanned = %s,
                        errors_count = %s,
                        finished_at = clock_timestamp()
                    WHERE id = %s
                    """,
                    (
                        "completed" if errors == 0 else "completed_with_errors",
                        len(files_found),
                        errors,
                        run_id,
                    ),
                )
                log_event(cursor, "inventory.completed", "inventory_run", run_id, {
                    "source_id": str(request.source_id),
                    "files_scanned": len(files_found),
                    "errors_count": errors,
                })

        return {
            "run_id": str(run_id),
            "status": "completed" if errors == 0 else "completed_with_errors",
            "files_scanned": len(files_found),
            "errors_count": errors,
            "files": [
                {
                    "path": item["relative_path"],
                    "size_bytes": item["size_bytes"],
                    "sha256": item["sha256"],
                }
                for item in files_found
            ],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Échec de l'inventaire %s", run_id)
        record_failed_run(run_id, request.source_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="L'inventaire a échoué. Vérifiez les journaux du serveur.",
        )

@router.get("/compare/{source_id}")
def compare_inventory(source_id: UUID):
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, status, files_scanned, errors_count, finished_at
                    FROM inventory_runs
                    WHERE source_id = %s
                      AND status IN ('completed', 'completed_with_errors')
                    ORDER BY finished_at DESC NULLS LAST, started_at DESC
                    LIMIT 2
                    """,
                    (source_id,),
                )
                runs = cursor.fetchall()

                if not runs:
                    raise HTTPException(
                        status_code=404,
                        detail="Aucun inventaire terminé pour cette source.",
                    )

                if len(runs) < 2:
                    raise HTTPException(
                        status_code=409,
                        detail="Il faut au moins deux inventaires terminés pour comparer.",
                    )

                latest_run, previous_run = runs[0], runs[1]

                cursor.execute(
                    """
                    SELECT relative_path, size_bytes, sha256
                    FROM inventory_files WHERE run_id = %s
                    """,
                    (latest_run[0],),
                )
                latest = {
                    row[0]: {"size": row[1], "sha256": row[2].strip()}
                    for row in cursor.fetchall()
                }

                cursor.execute(
                    """
                    SELECT relative_path, size_bytes, sha256
                    FROM inventory_files WHERE run_id = %s
                    """,
                    (previous_run[0],),
                )
                previous = {
                    row[0]: {"size": row[1], "sha256": row[2].strip()}
                    for row in cursor.fetchall()
                }

        new_files = sorted(path for path in latest if path not in previous)
        deleted_files = sorted(path for path in previous if path not in latest)
        modified_files = sorted(
            path for path in latest
            if path in previous
            and latest[path]["sha256"] != previous[path]["sha256"]
        )
        unchanged_files = sorted(
            path for path in latest
            if path in previous
            and latest[path]["sha256"] == previous[path]["sha256"]
        )

        return {
            "source_id": str(source_id),
            "latest_run_id": str(latest_run[0]),
            "previous_run_id": str(previous_run[0]),
            "summary": {
                "new": len(new_files),
                "modified": len(modified_files),
                "deleted": len(deleted_files),
                "unchanged": len(unchanged_files),
            },
            "new_files": new_files,
            "modified_files": [
                {
                    "path": path,
                    "previous_size_bytes": previous[path]["size"],
                    "current_size_bytes": latest[path]["size"],
                }
                for path in modified_files
            ],
            "deleted_files": deleted_files,
            "unchanged_files": unchanged_files,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Échec de la comparaison pour la source %s", source_id)
        raise HTTPException(
            status_code=500,
            detail="La comparaison a échoué. Vérifiez les journaux du serveur.",
        )

@router.get("/history/{source_id}")
def inventory_history(source_id: UUID, limit: int = 20):
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="La limite doit être comprise entre 1 et 100.",
        )

    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, status, files_scanned, errors_count,
                           started_at, finished_at, error_message
                    FROM inventory_runs
                    WHERE source_id = %s
                    ORDER BY started_at DESC
                    LIMIT %s
                    """,
                    (source_id, limit),
                )
                rows = cursor.fetchall()

        return {
            "source_id": str(source_id),
            "count": len(rows),
            "runs": [
                {
                    "run_id": str(row[0]),
                    "status": row[1],
                    "files_scanned": row[2],
                    "errors_count": row[3],
                    "started_at": row[4].isoformat() if row[4] else None,
                    "finished_at": row[5].isoformat() if row[5] else None,
                    "error_message": row[6],
                }
                for row in rows
            ],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Échec de la lecture de l'historique pour la source %s", source_id)
        raise HTTPException(
            status_code=500,
            detail="Impossible de consulter l'historique des inventaires.",
        )


@router.get("/runs/{run_id}")
def inventory_run_detail(run_id: UUID):
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.id, r.source_id, s.name, r.status, r.files_scanned,
                           r.errors_count, r.started_at, r.finished_at,
                           r.error_message
                    FROM inventory_runs r JOIN sources s ON s.id = r.source_id
                    WHERE r.id = %s
                    """,
                    (run_id,),
                )
                run = cursor.fetchone()
                if run is None:
                    raise HTTPException(status_code=404, detail="Exécution introuvable.")
                cursor.execute(
                    """
                    SELECT relative_path, size_bytes, modified_at, sha256
                    FROM inventory_files WHERE run_id = %s
                    ORDER BY relative_path
                    """,
                    (run_id,),
                )
                files = cursor.fetchall()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Échec de la lecture de l'exécution %s", run_id)
        raise HTTPException(
            status_code=500,
            detail="Impossible de consulter l'exécution.",
        )

    return {
        "run_id": str(run[0]),
        "source_id": str(run[1]),
        "source_name": run[2],
        "status": run[3],
        "files_scanned": run[4],
        "errors_count": run[5],
        "started_at": run[6].isoformat() if run[6] else None,
        "finished_at": run[7].isoformat() if run[7] else None,
        "error_message": run[8],
        "total_size_bytes": sum(f[1] for f in files),
        "files": [
            {
                "path": f[0],
                "size_bytes": f[1],
                "modified_at": f[2].isoformat(),
                "sha256": f[3].strip(),
            }
            for f in files
        ],
    }
