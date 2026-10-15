import { api } from "../api";
import { Alert, Empty, Link, Loading, PageHeader, formatDate, shortId, useLoad } from "../ui";

const EVENT_LABELS: Record<string, string> = {
  "source.created": "Source créée",
  "source.updated": "Source modifiée",
  "inventory.completed": "Inventaire terminé",
  "inventory.failed": "Inventaire en échec",
  "inventory.interrupted": "Inventaire interrompu",
  "backup.completed": "Sauvegarde terminée",
  "backup.failed": "Sauvegarde en échec",
  "backup.interrupted": "Sauvegarde interrompue",
  "backup.verified_ok": "Sauvegarde vérifiée",
  "backup.verified_corrupted": "Sauvegarde corrompue",
  "restore.completed": "Restauration terminée",
  "restore.failed": "Restauration en échec",
  "restore.interrupted": "Restauration interrompue",
};

function entityLink(type: string | null, id: string | null) {
  if (!id) return "—";
  if (type === "source") return <Link to={`/app/sources/${id}`} className="mono">{shortId(id)}</Link>;
  if (type === "backup") return <Link to={`/app/backups/${id}`} className="mono">{shortId(id)}</Link>;
  if (type === "inventory_run") return <Link to={`/app/runs/${id}`} className="mono">{shortId(id)}</Link>;
  return <span className="mono">{shortId(id)}</span>;
}

export function AuditPage() {
  const { data, error, loading, reload } = useLoad(() => api.audit(200));

  return (
    <>
      <PageHeader
        title="Journal d'audit"
        subtitle="Trace des opérations importantes effectuées par RECUPBA."
        actions={<button className="btn" onClick={reload} disabled={loading}>Actualiser</button>}
      />
      {error && <Alert>{error}</Alert>}
      {loading && !data && <Loading />}
      {data && (
        <section className="card">
          {data.length === 0 ? (
            <Empty title="Journal vide">Les prochaines opérations apparaîtront ici.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Date</th><th>Événement</th><th>Élément</th><th>Détails</th></tr>
                </thead>
                <tbody>
                  {data.map((event) => (
                    <tr key={event.id}>
                      <td className="nowrap">{formatDate(event.created_at)}</td>
                      <td><span className={`event event-${event.event_type.split(".")[1].replace("verified_ok", "completed").replace("verified_corrupted", "failed")}`}>{EVENT_LABELS[event.event_type] ?? event.event_type}</span></td>
                      <td>{entityLink(event.entity_type, event.entity_id)}</td>
                      <td className="details">
                        {Object.entries(event.details).map(([key, value]) => (
                          <span key={key}><em>{key}</em> {typeof value === "object" ? JSON.stringify(value) : String(value)}</span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
