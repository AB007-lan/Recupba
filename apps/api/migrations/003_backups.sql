CREATE TABLE IF NOT EXISTS backups (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES sources(id),
    status VARCHAR(30) NOT NULL DEFAULT 'running',
    files_count INTEGER NOT NULL DEFAULT 0,
    bytes_total BIGINT NOT NULL DEFAULT 0,
    bytes_new BIGINT NOT NULL DEFAULT 0,
    objects_new INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    verification_status VARCHAR(20),
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_backups_source_started
    ON backups (source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS backup_files (
    backup_id UUID NOT NULL REFERENCES backups(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    modified_at TIMESTAMPTZ NOT NULL,
    sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (backup_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_backup_files_sha256 ON backup_files (sha256);

CREATE TABLE IF NOT EXISTS restores (
    id UUID PRIMARY KEY,
    backup_id UUID NOT NULL REFERENCES backups(id),
    target_path TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'running',
    files_restored INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_restores_backup ON restores (backup_id);
