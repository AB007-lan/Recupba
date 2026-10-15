import { useState } from "react";
import { api } from "../api";
import {
  Alert, Empty, Loading, PageHeader, Stat, StatusBadge,
  formatBytes, formatDate, formatDuration, shortId, useLoad,
} from "../ui";

export function RunDetail({ id }: { id: string }) {
  const { data, error } = useLoad(() => api.run(id), [id]);
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  if (error) {
    return (
      <>
        <PageHeader title="Exécution" back={{ to: "/app", label: "Tableau de bord" }} />
        <Alert>{error}</Alert>
      </>
    );
  }
  if (!data) return <Loading />;

  const files = data.files.filter((f) => f.path.toLowerCase().includes(query.toLowerCase()));

  async function copy(hash: string) {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(hash);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* presse-papiers indisponible */
    }
  }

  return (
    <>
      <PageHeader
        title={`Inventaire ${shortId(data.run_id)}`}
        back={{ to: `/app/sources/${data.source_id}`, label: data.source_name }}
        subtitle={<>Démarré le {formatDate(data.started_at)}</>}
        actions={<StatusBadge status={data.status} />}
      />

      {data.error_message && <Alert>{data.error_message}</Alert>}

      <section className="stats-grid">
        <Stat label="Fichiers" value={data.files_scanned} />
        <Stat label="Volume total" value={formatBytes(data.total_size_bytes)} />
        <Stat label="Erreurs" value={data.errors_count} tone={data.errors_count ? "warn" : undefined} />
        <Stat label="Durée" value={formatDuration(data.started_at, data.finished_at)} />
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Fichiers inventoriés</h2>
          <input className="input search" type="search" placeholder="Filtrer par chemin…"
            value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filtrer les fichiers" />
        </div>
        {files.length === 0 ? (
          <Empty title={data.files.length ? "Aucun fichier ne correspond" : "Aucun fichier enregistré"} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Chemin</th>
                  <th className="num">Taille</th>
                  <th>Modifié</th>
                  <th>SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {files.map((file) => (
                  <tr key={file.path}>
                    <td><code>{file.path}</code></td>
                    <td className="num">{formatBytes(file.size_bytes)}</td>
                    <td>{formatDate(file.modified_at)}</td>
                    <td>
                      <button className="hash" onClick={() => copy(file.sha256)} title={`${file.sha256}\nCliquer pour copier`}>
                        {copied === file.sha256 ? "Copié ✓" : `${file.sha256.slice(0, 12)}…`}
                      </button>
                    </td>
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
