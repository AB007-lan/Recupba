import { useState, type FormEvent } from "react";
import { api, type Source } from "../api";
import { Alert, Empty, Link, Loading, PageHeader, formatDate, navigate, useLoad } from "../ui";

export function SourcesPage() {
  const { data, error, loading, reload } = useLoad(() => api.sources());
  const [showForm, setShowForm] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = (data ?? []).filter((source) =>
    `${source.name} ${source.configuration.path ?? ""}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <>
      <PageHeader
        title="Sources"
        subtitle="Dossiers et systèmes surveillés par RECUPBA."
        actions={
          <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Annuler" : "+ Nouvelle source"}
          </button>
        }
      />

      {showForm && (
        <SourceForm
          onCreated={(source) => {
            setShowForm(false);
            reload();
            navigate(`/app/sources/${source.id}`);
          }}
        />
      )}

      {error && <Alert>{error}</Alert>}
      {loading && !data && <Loading />}

      {data && (
        <section className="card">
          <div className="card-header">
            <h2>{data.length} source{data.length > 1 ? "s" : ""}</h2>
            <input
              className="input search"
              type="search"
              placeholder="Rechercher par nom ou chemin…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Rechercher une source"
            />
          </div>
          {filtered.length === 0 ? (
            <Empty title={data.length ? "Aucune source ne correspond" : "Aucune source"}>
              {data.length ? "Modifiez votre recherche." : "Créez une première source pour lancer un inventaire."}
            </Empty>
          ) : (
            <ul className="source-list">
              {filtered.map((source) => (
                <li key={source.id}>
                  <Link to={`/app/sources/${source.id}`} className="source-item">
                    <div className="source-main">
                      <span className="source-name">{source.name}</span>
                      <code className="source-path">{source.configuration.path ?? "—"}</code>
                    </div>
                    <div className="source-meta">
                      <span className="tag">{source.source_type}</span>
                      <span className={`dot ${source.enabled ? "dot-on" : "dot-off"}`}>
                        {source.enabled ? "Activée" : "Désactivée"}
                      </span>
                      <span className="muted">Créée le {formatDate(source.created_at)}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}

export function SourceForm({ initial, onCreated, onSaved }: {
  initial?: Source;
  onCreated?: (source: Source) => void;
  onSaved?: (source: Source) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [path, setPath] = useState(initial?.configuration.path ?? "");
  const [recursive, setRecursive] = useState(initial?.configuration.recursive ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const configuration = { ...(initial?.configuration ?? {}), path: path.trim(), recursive };
    try {
      if (initial) {
        onSaved?.(await api.updateSource(initial.id, { name: name.trim(), configuration }));
      } else {
        onCreated?.(await api.createSource({
          name: name.trim(), source_type: "filesystem", configuration, enabled: true,
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="card form" onSubmit={submit}>
      <h2>{initial ? "Modifier la source" : "Nouvelle source de fichiers"}</h2>
      {error && <Alert>{error}</Alert>}
      <label className="field">
        <span>Nom</span>
        <input className="input" required maxLength={150} value={name}
          onChange={(e) => setName(e.target.value)} placeholder="Ex. : Documents comptables" />
      </label>
      <label className="field">
        <span>Chemin du dossier</span>
        <input className="input mono" required value={path}
          onChange={(e) => setPath(e.target.value)} placeholder="E:\Donnees\Comptabilite" />
        <small>Le dossier doit exister sur la machine qui exécute l'API. Il est seulement lu, jamais modifié.</small>
      </label>
      <label className="check">
        <input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} />
        <span>Inclure les sous-dossiers</span>
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? "Enregistrement…" : initial ? "Enregistrer" : "Créer la source"}
        </button>
      </div>
    </form>
  );
}
