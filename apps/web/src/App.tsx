import { useEffect, useState } from "react";
import { api } from "./api";
import { Link, usePath } from "./ui";
import { AuditPage } from "./pages/Audit";
import { BackupDetailPage } from "./pages/BackupDetail";
import { Dashboard } from "./pages/Dashboard";
import { RunDetail } from "./pages/RunDetail";
import { SourceDetail } from "./pages/SourceDetail";
import { SourcesPage } from "./pages/Sources";

const NAV = [
  { to: "/app", label: "Tableau de bord", match: (p: string) => p === "/" || p === "/app" || p.startsWith("/app/runs") },
  { to: "/app/sources", label: "Sources", match: (p: string) => p.startsWith("/app/sources") || p.startsWith("/app/backups") },
  { to: "/app/audit", label: "Journal d'audit", match: (p: string) => p.startsWith("/app/audit") },
];

function route(path: string) {
  const source = path.match(/^\/app\/sources\/([0-9a-f-]{36})$/i);
  if (source) return <SourceDetail id={source[1]} />;
  const run = path.match(/^\/app\/runs\/([0-9a-f-]{36})$/i);
  if (run) return <RunDetail id={run[1]} />;
  const backup = path.match(/^\/app\/backups\/([0-9a-f-]{36})$/i);
  if (backup) return <BackupDetailPage id={backup[1]} />;
  if (path === "/app/sources") return <SourcesPage />;
  if (path === "/app/audit") return <AuditPage />;
  return <Dashboard />;
}

function HealthIndicator() {
  const [state, setState] = useState<"ok" | "down" | "checking">("checking");
  useEffect(() => {
    const check = () => api.health().then(() => setState("ok")).catch(() => setState("down"));
    check();
    const timer = setInterval(check, 30000);
    return () => clearInterval(timer);
  }, []);
  const label = { ok: "API et base connectées", down: "API ou base indisponible", checking: "Vérification…" }[state];
  return <div className={`health health-${state}`} title={label}><span className="health-dot" />{label}</div>;
}

export function App() {
  const path = usePath();
  return (
    <div className="layout">
      <aside className="sidebar">
        <Link to="/app" className="brand">
          <span className="brand-mark">R</span>
          <span>RECUPBA</span>
        </Link>
        <nav aria-label="Navigation principale">
          {NAV.map((item) => (
            <Link key={item.to} to={item.to} className={item.match(path) ? "nav-link active" : "nav-link"}>
              {item.label}
            </Link>
          ))}
          <a className="nav-link" href="/docs" target="_blank" rel="noreferrer">Documentation API ↗</a>
        </nav>
        <HealthIndicator />
      </aside>
      <main className="content">{route(path)}</main>
    </div>
  );
}
