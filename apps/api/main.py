import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

app = FastAPI(
    title="RECUPBA API",
    description="API de collecte et de synchronisation de données multi-sources.",
    version="0.2.0",
)


def database_connection():
    password = os.getenv("RECUPBA_DB_PASSWORD")
    if not password:
        raise RuntimeError("RECUPBA_DB_PASSWORD est absent du fichier .env")

    return psycopg.connect(
        host="127.0.0.1",
        port=5438,
        dbname="recupba",
        user="recupba",
        password=password,
        connect_timeout=3,
    )


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    source_type: Literal["filesystem", "csv", "json", "postgresql"]
    configuration: dict = Field(default_factory=dict)
    enabled: bool = True


class SourceResponse(BaseModel):
    id: UUID
    name: str
    source_type: str
    configuration: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime


@app.get("/", tags=["Accueil"])
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
        "version": "0.2.0",
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
    source_id = uuid4()

    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sources
                        (id, name, source_type, configuration, enabled)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, name, source_type, configuration,
                              enabled, created_at, updated_at
                    """,
                    (
                        source_id,
                        source.name,
                        source.source_type,
                        psycopg.types.json.Jsonb(source.configuration),
                        source.enabled,
                    ),
                )
                row = cursor.fetchone()

        return SourceResponse(
            id=row[0],
            name=row[1],
            source_type=row[2],
            configuration=row[3],
            enabled=row[4],
            created_at=row[5],
            updated_at=row[6],
        )
    except Exception:
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
                    """
                    SELECT id, name, source_type, configuration,
                           enabled, created_at, updated_at
                    FROM sources
                    ORDER BY created_at DESC
                    """
                )
                rows = cursor.fetchall()

        return [
            SourceResponse(
                id=row[0],
                name=row[1],
                source_type=row[2],
                configuration=row[3],
                enabled=row[4],
                created_at=row[5],
                updated_at=row[6],
            )
            for row in rows
        ]
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Impossible de consulter les sources.",
        )

from inventory import router as inventory_router
app.include_router(inventory_router)

