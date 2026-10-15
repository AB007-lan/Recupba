import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from db import (
    BASE_DIR,
    apply_migrations,
    database_connection,
    log_event,
    mark_interrupted_runs,
)

APP_VERSION = "0.3.0"
WEB_DIST = BASE_DIR / "apps" / "web" / "dist"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recupba")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        apply_migrations()
        interrupted = mark_interrupted_runs()
        if interrupted:
            logger.warning("%s inventaire(s) interrompu(s) clôturé(s).", interrupted)
    except Exception:
        logger.exception("Initialisation de la base impossible au démarrage.")
    yield


app = FastAPI(
    title="RECUPBA API",
    description="API de collecte et de synchronisation de données multi-sources.",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


SourceType = Literal["filesystem", "csv", "json", "postgresql"]
SOURCE_COLUMNS = "id, name, source_type, configuration, enabled, created_at, updated_at"


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    source_type: SourceType
    configuration: dict = Field(default_factory=dict)
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    configuration: dict | None = None
    enabled: bool | None = None


class SourceResponse(BaseModel):
    id: UUID
    name: str
    source_type: str
    configuration: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime


def source_from_row(row) -> SourceResponse:
    return SourceResponse(
        id=row[0],
        name=row[1],
        source_type=row[2],
        configuration=row[3],
        enabled=row[4],
        created_at=row[5],
        updated_at=row[6],
    )


def validate_configuration(source_type: str, configuration: dict) -> None:
    if source_type != "filesystem":
        return
    raw_path = configuration.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise HTTPException(status_code=400, detail="Le chemin « path » est obligatoire.")
    if not Path(raw_path).is_dir():
        raise HTTPException(
            status_code=400,
            detail="Le chemin indiqué n'existe pas ou n'est pas un dossier.",
        )
    if "recursive" in configuration and not isinstance(configuration["recursive"], bool):
        raise HTTPException(status_code=400, detail="« recursive » doit être un booléen.")


@app.get("/api", tags=["Accueil"])
def root():
    return {
        "application": "RECUPBA",
        "message": "API opérationnelle",
        "documentation": "/docs",
    }


@app.get("/health", tags=["Santé"])
def health_check():
    return {
        "status": "ok",
        "application": "RECUPBA",
        "version": APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health/database", tags=["Santé"])
def database_health_check():
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                database, user = cursor.fetchone()
        return {"status": "ok", "database": database, "user": user}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="La connexion à la base de données a échoué.",
        )


@app.post(
    "/sources",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Sources"],
)
def create_source(source: SourceCreate):
    validate_configuration(source.source_type, source.configuration)
    source_id = uuid4()

    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO sources
                        (id, name, source_type, configuration, enabled)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING {SOURCE_COLUMNS}
                    """,
                    (
                        source_id,
                        source.name,
                        source.source_type,
                        Jsonb(source.configuration),
                        source.enabled,
                    ),
                )
                row = cursor.fetchone()
                log_event(cursor, "source.created", "source", source_id,
                          {"name": source.name, "source_type": source.source_type})

        return source_from_row(row)
    except Exception:
        logger.exception("Échec de la création de source")
        raise HTTPException(
            status_code=503,
            detail="Impossible d'enregistrer la source dans la base de données.",
        )


@app.get("/sources", response_model=list[SourceResponse], tags=["Sources"])
def list_sources():
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {SOURCE_COLUMNS} FROM sources ORDER BY created_at DESC"
                )
                rows = cursor.fetchall()

        return [source_from_row(row) for row in rows]
    except Exception:
        logger.exception("Échec de la lecture des sources")
        raise HTTPException(
            status_code=503,
            detail="Impossible de consulter les sources.",
        )


@app.get("/sources/{source_id}", response_model=SourceResponse, tags=["Sources"])
def get_source(source_id: UUID):
    try:
        with database_connection() as connection:
            row = connection.execute(
                f"SELECT {SOURCE_COLUMNS} FROM sources WHERE id = %s", (source_id,)
            ).fetchone()
    except Exception:
        logger.exception("Échec de la lecture de la source %s", source_id)
        raise HTTPException(status_code=503, detail="Impossible de consulter la source.")
    if row is None:
        raise HTTPException(status_code=404, detail="Source introuvable.")
    return source_from_row(row)


@app.patch("/sources/{source_id}", response_model=SourceResponse, tags=["Sources"])
def update_source(source_id: UUID, update: SourceUpdate):
    current = get_source(source_id)
    changes = update.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return current

    if "configuration" in changes:
        validate_configuration(current.source_type, changes["configuration"])

    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE sources
                    SET name = COALESCE(%s, name),
                        configuration = COALESCE(%s, configuration),
                        enabled = COALESCE(%s, enabled),
                        updated_at = clock_timestamp()
                    WHERE id = %s
                    RETURNING {SOURCE_COLUMNS}
                    """,
                    (
                        changes.get("name"),
                        Jsonb(changes["configuration"]) if "configuration" in changes else None,
                        changes.get("enabled"),
                        source_id,
                    ),
                )
                row = cursor.fetchone()
                log_event(cursor, "source.updated", "source", source_id,
                          {"fields": sorted(changes)})
        return source_from_row(row)
    except Exception:
        logger.exception("Échec de la mise à jour de la source %s", source_id)
        raise HTTPException(status_code=503, detail="Impossible de modifier la source.")


