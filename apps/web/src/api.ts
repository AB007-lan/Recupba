export type Source = {
  id: string;
  name: string;
  source_type: "filesystem" | "csv" | "json" | "postgresql";
  configuration: { path?: string; recursive?: boolean; [key: string]: unknown };
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type RunSummary = {
  run_id: string;
  status: string;
  files_scanned: number;
  errors_count: number;
  started_at: string | null;
  finished_at: string | null;
  error_message?: string | null;
  source_id?: string;
  source_name?: string;
};

export type RunDetail = RunSummary & {
  source_id: string;
  source_name: string;
  total_size_bytes: number;
  files: { path: string; size_bytes: number; modified_at: string; sha256: string }[];
};

export type Comparison = {
  source_id: string;
  latest_run_id: string;
  previous_run_id: string;
  summary: { new: number; modified: number; deleted: number; unchanged: number };
  new_files: string[];
  modified_files: { path: string; previous_size_bytes: number; current_size_bytes: number }[];
  deleted_files: string[];
  unchanged_files: string[];
};

export type Stats = {
  sources_total: number;
  sources_enabled: number;
  runs_total: number;
  runs_with_problems: number;
  last_run_at: string | null;
  recent_runs: RunSummary[];
};

export type AuditEvent = {
  id: number;
  event_type: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(0, "Impossible de joindre l'API RECUPBA. Le serveur est-il démarré ?");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? "Données invalides : " + detail.map((d: { msg: string }) => d.msg).join(", ")
        : `Erreur HTTP ${response.status}`;
    throw new ApiError(response.status, message);
  }
  return body as T;
}

export const api = {
  health: () => request<{ status: string }>("/health/database"),
  stats: () => request<Stats>("/stats"),
  sources: () => request<Source[]>("/sources"),
  source: (id: string) => request<Source>(`/sources/${id}`),
  createSource: (data: Pick<Source, "name" | "source_type" | "configuration" | "enabled">) =>
    request<Source>("/sources", { method: "POST", body: JSON.stringify(data) }),
  updateSource: (id: string, data: Partial<Pick<Source, "name" | "configuration" | "enabled">>) =>
    request<Source>(`/sources/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  runInventory: (sourceId: string) =>
    request<RunSummary>("/inventory/run", { method: "POST", body: JSON.stringify({ source_id: sourceId }) }),
  history: (sourceId: string, limit = 50) =>
    request<{ count: number; runs: RunSummary[] }>(`/inventory/history/${sourceId}?limit=${limit}`),
  compare: (sourceId: string) => request<Comparison>(`/inventory/compare/${sourceId}`),
  run: (runId: string) => request<RunDetail>(`/inventory/runs/${runId}`),
  audit: (limit = 100) => request<AuditEvent[]>(`/audit?limit=${limit}`),
};
