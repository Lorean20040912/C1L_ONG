import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { PAYMENT_STATE_LABELS, type InvoiceJournal, type InvoiceJournalRow, type InvoiceSettlements, type PaymentSettlements, type SupplierPayment } from "../../api/treasury";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, parseAmount, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";
import { StatusIcon } from "../StatusIcon";

const csvCell = (v: string) => `"${v.replace(/"/g, '""')}"`;

/** Jurnalul facturilor fiscale primite: facturile pe perioadă, cu TVA pe cote și totaluri. */
export function ReceivedInvoices() {
  const { orgId, role, openTab } = useShell();
  const editable = can(role, POSTING_ROLES);
  const act = useAction();
  const [selected, setSelected] = useState<InvoiceJournalRow | null>(null);
  const [detail, setDetail] = useState<InvoiceSettlements | null>(null);
  const [payments, setPayments] = useState<SupplierPayment[]>([]);
  const [linkPay, setLinkPay] = useState("");
  const [linkAmount, setLinkAmount] = useState("");
  const { catalogs } = useCatalogs(orgId);
  const [from, setFrom] = useState(`${today().slice(0, 4)}-01-01`);
  const [to, setTo] = useState(today());
  const [supplier, setSupplier] = useState("");
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const [payState, setPayState] = useState("");
  const [journal, setJournal] = useState<InvoiceJournal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/organizations/${orgId}/treasury/reports/received-invoices`;

  const load = useCallback(() => {
    setError(null);
    if (from && to && from > to) return setError("Data de început e după data de sfârșit");
    const qs = new URLSearchParams();
    if (from) qs.set("date_from", from);
    if (to) qs.set("date_to", to);
    if (supplier) qs.set("counterparty_id", supplier);
    if (state) qs.set("posted", state === "posted" ? "true" : "false");
    if (q.trim()) qs.set("q", q.trim());
    if (payState) qs.set("payment_status", payState);
    api<InvoiceJournal>(`${base}?${qs}`).then(setJournal, (e: Error) => setError(e.message));
  }, [base, from, to, supplier, state, q, payState]);
  useEffect(load, [load]);

  const tbase = `/organizations/${orgId}/treasury`;
  const pick = (r: InvoiceJournalRow) => {
    setSelected(r);
    setDetail(null);
    setLinkPay("");
    setLinkAmount("");
    api<InvoiceSettlements>(`${tbase}/invoices/${r.document_id}/settlements`).then(setDetail, (e: Error) => setError(e.message));
    if (r.counterparty_id) api<SupplierPayment[]>(`${tbase}/settlements/payments?counterparty_id=${r.counterparty_id}`).then(setPayments, () => setPayments([]));
  };
  const refresh = () => {
    load();
    if (selected) pick(selected);
  };
  const autoSettle = () =>
    act.run(async () => {
      const out = await api<{ payments: number; invoices: number; amount: string }>(`${tbase}/settlements/auto`, { method: "POST", body: { counterparty_id: supplier || null } });
      refresh();
      return out.payments ? `Stins automat: ${money(out.amount)} pe ${out.invoices} facturi din ${out.payments} plăți.` : "Nu sunt plăți înregistrate nelegate de facturi.";
    });
  // legarea / dezlegarea se face pe plată: se citesc stingerile ei, se modifică lista și se trimite întreagă
  const changeLink = (paymentId: string, mutate: (items: { invoice_document_id: string; amount: string }[]) => { invoice_document_id: string; amount: string }[], msg: string) =>
    act.run(async () => {
      const cur = await api<PaymentSettlements>(`${tbase}/payments/${paymentId}/settlements`);
      await api(`${tbase}/payments/${paymentId}/settlements`, { method: "PUT", body: { items: mutate(cur.items) } });
      refresh();
      return msg;
    });
  const link = () => {
    const amount = parseAmount(linkAmount);
    if (!selected || !linkPay || amount === null || Number(amount) <= 0) return act.setError("Alegeți plata și suma stingerii");
    return changeLink(linkPay, (items) => [...items.filter((i) => i.invoice_document_id !== selected.document_id), { invoice_document_id: selected.document_id, amount }], "Plata a fost legată de factură.");
  };

  const open = (r: InvoiceJournalRow) => openTab({ id: `invoice:${r.document_id}`, title: `Factura ${r.series ?? ""}${r.doc_number ?? ""}`, kind: "invoice", params: { documentId: r.document_id } });
  const exportCsv = () => {
    if (!journal) return;
    const head = ["Data", "Seria", "Număr", "Furnizor", "IDNO", "Cod TVA", "Total", "Fără TVA", "TVA", "Achitat", "Rest", "Starea plății", "Înregistrată"];
    const rows = journal.rows.map((r) => [day(r.doc_date), r.series ?? "", r.doc_number ?? "", r.counterparty_name ?? "", r.idno ?? "", r.vat_code ?? "", r.total, r.net, r.vat, r.paid, r.remaining, PAYMENT_STATE_LABELS[r.payment_status], r.is_posted ? "da" : "nu"]);
    const blob = new Blob(["﻿" + [head, ...rows].map((l) => l.map(csvCell).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `facturi-fiscale-primite-${to || "toate"}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div>
      <h1>Facturi fiscale primite</h1>
      <div className="bar">
        <label>
          De la <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          Până la <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <select aria-label="Furnizor" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
          <option value="">Toți furnizorii</option>
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
        </select>
        <select aria-label="Starea plății" value={payState} onChange={(e) => setPayState(e.target.value)}>
          <option value="">Toate plățile</option>
          <option value="unpaid">Neachitate</option>
          <option value="partial">Parțial achitate</option>
          <option value="paid">Achitate</option>
        </select>
        <input aria-label="Căutare" placeholder="Serie, număr, furnizor…" value={q} onChange={(e) => setQ(e.target.value)} />
        {editable && (
          <button className="b" onClick={autoSettle} disabled={act.busy} title="Plățile înregistrate către furnizori sting cele mai vechi facturi">
            Stinge automat
          </button>
        )}
        <button className="b" onClick={exportCsv} disabled={!journal || journal.rows.length === 0}>
          Export CSV
        </button>
      </div>
      <Messages error={error ?? act.error} info={act.info} />
      {!journal && !error && <p className="muted">Se încarcă…</p>}
      {journal && (
        <>
          <table className="grid">
            <thead>
              <tr>
                <th style={{ width: 24 }} />
                <th>Data</th>
                <th>Seria, nr.</th>
                <th>Furnizor</th>
                <th>IDNO</th>
                <th>Cod TVA</th>
                <th>e-Factura</th>
                <th className="num">Total</th>
                <th className="num">Fără TVA</th>
                <th className="num">TVA</th>
                <th className="num">Achitat</th>
                <th className="num">Rest</th>
                <th>Plata</th>
              </tr>
            </thead>
            <tbody>
              {journal.rows.map((r) => (
                <tr key={r.document_id} tabIndex={0} className={selected?.document_id === r.document_id ? "sel" : ""} onClick={() => pick(r)} onDoubleClick={() => open(r)} onKeyDown={(e) => e.key === "Enter" && open(r)}>
                  <td>
                    <StatusIcon posted={r.is_posted} />
                  </td>
                  <td>{day(r.doc_date)}</td>
                  <td>
                    {r.series ?? ""} {r.doc_number}
                  </td>
                  <td>{r.counterparty_name}</td>
                  <td>{r.idno}</td>
                  <td>{r.vat_code}</td>
                  <td>{r.e_invoice_id}</td>
                  <td className="num">{money(r.total)}</td>
                  <td className="num">{money(r.net)}</td>
                  <td className="num">{money(r.vat)}</td>
                  <td className="num">{money(r.paid)}</td>
                  <td className="num">{money(r.remaining)}</td>
                  <td className={r.payment_status === "paid" ? "" : r.payment_status === "partial" ? "muted" : "late"}>{PAYMENT_STATE_LABELS[r.payment_status]}</td>
                </tr>
              ))}
              {journal.rows.length === 0 && (
                <tr>
                  <td colSpan={13} className="muted">
                    Nu sunt facturi pentru filtrele alese.
                  </td>
                </tr>
              )}
            </tbody>
            {journal.rows.length > 0 && (
              <tfoot>
                <tr>
                  <td colSpan={7}>
                    <b>Total ({journal.rows.length})</b>
                  </td>
                  <td className="num">
                    <b>{money(journal.total)}</b>
                  </td>
                  <td className="num">{money(journal.net)}</td>
                  <td className="num">{money(journal.vat)}</td>
                  <td className="num">{money(journal.paid)}</td>
                  <td className="num">{money(journal.remaining)}</td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
          {selected && (
            <section>
              <h2>
                Plățile facturii {selected.series ?? ""}
                {selected.doc_number}
              </h2>
              {!detail && <p className="muted">Se încarcă…</p>}
              {detail && (
                <>
                  <p>
                    Total {money(detail.total)} · achitat {money(detail.paid)} · rest <b>{money(detail.remaining)}</b> — {PAYMENT_STATE_LABELS[detail.payment_status]}
                  </p>
                  <table className="grid" style={{ maxWidth: 640 }}>
                    <thead>
                      <tr>
                        <th>Plata</th>
                        <th>Data</th>
                        <th>Stare</th>
                        <th className="num">Stinge</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {detail.payments.map((p) => (
                        <tr key={p.payment_document_id}>
                          <td>{p.doc_number}</td>
                          <td>{day(p.doc_date)}</td>
                          <td>{p.is_posted ? "înregistrată" : "neînregistrată (nu se numără)"}</td>
                          <td className="num">{money(p.amount)}</td>
                          <td>
                            {editable && (
                              <button className="b" disabled={act.busy} onClick={() => changeLink(p.payment_document_id, (items) => items.filter((i) => i.invoice_document_id !== selected.document_id), "Legătura a fost ștearsă.")}>
                                Dezleagă
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                      {detail.payments.length === 0 && (
                        <tr>
                          <td colSpan={5} className="muted">
                            Factura nu e legată de nicio plată.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  {editable && Number(detail.remaining) > 0 && (
                    <div className="bar">
                      <select
                        aria-label="Plata de legat"
                        value={linkPay}
                        onChange={(e) => {
                          setLinkPay(e.target.value);
                          const p = payments.find((x) => x.payment_document_id === e.target.value);
                          if (p) setLinkAmount(money(Math.min(Number(p.free), Number(detail.remaining))));
                        }}
                      >
                        <option value="">— alegeți plata către furnizor —</option>
                        {payments
                          .filter((p) => Number(p.free) > 0)
                          .map((p) => (
                            <option key={p.payment_document_id} value={p.payment_document_id}>
                              {p.doc_number} din {day(p.doc_date)} — liber {money(p.free)}
                              {p.is_posted ? "" : " (neînregistrată)"}
                            </option>
                          ))}
                      </select>
                      <input aria-label="Suma stinsă" className="num" inputMode="decimal" value={linkAmount} onChange={(e) => setLinkAmount(e.target.value)} />
                      <button className="b primary" disabled={act.busy} onClick={link}>
                        Leagă plata
                      </button>
                    </div>
                  )}
                </>
              )}
            </section>
          )}
          {journal.by_rate.length > 0 && (
            <>
              <h2>TVA pe cote</h2>
              <table className="grid" style={{ maxWidth: 420 }}>
                <thead>
                  <tr>
                    <th>Cota</th>
                    <th className="num">Baza</th>
                    <th className="num">TVA</th>
                  </tr>
                </thead>
                <tbody>
                  {journal.by_rate.map((r) => (
                    <tr key={r.vat_rate}>
                      <td>{Number(r.vat_rate) ? `${Number(r.vat_rate)}%` : "fără TVA"}</td>
                      <td className="num">{money(r.base)}</td>
                      <td className="num">{money(r.vat)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
      <p className="footer-note">Suma rândului facturii include TVA; TVA se extrage din cota indicată pe rând. Clic pe o factură arată plățile care o sting; dublu clic o deschide.</p>
    </div>
  );
}
