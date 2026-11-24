import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { TreasuryDoc, TreasuryKind } from "../../api/treasury";
import { useCatalogs } from "../../catalog/useCatalogs";
import { onDocumentsChanged, notifyDocumentsChanged } from "../../lib/events";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, newId, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";
import { StatusIcon } from "../StatusIcon";

export const KIND_TITLES: Record<TreasuryKind, { list: string; one: string }> = {
  bank_receipt: { list: "Încasări pe cont", one: "Încasare pe cont" },
  bank_payment: { list: "Plăți din cont", one: "Plată din cont" },
  cash_receipt: { list: "Încasări numerar", one: "Încasare în numerar" },
  cash_payment: { list: "Plăți numerar", one: "Plată în numerar" },
  advance_report: { list: "Decont de avans", one: "Decont de avans" },
  service_act: { list: "Servicii primite (acte)", one: "Act de servicii" },
};

/** Lista documentelor unui tip (încasări/plăți bancă și casă, deconturi, acte) cu filtre și acțiuni. */
export function TreasuryList({ kind }: { kind: TreasuryKind }) {
  const { orgId, role, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<TreasuryDoc[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [state, setState] = useState("");
  const [bank, setBank] = useState("");
  const [q, setQ] = useState("");
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/treasury`;
  const titles = KIND_TITLES[kind];
  const hasBank = kind === "bank_receipt" || kind === "bank_payment";

  const load = useCallback(() => {
    const qs = new URLSearchParams({ kind });
    if (from) qs.set("date_from", from);
    if (to) qs.set("date_to", to);
    if (state) qs.set("posted", state === "posted" ? "true" : "false");
    if (bank) qs.set("bank_account_id", bank);
    if (q.trim()) qs.set("q", q.trim());
    api<TreasuryDoc[]>(`${base}/docs?${qs}`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [base, kind, from, to, state, bank, q, setError]);
  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("treasury", load), [load]);

  const sel = rows?.find((r) => r.document_id === selected);
  const create = () => openTab({ id: newId("tr"), title: `${titles.one} (nou)`, kind: "treasury-doc", params: { kind } });
  const open = (r: TreasuryDoc) =>
    openTab({ id: `tr:${r.document_id}`, title: `${titles.one} ${r.doc_number ?? ""}`, kind: "treasury-doc", params: { kind, documentId: r.document_id } });
  const dtkt = () =>
    sel && openTab({ id: `dtkt:${sel.document_id}`, title: `Dt/Kt: ${sel.doc_number ?? ""}`, kind: "dtkt", params: { route: "treasury/docs", documentId: sel.document_id } });
  const act = (path: "post" | "unpost", done: string) =>
    run(async () => {
      if (!sel) throw new Error("Alegeți un document");
      await api(`${base}/docs/${sel.document_id}/${path}`, { method: "POST" });
      notifyDocumentsChanged("treasury");
      return done;
    });
  const remove = () =>
    run(async () => {
      if (!sel) throw new Error("Alegeți un document");
      if (sel.is_posted) throw new Error("Documentul este înregistrat; anulați întâi înregistrarea");
      if (!window.confirm(`Ștergeți documentul ${sel.doc_number}?`)) return;
      await api(`${base}/docs/${sel.document_id}`, { method: "DELETE" });
      setSelected(null);
      notifyDocumentsChanged("treasury");
      return "Documentul a fost șters.";
    });

  const total = useMemo(() => (rows ?? []).reduce((s, r) => s + Number(r.amount ?? 0), 0), [rows]);
  const party = (r: TreasuryDoc) => r.counterparty_name ?? r.person_name ?? "";

  return (
    <div onKeyDown={(e) => e.key === "Insert" && editable && create()}>
      <h1>{titles.list}</h1>
      <div className="bar">
        {editable && (
          <button className="b primary" onClick={create}>
            Creare
          </button>
        )}
        <button className="b" onClick={() => sel && open(sel)} disabled={!sel}>
          Deschide
        </button>
        {editable && (
          <>
            <button className="b" onClick={() => act("post", "Documentul a fost înregistrat.")} disabled={!sel || busy || !!sel.is_posted}>
              Înregistrează
            </button>
            <button className="b" onClick={() => act("unpost", "Înregistrarea a fost anulată.")} disabled={!sel || busy || !sel.is_posted}>
              Anulează înregistrarea
            </button>
            <button className="b" onClick={remove} disabled={!sel || busy || !!sel.is_posted}>
              Șterge
            </button>
          </>
        )}
        <button className="b" onClick={dtkt} disabled={!sel}>
          Dt/Kt
        </button>
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      <div className="bar">
        <label>
          De la <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          Până la <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <select aria-label="Starea" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">Toate</option>
          <option value="posted">Înregistrate</option>
          <option value="draft">Neînregistrate</option>
        </select>
        {hasBank && (
          <select aria-label="Cont bancar" value={bank} onChange={(e) => setBank(e.target.value)}>
            <option value="">Toate conturile</option>
            {catalogs.bankAccounts.map((b) => (
              <option key={b.id} value={b.id}>
                {b.bank_name ?? "Bancă"} {b.iban.slice(-8)} ({b.currency})
              </option>
            ))}
          </select>
        )}
        <input aria-label="Căutare" placeholder="Număr, contrapartidă, destinație…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Messages error={error} info={info} />
      {rows === null && !error && <p className="muted">Se încarcă…</p>}
      {rows && (
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 24 }} />
              <th>Număr</th>
              <th>Data</th>
              {kind !== "advance_report" && kind !== "service_act" && <th>Operațiunea</th>}
              <th>{kind === "advance_report" ? "Persoana" : "Contrapartidă"}</th>
              <th className="num">Suma</th>
              <th>Valuta</th>
              <th>{kind === "advance_report" ? "Scopul" : "Destinația"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.document_id}
                className={selected === r.document_id ? "sel" : ""}
                tabIndex={0}
                onClick={() => setSelected(r.document_id)}
                onDoubleClick={() => open(r)}
                onKeyDown={(e) => e.key === "Enter" && open(r)}
              >
                <td>
                  <StatusIcon posted={r.is_posted} />
                </td>
                <td>{r.doc_number}</td>
                <td>{day(r.doc_date)}</td>
                {kind !== "advance_report" && kind !== "service_act" && <td>{r.operation_label}</td>}
                <td>{party(r)}</td>
                <td className="num">{money(r.amount)}</td>
                <td>{r.currency}</td>
                <td>{r.purpose}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  Nu sunt documente pentru filtrele alese.{editable ? " Apăsați „Creare” sau Insert." : ""}
                </td>
              </tr>
            )}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={kind === "advance_report" || kind === "service_act" ? 4 : 5}>
                  <b>Total ({rows.length})</b>
                </td>
                <td className="num">
                  <b>{money(total)}</b>
                </td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          )}
        </table>
      )}
      <p className="footer-note">
        Dublu clic deschide documentul · <span className="kbd">Insert</span> document nou
      </p>
    </div>
  );
}
