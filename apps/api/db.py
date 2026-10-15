import logging
import os
from pathlib import Path
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

BASE_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("recupba.db")


def database_connection():
    password = os.getenv("RECUPBA_DB_PASSWORD")
    if not password:
        raise RuntimeError("RECUPBA_DB_PASSWORD est absent du fichier .env")

    return psycopg.connect(
        host=os.getenv("RECUPBA_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("RECUPBA_DB_PORT", "5438")),
        dbname=os.getenv("RECUPBA_DB_NAME", "recupba"),
        user=os.getenv("RECUPBA_DB_USER", "recupba"),
        password=password,
        connect_timeout=3,
    )


def apply_migrations() -> None:
    """Applique les migrations SQL idempotentes (CREATE ... IF NOT EXISTS)."""
    with database_connection() as connection:
        for script in sorted(MIGRATIONS_DIR.glob("*.sql")):
            connection.execute(script.read_text(encoding="utf-8-sig"))


def log_event(
    cursor,
    event_type: str,
    entity_type: str | None = None,
    entity_id: UUID | str | None = None,
    details: dict | None = None,
) -> None:
    """Ajoute une entrée au journal d'audit dans la transaction en cours."""
    cursor.execute(
        """
        INSERT INTO audit_events (event_type, entity_type, entity_id, details)
        VALUES (%s, %s, %s, %s)
        """,
        (event_type, entity_type, entity_id, Jsonb(details or {})),
    )


def mark_interrupted_runs() -> int:
    """Clôt les inventaires restés « running » après un arrêt brutal du serveur."""
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE inventory_runs
                SET status = 'interrupted',
                    finished_at = clock_timestamp(),
                    error_message = 'Exécution interrompue (arrêt du serveur).'
                WHERE status = 'running'
                RETURNING id, source_id
                """
            )
            rows = cursor.fetchall()
            for run_id, source_id in rows:
                log_event(cursor, "inventory.interrupted", "inventory_run", run_id,
                          {"source_id": str(source_id)})
            for table, entity in (("backups", "backup"), ("restores", "restore")):
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'interrupted',
                        finished_at = clock_timestamp(),
                        error_message = 'Opération interrompue (arrêt du serveur).'
                    WHERE status = 'running'
                    RETURNING id
                    """
                )
                interrupted = cursor.fetchall()
                for (row_id,) in interrupted:
                    log_event(cursor, f"{entity}.interrupted", entity, row_id)
                rows += interrupted
    return len(rows)
