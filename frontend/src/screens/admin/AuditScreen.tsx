import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";
import { Messages } from "./Messages";

interface AuditItem {
  id: number;
  created_at: string | null;
  user_email: string | null;
  action: string;
  entity: string;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
}
interface AuditPage {
  has_more: boolean;
  items: AuditItem[];
}

const PAGE = 50;
const ALLOWED = ["admin", "chief_accountant", "auditor"];

/** Jurnalul de audit: cine, ce și când a modificat (administrator, contabil-șef, auditor). */
export function AuditScreen() {
  const { orgId, role } = useShell();
  const [entities, setEntities] = useState<string[]>([]);
  const [entity, setEntity] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuditPage | null>(null);
  const { error, info, run } = useAction();
  const allowed = role !== undefined && ALLOWED.includes(role);
  const base = `/organizations/${orgId}/audit`;

  const load = useCallback(
    () =>
      run(async () => {
        const q = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
        if (entity) q.set("entity", entity);
        if (from) q.set("date_from", from);
        if (to) q.set("date_to", to);
        setPage(await api<AuditPage>(`${base}?${q}`));
      }),
    [base, entity, from, to, offset, run],
  );

  useEffect(() => {
    if (allowed) api<string[]>(`${base}/entities`).then(setEntities).catch(() => undefined);
  }, [allowed, base]);
  useEffect(() => {
    if (allowed) load();
  }, [allowed, load]);

  if (!allowed) {
    return (
      <>
        <h1>Jurnal de audit</h1>
        <div className="hint">Jurnalul este vizibil pentru administrator, contabilul-șef și auditor.</div>
      </>
    );
  }

  return (
    <>
      <h1>Jurnal de audit</h1>
      <Messages error={error} info={info} />
      <div className="bar">
        <select value={entity} onChange={(e) => { setOffset(0); setEntity(e.target.value); }} aria-label="Obiect">
          <option value="">Toate obiectele</option>
          {entities.map((e) => (
            <option key={e} value={e}>{e}</option>
          ))}
        </select>
        <input type="date" value={from} onChange={(e) => { setOffset(0); setFrom(e.target.value); }} aria-label="De la" />
        <input type="date" value={to} onChange={(e) => { setOffset(0); setTo(e.target.value); }} aria-label="Până la" />
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th>Data</th>
            <th>Utilizator</th>
            <th>Acțiune</th>
            <th>Obiect</th>
            <th>Detalii</th>
          </tr>
        </thead>
        <tbody>
          {page?.items.map((i) => (
            <tr key={i.id}>
              <td>{i.created_at ? i.created_at.replace("T", " ").slice(0, 16) : ""}</td>
              <td>{i.user_email ?? "—"}</td>
              <td>{i.action}</td>
              <td>{i.entity}</td>
              <td>{i.new_values ? JSON.stringify(i.new_values).slice(0, 120) : ""}</td>
            </tr>
          ))}
          {page && page.items.length === 0 && (
            <tr>
              <td colSpan={5}>Nicio înregistrare.</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="bar">
        <button className="b" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          ← Mai noi
        </button>
        <button className="b" disabled={!page?.has_more} onClick={() => setOffset(offset + PAGE)}>
          Mai vechi →
        </button>
      </div>
    </>
  );
}
