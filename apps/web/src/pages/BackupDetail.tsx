import { useState, type FormEvent } from "react";
import { api } from "../api";
import {
  Alert, Empty, Loading, PageHeader, Stat, StatusBadge,
  formatBytes, formatDate, formatDuration, formatRelative, shortId, useLoad,
} from "../ui";

type Message = { kind: "success" | "error" | "info"; text: string };

export function BackupDetailPage({ id }: { id: string }) {
  const { data, error, reload } = useLoad(() => api.backup(id), [id]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<Message | null>(null);
  const [verifying, setVerifying] = useState(false);

  if (error) {
    return (
      <>
        <PageHeader title="Sauvegarde" back={{ to: "/app/sources", label: "Sources" }} />
        <Alert>{error}</Alert>
      </>
    );
  }
  if (!data) return <Loading />;

  const files = data.files.filter((f) => f.path.toLowerCase().includes(query.toLowerCase()));
  const allVisibleSelected = files.length > 0 && files.every((f) => selected.has(f.path));

  function toggle(path: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }

  function toggleAll() {
    setSelected((current) => {
      const next = new Set(current);
      files.forEach((f) => (allVisibleSelected ? next.delete(f.path) : next.add(f.path)));
      return next;
    });
  }

  async function verify() {
    setVerifying(true);
    setMessage(null);
    try {
      const result = await api.verifyBackup(id);
      setMessage(result.verification_status === "ok"
        ? { kind: "success", text: `Intégrité confirmée : ${result.files_checked} fichier(s) vérifié(s).` }
        : { kind: "error", text: `Sauvegarde corrompue : ${result.invalid_files.length} fichier(s) illisible(s) — ${result.invalid_files.slice(0, 5).join(", ")}` });
      reload();
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setVerifying(false);
    }
  }

  const restorable = data.status.startsWith("completed");

  return (
    <>
      <PageHeader
        title={`Sauvegarde ${shortId(data.backup_id)}`}
        back={{ to: `/app/sources/${data.source_id}`, label: data.source_name }}
        subtitle={<>Réalisée le {formatDate(data.started_at)}</>}
        actions={
          <>
            <StatusBadge status={data.status} />
            <button className="btn" onClick={verify} disabled={verifying || !restorable}>
              {verifying ? "Vérification…" : "Vérifier l'intégrité"}
            </button>
          </>
        }
      />

      {message && <Alert kind={message.kind} onClose={() => setMessage(null)}>{message.text}</Alert>}
      {data.error_message && <Alert>{data.error_message}</Alert>}

      <section className="stats-grid">
        <Stat label="Fichiers" value={data.files_count} />
        <Stat label="Volume" value={formatBytes(data.bytes_total)}
          hint={`${formatBytes(data.bytes_new)} nouveau(x) stocké(s)`} />
        <Stat label="Durée" value={formatDuration(data.started_at, data.finished_at)} />
        <Stat
          label="Intégrité"
          value={data.verification_status === "ok" ? "Vérifiée" : data.verification_status === "corrupted" ? "Corrompue" : "Non vérifiée"}
          hint={data.verified_at ? formatRelative(data.verified_at) : "Cliquez sur « Vérifier l'intégrité »"}
          tone={data.verification_status === "corrupted" ? "warn" : undefined}
        />
      </section>

      {restorable && (
        <RestoreForm
          backupId={id}
          selected={[...selected]}
          onDone={(m) => { setMessage(m); reload(); }}
        />
      )}

      <section className="card">
        <div className="card-header">
          <h2>Contenu de la sauvegarde</h2>
          <input className="input search" type="search" placeholder="Filtrer par chemin…"
            value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filtrer les fichiers" />
        </div>
        {files.length === 0 ? (
          <Empty title={data.files.length ? "Aucun fichier ne correspond" : "Sauvegarde vide"} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="check-col">
                    <input type="checkbox" checked={allVisibleSelected} onChange={toggleAll}
                      aria-label="Tout sélectionner" disabled={!restorable} />
                  </th>
                  <th>Chemin</th>
                  <th className="num">Taille</th>
                  <th>Modifié</th>
                  <th aria-label="Télécharger" />
                </tr>
              </thead>
              <tbody>
                {files.map((file) => (
                  <tr key={file.path} className={selected.has(file.path) ? "selected" : undefined}>
                    <td className="check-col">
                      <input type="checkbox" checked={selected.has(file.path)} onChange={() => toggle(file.path)}
                        aria-label={`Sélectionner ${file.path}`} disabled={!restorable} />
                    </td>
                    <td><code>{file.path}</code></td>
                    <td className="num">{formatBytes(file.size_bytes)}</td>
                    <td>{formatDate(file.modified_at)}</td>
                    <td className="right">
                      <a href={api.downloadUrl(id, file.path)} download>Télécharger</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-header"><h2>Restaurations effectuées</h2></div>
        {data.restores.length === 0 ? (
          <Empty title="Aucune restauration depuis cette sauvegarde" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Date</th><th>Dossier cible</th><th>Statut</th><th className="num">Restaurés</th><th className="num">Erreurs</th></tr>
              </thead>
              <tbody>
                {data.restores.map((r) => (
                  <tr key={r.restore_id}>
                    <td className="nowrap">{formatDate(r.started_at)}</td>
                    <td><code>{r.target_path}</code></td>
                    <td>
                      <StatusBadge status={r.status} />
                      {r.error_message && <div className="error-text">{r.error_message}</div>}
                    </td>
                    <td className="num">{r.files_restored}</td>
                    <td className="num">{r.errors_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function RestoreForm({ backupId, selected, onDone }: {
  backupId: string;
  selected: string[];
  onDone: (message: Message) => void;
}) {
  const [target, setTarget] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (overwrite && !window.confirm("Les fichiers déjà présents dans le dossier cible seront remplacés. Continuer ?")) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.restoreBackup(backupId, {
        target_path: target.trim(),
        paths: selected.length ? selected : undefined,
        overwrite,
      });
      const skipped = result.files_skipped.length
        ? ` ${result.files_skipped.length} fichier(s) déjà présent(s) non remplacé(s).`
        : "";
      onDone({
        kind: result.errors_count ? "info" : "success",
        text: `${result.files_restored} fichier(s) restauré(s) dans ${result.target_path}.${skipped}`,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form restore-form" onSubmit={submit}>
      <h2>Restaurer</h2>
      <p className="muted">
        {selected.length
          ? `${selected.length} fichier(s) sélectionné(s) dans la liste ci-dessous.`
          : "Toute la sauvegarde sera restaurée. Cochez des fichiers ci-dessous pour n'en restaurer qu'une partie."}
      </p>
      {error && <Alert>{error}</Alert>}
      <label className="field">
        <span>Dossier de destination</span>
        <input className="input mono" required value={target} onChange={(e) => setTarget(e.target.value)}
          placeholder="E:\Restauration\2026-10-15" />
        <small>Chemin absolu. Le dossier est créé s'il n'existe pas. Par sécurité, le dossier source d'origine est refusé.</small>
      </label>
      <label className="check">
        <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
        <span>Remplacer les fichiers déjà présents dans la destination</span>
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Restauration…" : selected.length ? `Restaurer ${selected.length} fichier(s)` : "Restaurer toute la sauvegarde"}
        </button>
      </div>
    </form>
  );
}
