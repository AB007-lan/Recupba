import { api } from "../api";
import { Alert, Empty, Link, Loading, PageHeader, Stat, StatusBadge, formatDate, formatRelative, useLoad } from "../ui";

export function Dashboard() {
  const { data, error, loading, reload } = useLoad(() => api.stats());

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        subtitle="Vue d'ensemble des sources et des inventaires de fichiers."
        actions={<button className="btn" onClick={reload} disabled={loading}>Actualiser</button>}
      />

      {error && <Alert>{error}</Alert>}
      {loading && !data && <Loading />}

      {data && (
        <>
          <section className="stats-grid">
            <Stat label="Sources" value={data.sources_total} hint={`${data.sources_enabled} activée(s)`} />
            <Stat label="Inventaires" value={data.runs_total} hint={`Dernier : ${formatRelative(data.last_run_at)}`} />
            <Stat
              label="À surveiller"
              value={data.runs_with_problems}
              hint="Échecs, interruptions ou erreurs"
              tone={data.runs_with_problems > 0 ? "warn" : undefined}
            />
          </section>

          <section className="card">
            <div className="card-header">
              <h2>Derniers inventaires</h2>
              <Link to="/app/sources" className="btn btn-ghost">Voir les sources</Link>
            </div>
            {data.recent_runs.length === 0 ? (
              <Empty title="Aucun inventaire pour l'instant">
                Ouvrez une source puis lancez un premier inventaire.
              </Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Statut</th>
                      <th className="num">Fichiers</th>
                      <th className="num">Erreurs</th>
                      <th>Démarré</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_runs.map((run) => (
                      <tr key={run.run_id}>
                        <td><Link to={`/app/sources/${run.source_id}`}>{run.source_name}</Link></td>
                        <td><StatusBadge status={run.status} /></td>
                        <td className="num">{run.files_scanned}</td>
                        <td className="num">{run.errors_count}</td>
                        <td title={formatDate(run.started_at)}>{formatRelative(run.started_at)}</td>
                        <td className="right"><Link to={`/app/runs/${run.run_id}`}>Détail →</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
