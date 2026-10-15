CREATE TABLE IF NOT EXISTS inventory_runs (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES sources(id),
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    files_scanned INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_inventory_runs_source_started
    ON inventory_runs (source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS inventory_files (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES inventory_runs(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    modified_at TIMESTAMPTZ NOT NULL,
    sha256 CHAR(64) NOT NULL,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_inventory_files_run ON inventory_files (run_id);
CREATE INDEX IF NOT EXISTS idx_inventory_files_sha256 ON inventory_files (sha256);
