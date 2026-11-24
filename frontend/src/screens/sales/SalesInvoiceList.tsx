import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { SalesListItem } from "../../api/sales";
import { useCatalogs } from "../../catalog/useCatalogs";
import { notifyDocumentsChanged, onDocumentsChanged } from "../../lib/events";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, newId, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";
import { StatusIcon } from "../StatusIcon";

/** Facturi emise către clienți și note de stornare: filtre, înregistrare, anulare, încasări. */
export function SalesInvoiceList() {
  const { orgId, role, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<SalesListItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [client, setClient] = useState("");
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/sales`;

  const load = useCallback(() => {
    const qs = new URLSearchParams();
    if (from) qs.set("date_from", from);
    if (to) qs.set("date_to", to);
    if (client) qs.set("counterparty_id", client);
    if (state === "posted") qs.set("posted", "true");
    if (state === "draft") qs.set("posted", "false");
    if (state === "unpaid") qs.set("unpaid", "true");
    if (q.trim()) qs.set("q", q.trim());
    api<SalesListItem[]>(`${base}/invoices?${qs}`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [base, from, to, client, state, q, setError]);
  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("sales", load), [load]);

  const sel = rows?.find((r) => r.document_id === selected);
  const label = (r: SalesListItem) => `${r.kind_label} ${r.series} ${r.number}`.replace("  ", " ");
  const create = () => openTab({ id: newId("sales"), title: "Factură emisă (nouă)", kind: "sales-invoice" });
  const open = (r: SalesListItem) => openTab({ id: `sales:${r.document_id}`, title: label(r), kind: "sales-invoice", params: { documentId: r.document_id } });
  const dtkt = () => sel && openTab({ id: `dtkt:${sel.document_id}`, title: `Dt/Kt: ${sel.number}`, kind: "dtkt", params: { route: "sales/invoices", documentId: sel.document_id } });
  const act = (path: "post" | "unpost", done: string) =>
    run(async () => {
      if (!sel) throw new Error("Alegeți un document");
      await api(`${base}/invoices/${sel.document_id}/${path}`, { method: "POST" });
      notifyDocumentsChanged("sales");
      return done;
    });
  const remove = () =>
    run(async () => {
      if (!sel) throw new Error("Alegeți un document");
      if (!window.confirm(`Ștergeți ${label(sel)}? Numărul va rămâne liber.`)) return;
      await api(`${base}/invoices/${sel.document_id}`, { method: "DELETE" });
      setSelected(null);
      notifyDocumentsChanged("sales");
      return "Documentul a fost șters.";
    });

  const total = useMemo(() => (rows ?? []).filter((r) => r.status === "active").reduce((s, r) => s + Number(r.gross), 0), [rows]);

  return (
    <div onKeyDown={(e) => e.key === "Insert" && editable && create()}>
      <h1>Facturi emise</h1>
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
            <button className="b" onClick={() => act("post", "Documentul a fost înregistrat.")} disabled={!sel || busy || !!sel.is_posted || sel.status === "cancelled"}>
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
        <select aria-label="Client" value={client} onChange={(e) => setClient(e.target.value)}>
          <option value="">Toți clienții</option>
          {catalogs.counterparties.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select aria-label="Starea" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">Toate</option>
          <option value="posted">Înregistrate</option>
          <option value="draft">Neînregistrate</option>
          <option value="unpaid">Neîncasate</option>
        </select>
        <input aria-label="Căutare" placeholder="Număr, client, IDNO…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Messages error={error} info={info} />
      {rows === null && !error && <p className="muted">Se încarcă…</p>}
      {rows && (
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 24 }} />
              <th>Tip</th>
              <th>Număr</th>
              <th>Data</th>
              <th>Scadența</th>
              <th>Client</th>
              <th className="num">Fără TVA</th>
              <th className="num">TVA</th>
              <th className="num">Total</th>
              <th className="num">Încasat</th>
              <th className="num">De încasat</th>
              <th>Valuta</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.document_id}
                className={selected === r.document_id ? "sel" : ""}
                style={r.status === "cancelled" ? { textDecoration: "line-through", opacity: 0.6 } : undefined}
                tabIndex={0}
                onClick={() => setSelected(r.document_id)}
                onDoubleClick={() => open(r)}
                onKeyDown={(e) => e.key === "Enter" && open(r)}
              >
                <td>
                  <StatusIcon posted={r.is_posted} />
                </td>
                <td>{r.status === "cancelled" ? "Anulată" : r.kind_label}</td>
                <td>{`${r.series} ${r.number}`.trim()}</td>
                <td>{day(r.doc_date)}</td>
                <td>{day(r.due_date)}</td>
                <td>{r.counterparty_name}</td>
                <td className="num">{money(r.net)}</td>
                <td className="num">{money(r.vat)}</td>
                <td className="num">{money(r.gross)}</td>
                <td className="num">{r.kind === "invoice" ? money(r.paid) : ""}</td>
                <td className="num">{r.kind === "invoice" && r.status === "active" && r.is_posted ? money(r.balance) : ""}</td>
                <td>{r.currency}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={12} className="muted">
                  Nu sunt facturi pentru filtrele alese.{editable ? " Apăsați „Creare” sau Insert." : ""}
                </td>
              </tr>
            )}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={8}>
                  <b>Total ({rows.length}, fără cele anulate)</b>
                </td>
                <td className="num">
                  <b>{money(total)}</b>
                </td>
                <td colSpan={3} />
              </tr>
            </tfoot>
          )}
        </table>
      )}
      <p className="footer-note">
        Dublu clic deschide factura · <span className="kbd">Insert</span> factură nouă · încasarea se face din factură sau din „Încasări pe cont / numerar”
      </p>
    </div>
  );
}
