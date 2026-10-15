import { useCallback, useEffect, useState, type ReactNode } from "react";

// --- Navigation minimale basée sur l'historique du navigateur ---------------

export function navigate(to: string) {
  window.history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

export function usePath() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return path;
}

export function Link({ to, children, className }: { to: string; children: ReactNode; className?: string }) {
  return (
    <a
      href={to}
      className={className}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.button !== 0) return;
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}

// --- Chargement de données ---------------------------------------------------

export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loader());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload };
}

// --- Formatage ---------------------------------------------------------------

const dateFormat = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "medium" });

export function formatDate(value: string | null | undefined) {
  return value ? dateFormat.format(new Date(value)) : "—";
}

export function formatRelative(value: string | null | undefined) {
  if (!value) return "jamais";
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return rtf.format(-seconds, "second");
  if (Math.abs(seconds) < 3600) return rtf.format(-Math.round(seconds / 60), "minute");
  if (Math.abs(seconds) < 86400) return rtf.format(-Math.round(seconds / 3600), "hour");
  return rtf.format(-Math.round(seconds / 86400), "day");
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} o`;
  const units = ["Ko", "Mo", "Go", "To"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} ${units[unit]}`;
}

export function formatDuration(start: string | null, end: string | null) {
  if (!start || !end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
}

// --- Composants --------------------------------------------------------------

const STATUS_LABELS: Record<string, string> = {
  completed: "Terminé",
  completed_with_errors: "Terminé avec erreurs",
  running: "En cours",
  failed: "Échec",
  interrupted: "Interrompu",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function Alert({ kind = "error", children, onClose }: { kind?: "error" | "success" | "info"; children: ReactNode; onClose?: () => void }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      <span>{children}</span>
      {onClose && (
        <button className="alert-close" onClick={onClose} aria-label="Fermer">×</button>
      )}
    </div>
  );
}

export function Loading({ label = "Chargement…" }: { label?: string }) {
  return <div className="loading"><span className="spinner" aria-hidden /> {label}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, back }: { title: string; subtitle?: ReactNode; actions?: ReactNode; back?: { to: string; label: string } }) {
  return (
    <header className="page-header">
      <div>
        {back && <Link to={back.to} className="back-link">← {back.label}</Link>}
        <h1>{title}</h1>
        {subtitle && <p className="subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "warn" }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

export function shortId(id: string) {
  return id.slice(0, 8);
}