@app.get("/stats", tags=["Tableau de bord"])
def dashboard_stats():
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM sources),
                        (SELECT COUNT(*) FROM sources WHERE enabled),
                        (SELECT COUNT(*) FROM inventory_runs),
                        (SELECT COUNT(*) FROM inventory_runs
                          WHERE status NOT IN ('completed', 'running')),
                        (SELECT MAX(started_at) FROM inventory_runs)
                    """
                )
                sources, enabled, runs, problems, last_run = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT r.id, r.source_id, s.name, r.status, r.files_scanned,
                           r.errors_count, r.started_at, r.finished_at
                    FROM inventory_runs r JOIN sources s ON s.id = r.source_id
                    ORDER BY r.started_at DESC LIMIT 8
                    """
                )
                recent = cursor.fetchall()
    except Exception:
        logger.exception("Échec du calcul des statistiques")
        raise HTTPException(status_code=503, detail="Statistiques indisponibles.")

    return {
        "sources_total": sources,
        "sources_enabled": enabled,
        "runs_total": runs,
        "runs_with_problems": problems,
        "last_run_at": last_run.isoformat() if last_run else None,
        "recent_runs": [
            {
                "run_id": str(r[0]),
                "source_id": str(r[1]),
                "source_name": r[2],
                "status": r[3],
                "files_scanned": r[4],
                "errors_count": r[5],
                "started_at": r[6].isoformat() if r[6] else None,
                "finished_at": r[7].isoformat() if r[7] else None,
            }
            for r in recent
        ],
    }


@app.get("/audit", tags=["Audit"])
def list_audit_events(limit: int = 50):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="La limite doit être comprise entre 1 et 200.")
    try:
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, event_type, entity_type, entity_id, details, created_at
                FROM audit_events ORDER BY created_at DESC, id DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
    except Exception:
        logger.exception("Échec de la lecture du journal d'audit")
        raise HTTPException(status_code=503, detail="Journal d'audit indisponible.")
    return [
        {
            "id": r[0],
            "event_type": r[1],
            "entity_type": r[2],
            "entity_id": str(r[3]) if r[3] else None,
            "details": r[4],
            "created_at": r[5].isoformat(),
        }
        for r in rows
    ]


from inventory import router as inventory_router  # noqa: E402

app.include_router(inventory_router)


# Interface web (build Vite) servie par l'API lorsqu'elle est construite.
if not WEB_DIST.is_dir():
    app.get("/", tags=["Accueil"])(root)
else:
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/app/{path:path}", include_in_schema=False)
    def web_app(path: str = ""):
        return FileResponse(WEB_DIST / "index.html")
