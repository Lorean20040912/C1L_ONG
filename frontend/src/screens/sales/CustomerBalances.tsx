import { useCallback, useEffect, useState } from "react";
import { api, download } from "../../api/client";
import type { CustomerBalances as Report, CustomerRow } from "../../api/sales";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** Sold clienți (cont 221) cu vechimea creanțelor: după data facturii și după scadență, cu facturile deschise ale fiecărui client. */
export function CustomerBalances() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [asOf, setAsOf] = useState(today());
  const [client, setClient] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [open, setOpen] = useState<CustomerRow | null>(null);
  const { error, run } = useAction();
  const base = `/organizations/${orgId}/sales/reports`;

  const load = useCallback(() => {
    const qs = new URLSearchParams({ as_of: asOf });
    if (client) qs.set("counterparty_id", client);
    run(async () => setReport(await api<Report>(`${base}/customer-balances?${qs}`)));
  }, [base, asOf, client, run]);
  useEffect(load, [load]);

  const rows = report?.rows ?? [];
  const diff = report ? Number(report.ledger_balance) - Number(report.total_balance) : 0;

  return (
    <div>
      <h1>Sold clienți</h1>
      <div className="bar">
        <label>
          La data <input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
        </label>
        <select aria-label="Client" value={client} onChange={(e) => setClient(e.target.value)}>
          <option value="">Toți clienții</option>
          {catalogs.counterparties.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button className="b primary" onClick={load}>
          Actualizează
        </button>
        <button className="b" onClick={() => run(() => download(`${base}/customer-balances.csv?as_of=${asOf}`, `sold-clienti-${asOf}.csv`))} disabled={rows.length === 0}>
          Export CSV
        </button>
      </div>
      <Messages error={error} info={null} />
      {!report && !error && <p className="muted">Se încarcă…</p>}
      {report && (
        <>
          <table className="grid">
            <thead>
              <tr>
                <th>Client</th>
                <th>IDNO</th>
                <th className="num">Facturat</th>
                <th className="num">Stornat</th>
                <th className="num">Încasat</th>
                <th className="num">Sold</th>
                <th className="num">Nescadent</th>
                <th className="num">0–30 zile</th>
                <th className="num">31–60</th>
                <th className="num">61–90</th>
                <th className="num">&gt;90</th>
                <th className="num">Restant</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.counterparty_id} tabIndex={0} className={open === r ? "sel" : ""} onClick={() => setOpen(r)} onKeyDown={(e) => e.key === "Enter" && setOpen(r)}>
                  <td>{r.name}</td>
                  <td>{r.idno}</td>
                  <td className="num">{money(r.invoiced)}</td>
                  <td className="num">{money(r.credited)}</td>
                  <td className="num">{money(r.received)}</td>
                  <td className="num">
                    <b>{money(r.balance)}</b>
                  </td>
                  <td className="num">{money(r.not_due)}</td>
                  <td className="num">{money(r.age_0_30)}</td>
                  <td className="num">{money(r.age_31_60)}</td>
                  <td className="num">{money(r.age_61_90)}</td>
                  <td className="num">{money(r.age_over_90)}</td>
                  <td className="num">{money(r.overdue)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={12} className="muted">
                    Niciun client cu sold la această dată.
                  </td>
                </tr>
              )}
            </tbody>
            {rows.length > 0 && (
              <tfoot>
                <tr>
                  <td colSpan={5}>
                    <b>Total</b>
                  </td>
                  <td className="num">
                    <b>{money(report.total_balance)}</b>
                  </td>
                  <td className="num">{money(report.buckets.not_due)}</td>
                  <td className="num">{money(report.buckets.age_0_30)}</td>
                  <td className="num">{money(report.buckets.age_31_60)}</td>
                  <td className="num">{money(report.buckets.age_61_90)}</td>
                  <td className="num">{money(report.buckets.age_over_90)}</td>
                  <td className="num">
                    <b>{money(report.total_overdue)}</b>
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
          <p className="muted">
            Soldul contului 221 în contabilitate: {money(report.ledger_balance)}
            {Math.abs(diff) > 0.005 ? ` (diferență față de facturi: ${money(diff)} — operațiuni pe 221 făcute în afara facturilor)` : " — coincide cu facturile."}
          </p>
          {open && (
            <>
              <h3>Facturi deschise: {open.name}</h3>
              {open.unallocated_receipts !== "0.00" && Number(open.unallocated_receipts) > 0 && (
                <p className="muted">Avans / încasări peste facturi: {money(open.unallocated_receipts)}</p>
              )}
              <table className="grid">
                <thead>
                  <tr>
                    <th>Factura</th>
                    <th>Data</th>
                    <th>Scadența</th>
                    <th className="num">Vechime (zile)</th>
                    <th className="num">Întârziere (zile)</th>
                    <th className="num">Valoare (MDL)</th>
                    <th className="num">De încasat (MDL)</th>
                  </tr>
                </thead>
                <tbody>
                  {open.invoices.map((i) => (
                    <tr key={i.document_id}>
                      <td>
                        <button className="link" onClick={() => openTab({ id: `sales:${i.document_id}`, title: `Factură emisă ${i.number}`, kind: "sales-invoice", params: { documentId: i.document_id } })}>
                          {i.number}
                        </button>
                      </td>
                      <td>{day(i.doc_date)}</td>
                      <td>{day(i.due_date)}</td>
                      <td className="num">{i.age_days}</td>
                      <td className="num">{i.overdue_days}</td>
                      <td className="num">{money(i.gross_mdl)}</td>
                      <td className="num">
                        <b>{money(i.open_mdl)}</b>
                      </td>
                    </tr>
                  ))}
                  {open.invoices.length === 0 && (
                    <tr>
                      <td colSpan={7} className="muted">
                        Nicio factură deschisă.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}
