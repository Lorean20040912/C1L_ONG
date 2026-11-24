import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ENTITY_LABELS, ROLE_LABELS, type Workspace } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { NewBaseWizard } from "./NewBaseWizard";

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
          <button className="b" disabled={!selected} title="Deschide baza aleasă la ecranul de import din 1C" onClick={() => selected && navigate(`/org/${selected}`, { state: { open: "Import din 1C" } })}>
            Importă din 1C
          </button>
        </div>

        {creating && (
          <NewBaseWizard
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
