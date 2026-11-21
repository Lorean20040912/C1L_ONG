import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ENTITY_LABELS, ROLE_LABELS, type EntityType, type Workspace } from "../api/types";
import { useAuth } from "../auth/AuthContext";

// „Bazele mele” (ToR F00.1): ca lista de baze de la pornirea 1C.
export function MyBasesPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = () =>
    api<Workspace[]>("/workspaces")
      .then((ws) => {
        setWorkspaces(ws);
        setSelected((s) => s ?? ws[0]?.organizations[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const open = (orgId: string | null) => orgId && navigate(`/org/${orgId}`);

  return (
    <div className="page">
      <div className="page-top">
        <span className="logo">
          Conta<b>Hub</b>
        </span>
        <span className="sp" />
        <span>{user?.full_name}</span>
        <button className="b" onClick={logout}>
          Ieșire
        </button>
      </div>
      <div className="panel wide">
        <h1>Bazele mele</h1>
        {error && <div className="error">{error}</div>}
        <div className="bar">
          <button className="b primary" disabled={!selected} onClick={() => open(selected)}>
            Deschide
          </button>
          <button className="b" onClick={() => setCreating((c) => !c)}>
            Bază nouă
          </button>
          <button className="b" disabled title="În lucru: importul din 1C vine într-o etapă următoare">
            Importă din 1C
          </button>
        </div>

        {creating && (
          <NewBaseForm
            onCreated={(ws) => {
              setCreating(false);
              setSelected(ws.organizations[0].id);
              load();
            }}
          />
        )}

        {workspaces === null && !error && <p className="muted">Se încarcă…</p>}
        {workspaces?.length === 0 && (
          <div className="hint">Nu aveți acces la nicio bază. Creați una cu „Bază nouă” sau cereți acces administratorului.</div>
        )}
        {workspaces && workspaces.length > 0 && (
          <table className="grid">
            <thead>
              <tr>
                <th>Baza</th>
                <th>Organizația</th>
                <th>Tipul</th>
                <th>IDNO</th>
                <th>Rolul meu</th>
              </tr>
            </thead>
            <tbody>
              {workspaces.flatMap((ws) =>
                ws.organizations.map((o, i) => (
                  <tr
                    key={o.id}
                    className={selected === o.id ? "sel" : ""}
                    onClick={() => setSelected(o.id)}
                    onDoubleClick={() => open(o.id)}
                    tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && open(o.id)}
                  >
                    <td>{i === 0 ? ws.name : ""}</td>
                    <td>{o.name}</td>
                    <td>{ENTITY_LABELS[o.entity_type]}</td>
                    <td>{o.idno}</td>
                    <td>{ROLE_LABELS[o.role]}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        )}
        <p className="muted">Dublu clic sau Enter pe rând deschide baza.</p>
      </div>
    </div>
  );
}

function NewBaseForm({ onCreated }: { onCreated: (ws: Workspace) => void }) {
  const [name, setName] = useState("");
  const [idno, setIdno] = useState("");
  const [entityType, setEntityType] = useState<EntityType>("ngo_association");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const ws = await api<Workspace>("/workspaces", {
        method: "POST",
        body: { name, organization_name: name, idno, entity_type: entityType },
      });
      onCreated(ws);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3>Bază nouă</h3>
      {error && <div className="error">{error}</div>}
      <div className="field">
        <label htmlFor="nb-name">Denumirea organizației</label>
        <input id="nb-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="nb-idno">IDNO (13 cifre)</label>
        <input
          id="nb-idno"
          value={idno}
          onChange={(e) => setIdno(e.target.value)}
          pattern="\d{13}"
          inputMode="numeric"
          required
        />
      </div>
      <div className="field">
        <label htmlFor="nb-type">Forma juridică</label>
        <select id="nb-type" value={entityType} onChange={(e) => setEntityType(e.target.value as EntityType)}>
          {Object.entries(ENTITY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <button className="b primary" type="submit">
        Creează
      </button>
    </form>
  );
}
