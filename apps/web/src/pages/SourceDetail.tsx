import { useState } from "react";
import { ApiError, api, type Comparison } from "../api";
import {
  Alert, Empty, Link, Loading, PageHeader, StatusBadge,
  formatDate, formatDuration, formatRelative, shortId, useLoad,
} from "../ui";
import { SourceForm } from "./Sources";

type Tab = "history" | "compare";

export function SourceDetail({ id }: { id: string }) {
  const source = useLoad(() => api.source(id), [id]);
  const history = useLoad(() => api.history(id), [id]);
  const [tab, setTab] = useState<Tab>("history");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [compareKey, setCompareKey] = useState(0);

  async function runInventory() {
    setBusy(true);
    setMessage(null);
    try {
      const run = await api.runInventory(id);
      setMessage({
        kind: run.errors_count ? "error" : "success",
        text: `Inventaire terminé : ${run.files_scanned} fichier(s) analysé(s), ${run.errors_count} erreur(s).`,
      });
      history.reload();
      setCompareKey((k) => k + 1);
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
      history.reload();
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled() {
    if (!source.data) return;
    setBusy(true);
    try {
      await api.updateSource(id, { enabled: !source.data.enabled });
      source.reload();
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  if (source.error) {
    return (
      <>
        <PageHeader title="Source" back={{ to: "/app/sources", label: "Sources" }} />
        <Alert>{source.error}</Alert>
      </>
    );
  }
  if (!source.data) return <Loading />;
  const s = source.data;

  return (
    <>
      <PageHeader
        title={s.name}
        back={{ to: "/app/sources", label: "Sources" }}
        subtitle={<code>{s.configuration.path ?? "—"}</code>}
        actions={
          <>
            <button className="btn" onClick={() => setEditing((v) => !v)} disabled={busy}>
              {editing ? "Fermer" : "Modifier"}
            </button>
            <button className="btn" onClick={toggleEnabled} disabled={busy}>
              {s.enabled ? "Désactiver" : "Activer"}
            </button>
            <button className="btn btn-primary" onClick={runInventory} disabled={busy || !s.enabled}
              title={s.enabled ? undefined : "Activez la source pour lancer un inventaire"}>
              {busy ? "Inventaire en cours…" : "Lancer un inventaire"}
            </button>
          </>
        }
      />

      {message && <Alert kind={message.kind} onClose={() => setMessage(null)}>{message.text}</Alert>}

      {editing && (
        <SourceForm initial={s} onSaved={() => { setEditing(false); source.reload(); }} />
      )}

      <section className="facts">
        <div><span>Type</span><strong>{s.source_type}</strong></div>
        <div><span>État</span><strong className={s.enabled ? "ok" : "muted"}>{s.enabled ? "Activée" : "Désactivée"}</strong></div>
        <div><span>Sous-dossiers</span><strong>{s.configuration.recursive === false ? "Non" : "Oui"}</strong></div>
        <div><span>Identifiant</span><strong className="mono" title={s.id}>{shortId(s.id)}</strong></div>
        <div><span>Mise à jour</span><strong>{formatDate(s.updated_at)}</strong></div>
      </section>

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "history"} className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
          Historique {history.data ? `(${history.data.count})` : ""}
        </button>
        <button role="tab" aria-selected={tab === "compare"} className={tab === "compare" ? "active" : ""} onClick={() => setTab("compare")}>
          Dernières modifications
        </button>
      </div>

      {tab === "history" && (
        <section className="card">
          {history.error && <Alert>{history.error}</Alert>}
          {history.loading && !history.data && <Loading />}
          {history.data && history.data.runs.length === 0 && (
            <Empty title="Aucun inventaire">Lancez un premier inventaire pour enregistrer l'état des fichiers.</Empty>
          )}
          {history.data && history.data.runs.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Exécution</th>
                    <th>Statut</th>
                    <th className="num">Fichiers</th>
                    <th className="num">Erreurs</th>
                    <th>Démarré</th>
                    <th className="num">Durée</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.runs.map((run) => (
                    <tr key={run.run_id}>
                      <td><Link to={`/app/runs/${run.run_id}`} className="mono">{shortId(run.run_id)}</Link></td>
                      <td>
                        <StatusBadge status={run.status} />
                        {run.error_message && <div className="error-text">{run.error_message}</div>}
                      </td>
                      <td className="num">{run.files_scanned}</td>
                      <td className="num">{run.errors_count}</td>
                      <td title={formatDate(run.started_at)}>{formatRelative(run.started_at)}</td>
                      <td className="num">{formatDuration(run.started_at, run.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "compare" && <ComparePanel key={compareKey} sourceId={id} />}
    </>
  );
}

function ComparePanel({ sourceId }: { sourceId: string }) {
  const [filter, setFilter] = useState<"changes" | "all">("changes");
  const { data, error, loading } = useLoad<Comparison | null>(async () => {
    try {
      return await api.compare(sourceId);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) return null;
      throw err;
    }
  }, [sourceId]);

  if (loading) return <section className="card"><Loading /></section>;
  if (error) return <Alert>{error}</Alert>;
  if (!data) {
    return (
      <section className="card">
        <Empty title="Comparaison indisponible">Il faut au moins deux inventaires terminés pour comparer.</Empty>
      </section>
    );
  }

  const rows = [
    ...data.new_files.map((path) => ({ path, kind: "new", label: "Nouveau", info: "" })),
    ...data.modified_files.map((f) => ({
      path: f.path, kind: "modified", label: "Modifié",
      info: `${f.previous_size_bytes} → ${f.current_size_bytes} o`,
    })),
    ...data.deleted_files.map((path) => ({ path, kind: "deleted", label: "Supprimé", info: "" })),
    ...(filter === "all"
      ? data.unchanged_files.map((path) => ({ path, kind: "unchanged", label: "Inchangé", info: "" }))
      : []),
  ];

  return (
    <section className="card">
      <p className="muted compare-runs">
        Exécution <Link to={`/app/runs/${data.latest_run_id}`} className="mono">{shortId(data.latest_run_id)}</Link>{" "}
        comparée à <Link to={`/app/runs/${data.previous_run_id}`} className="mono">{shortId(data.previous_run_id)}</Link>
      </p>
      <div className="diff-summary">
        <span className="diff diff-new"><strong>{data.summary.new}</strong> nouveau(x)</span>
        <span className="diff diff-modified"><strong>{data.summary.modified}</strong> modifié(s)</span>
        <span className="diff diff-deleted"><strong>{data.summary.deleted}</strong> supprimé(s)</span>
        <span className="diff diff-unchanged"><strong>{data.summary.unchanged}</strong> inchangé(s)</span>
      </div>
      <label className="check">
        <input type="checkbox" checked={filter === "all"} onChange={(e) => setFilter(e.target.checked ? "all" : "changes")} />
        <span>Afficher aussi les fichiers inchangés</span>
      </label>
      {rows.length === 0 ? (
        <Empty title="Aucun changement">Les deux derniers inventaires sont identiques.</Empty>
      ) : (
        <ul className="diff-list">
          {rows.map((row) => (
            <li key={`${row.kind}-${row.path}`} className={`diff-row diff-${row.kind}`}>
              <span className="diff-label">{row.label}</span>
              <code>{row.path}</code>
              {row.info && <span className="muted">{row.info}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
