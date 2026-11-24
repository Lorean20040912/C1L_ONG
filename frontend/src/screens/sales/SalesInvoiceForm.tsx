import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { InvoiceReceipt, SalesInvoice, SalesLine, SalesMeta, Settlements } from "../../api/sales";
import type { TreasuryDoc } from "../../api/treasury";
import type { Counterparty } from "../../api/types";
import { useCatalogs } from "../../catalog/useCatalogs";
import { notifyDocumentsChanged } from "../../lib/events";
import { day, money, parseAmount, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { CounterpartyField } from "../CounterpartyField";
import { Messages } from "../admin/Messages";
import { printSalesInvoice } from "./printSalesInvoice";

const emptyLine = (): SalesLine => ({ description: "", unit: null, quantity: null, unit_price: null, amount: "", vat_rate: "0", revenue_type: "economic", account_id: null, grant_id: null });
const num = (v: string | null | undefined) => (v === null || v === undefined || v === "" ? 0 : Number(String(v).replace(",", ".")));
const round2 = (n: number) => Math.round((n + Number.EPSILON) * 100) / 100;

/** Factura emisă / nota de stornare: rânduri cu cotă TVA, valută cu curs BNM, înregistrare, încasări legate, tipărire. */
export function SalesInvoiceForm({ tabId, documentId: initialId }: { tabId: string; documentId?: string }) {
  const { orgId, role, openTab, closeTab, updateTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const base = `/organizations/${orgId}/sales`;
  const [documentId, setDocumentId] = useState(initialId);
  const [currentTab, setCurrentTab] = useState(tabId);
  const [inv, setInv] = useState<SalesInvoice | null>(null);
  const [meta, setMeta] = useState<SalesMeta | null>(null);
  const [series, setSeries] = useState("");
  const [number, setNumber] = useState("");
  const [docDate, setDocDate] = useState(today());
  const [dueDate, setDueDate] = useState("");
  const [clientId, setClientId] = useState("");
  const [currency, setCurrency] = useState("MDL");
  const [rate, setRate] = useState("");
  const [notes, setNotes] = useState("");
  const [rows, setRows] = useState<SalesLine[]>([emptyLine()]);
  const [version, setVersion] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [extraCp, setExtraCp] = useState<Counterparty[]>([]);
  const [receipts, setReceipts] = useState<InvoiceReceipt[]>([]);
  const [rcpt, setRcpt] = useState<{ kind: "bank_receipt" | "cash_receipt"; bank: string; date: string; amount: string; rate: string } | null>(null);
  const [existing, setExisting] = useState<TreasuryDoc[]>([]);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const posted = !!inv?.is_posted;
  const cancelled = inv?.status === "cancelled";
  const credit = inv?.kind === "credit_note";
  const ro = posted || cancelled || busy || !editable;
  const touch = () => setDirty(true);

  const fill = useCallback((i: SalesInvoice) => {
    setInv(i);
    setSeries(i.series);
    setNumber(i.number);
    setDocDate(i.doc_date ?? today());
    setDueDate(i.due_date ?? "");
    setClientId(i.counterparty_id ?? "");
    setCurrency(i.currency ?? "MDL");
    setRate(i.exchange_rate ?? "");
    setNotes(i.notes ?? "");
    setRows(i.lines.map((l) => ({ ...l, quantity: l.quantity, unit_price: l.unit_price })));
    setVersion(i.version);
    setDirty(false);
  }, []);

  const loadReceipts = useCallback(
    (id: string) => api<InvoiceReceipt[]>(`${base}/invoices/${id}/receipts`).then(setReceipts, () => {}),
    [base],
  );

  useEffect(() => {
    api<SalesMeta>(`${base}/meta?on_date=${docDate}`).then(setMeta, () => {});
  }, [base, docDate]);
  useEffect(() => {
    if (!initialId) return;
    api<SalesInvoice>(`${base}/invoices/${initialId}`).then((i) => {
      fill(i);
      loadReceipts(initialId);
    }, (e: Error) => setError(e.message));
  }, [base, initialId, fill, loadReceipts, setError]);

  const totals = useMemo(() => {
    let net = 0;
    let vat = 0;
    for (const r of rows) {
      const a = num(r.amount) || (r.quantity && r.unit_price ? round2(num(r.quantity) * num(r.unit_price)) : 0);
      net += a;
      vat += round2((a * num(r.vat_rate)) / 100);
    }
    return { net: round2(net), vat: round2(vat), gross: round2(net + vat) };
  }, [rows]);

  const setRow = (i: number, patch: Partial<SalesLine>) => {
    touch();
    setRows((rs) =>
      rs.map((r, k) => {
        if (k !== i) return r;
        const next = { ...r, ...patch };
        if (("quantity" in patch || "unit_price" in patch) && next.quantity && next.unit_price) next.amount = round2(num(next.quantity) * num(next.unit_price)).toFixed(2);
        return next;
      }),
    );
  };

  const body = () => ({
    series: series.trim(),
    number: number.trim() || null,
    doc_date: docDate,
    due_date: dueDate || null,
    counterparty_id: clientId,
    currency,
    exchange_rate: currency === "MDL" ? null : rate || null,
    notes: notes.trim() || null,
    version,
    lines: rows.map((r, i) => {
      const amount = r.amount ? parseAmount(String(r.amount)) : null;
      if (!r.description.trim()) throw new Error(`Rândul ${i + 1}: completați denumirea`);
      if (!amount && !(r.quantity && r.unit_price)) throw new Error(`Rândul ${i + 1}: indicați suma sau cantitatea și prețul`);
      return {
        description: r.description.trim(),
        unit: r.unit || null,
        quantity: r.quantity || null,
        unit_price: r.unit_price || null,
        amount,
        vat_rate: r.vat_rate || "0",
        revenue_type: r.revenue_type,
        account_id: r.account_id || null,
        grant_id: r.grant_id || null,
      };
    }),
  });

  async function save(): Promise<string> {
    if (!clientId) throw new Error("Alegeți clientul");
    const payload = body();
    const saved = documentId
      ? await api<SalesInvoice>(`${base}/invoices/${documentId}`, { method: "PUT", body: payload })
      : await api<SalesInvoice>(`${base}/invoices`, { method: "POST", body: payload });
    fill(saved);
    const id = `sales:${saved.document_id}`;
    if (!documentId) {
      updateTab(currentTab, { id, params: { documentId: saved.document_id } });
      setCurrentTab(id);
      setDocumentId(saved.document_id);
    }
    updateTab(documentId ? currentTab : id, { title: `${saved.kind_label} ${saved.series} ${saved.number}`.replace("  ", " ") });
    notifyDocumentsChanged("sales");
    return saved.document_id;
  }

  const reload = async (id: string) => {
    fill(await api<SalesInvoice>(`${base}/invoices/${id}`));
    await loadReceipts(id);
    notifyDocumentsChanged("sales");
  };

  const onSave = () => run(async () => (await save(), "Salvat."));
  const onPost = (close: boolean) =>
    run(async () => {
      const id = dirty || !documentId ? await save() : documentId;
      await api(`${base}/invoices/${id}/post`, { method: "POST" });
      await reload(id);
      if (close) closeTab(`sales:${id}`, { force: true });
      return "Înregistrat.";
    });
  const onUnpost = () =>
    run(async () => {
      await api(`${base}/invoices/${documentId}/unpost`, { method: "POST" });
      await reload(documentId!);
      return "Înregistrarea a fost anulată; factura se poate modifica.";
    });
  const onCancel = () =>
    run(async () => {
      const reason = window.prompt("Motivul anulării facturii (rămâne în registru, numărul nu se reutilizează):");
      if (!reason || reason.trim().length < 3) return;
      fill(await api<SalesInvoice>(`${base}/invoices/${documentId}/cancel`, { method: "POST", body: { reason: reason.trim() } }));
      notifyDocumentsChanged("sales");
      return "Factura a fost anulată.";
    });
  const onCredit = () =>
    run(async () => {
      const d = window.prompt("Data notei de stornare (AAAA-LL-ZZ):", today());
      if (!d) return;
      const note = await api<SalesInvoice>(`${base}/invoices/${documentId}/credit-note`, { method: "POST", body: { doc_date: d } });
      notifyDocumentsChanged("sales");
      openTab({ id: `sales:${note.document_id}`, title: `Notă de stornare ${note.series} ${note.number}`.replace("  ", " "), kind: "sales-invoice", params: { documentId: note.document_id } });
      return "Nota de stornare a fost creată (neînregistrată).";
    });
  const onDtKt = () =>
    run(async () => {
      const id = dirty || !documentId ? await save() : documentId;
      openTab({ id: `dtkt:${id}`, title: `Dt/Kt: ${number}`, kind: "dtkt", params: { route: "sales/invoices", documentId: id } });
    });
  const onPrint = () =>
    run(async () => {
      if (!inv) throw new Error("Salvați întâi factura");
      if (!printSalesInvoice(inv)) throw new Error("Fereastra de tipărire a fost blocată de browser");
    });
  const fetchRate = () =>
    run(async () => {
      if (currency === "MDL") return;
      const r = await api<{ rate: string }>(`/organizations/${orgId}/exchange-rates/on?currency=${currency}&on=${docDate}`);
      setRate(r.rate);
      touch();
    });

  // ── încasări ──
  const balance = inv ? num(inv.balance) : 0;
  const startReceipt = () => {
    setRcpt({ kind: "bank_receipt", bank: "", date: today(), amount: balance.toFixed(2), rate: "" });
    api<TreasuryDoc[]>(`/organizations/${orgId}/treasury/docs?kind=bank_receipt&posted=false${clientId ? `&counterparty_id=${clientId}` : ""}`).then(
      (a) => api<TreasuryDoc[]>(`/organizations/${orgId}/treasury/docs?kind=cash_receipt&posted=false&counterparty_id=${clientId}`).then((b) => setExisting([...a, ...b].filter((d) => d.operation === "customer"))),
      () => {},
    );
  };
  const banks = catalogs.bankAccounts.filter((b) => b.currency === currency);
  const registerReceipt = () =>
    run(async () => {
      if (!rcpt || !inv) return;
      const amount = parseAmount(rcpt.amount);
      if (!amount) throw new Error("Suma încasării nu e validă");
      if (num(amount) > balance + 0.0001) throw new Error(`Se poate încasa cel mult ${money(balance)}`);
      if (rcpt.kind === "bank_receipt" && !rcpt.bank) throw new Error("Alegeți contul bancar");
      const bank = banks.find((b) => b.id === rcpt.bank);
      const doc = await api<TreasuryDoc>(`/organizations/${orgId}/treasury/docs`, {
        method: "POST",
        body: {
          kind: rcpt.kind,
          operation: "customer",
          doc_date: rcpt.date,
          amount,
          bank_account_id: rcpt.kind === "bank_receipt" ? rcpt.bank : null,
          exchange_rate: bank && bank.currency !== "MDL" ? rcpt.rate || inv.exchange_rate : null,
          counterparty_id: inv.counterparty_id,
          purpose: `Plata facturii ${inv.series} ${inv.number}`.replace("  ", " "),
        },
      });
      await api(`${base}/receipts/${doc.document_id}/settlements`, { method: "PUT", body: { items: [{ invoice_id: inv.id, amount }] } });
      await api(`/organizations/${orgId}/treasury/docs/${doc.document_id}/post`, { method: "POST" });
      notifyDocumentsChanged("treasury");
      setRcpt(null);
      await reload(documentId!);
      return "Încasarea a fost înregistrată și legată de factură.";
    });
  const linkExisting = (d: TreasuryDoc) =>
    run(async () => {
      if (!inv) return;
      const cur = await api<Settlements>(`${base}/receipts/${d.document_id}/settlements`);
      const free = num(cur.unallocated);
      const amount = Math.min(free, balance);
      if (amount <= 0) throw new Error("Încasarea nu are sumă nelegată");
      const items = [...cur.items.map((x) => ({ invoice_id: x.invoice_id, amount: x.amount })), { invoice_id: inv.id, amount: amount.toFixed(2) }];
      await api(`${base}/receipts/${d.document_id}/settlements`, { method: "PUT", body: { items } });
      await api(`/organizations/${orgId}/treasury/docs/${d.document_id}/post`, { method: "POST" });
      notifyDocumentsChanged("treasury");
      setRcpt(null);
      await reload(documentId!);
      return `Încasarea ${d.doc_number} a fost legată (${money(amount)}) și înregistrată.`;
    });

  const counterparties = [...catalogs.counterparties, ...extraCp];
  const revenueAccounts = catalogs.accounts.filter((a) => !a.is_group && a.code.startsWith("6"));
  const client = counterparties.find((c) => c.id === clientId);
  const vatRates = meta?.vat_rates ?? ["0.00"];
  const title = credit ? "Notă de stornare" : "Factură emisă";

  return (
    <div
      onKeyDown={(e) => {
        if (e.ctrlKey && e.key === "Enter") {
          e.preventDefault();
          if (!ro) onPost(true);
        } else if (e.ctrlKey && e.key.toLowerCase() === "s") {
          e.preventDefault();
          if (!ro) onSave();
        }
      }}
    >
      <h1>
        {title} {documentId ? `${series} ${number} din ${day(docDate)}` : "(nouă)"}
        {posted && <span className="badge ok">înregistrată</span>}
        {cancelled && <span className="badge">anulată</span>}
      </h1>
      <div className="bar">
        {editable && !posted && !cancelled && (
          <>
            <button className="b primary" onClick={() => onPost(true)} disabled={busy}>
              Înregistrează și închide
            </button>
            <button className="b" onClick={() => onPost(false)} disabled={busy}>
              Înregistrează
            </button>
            <button className="b" onClick={onSave} disabled={busy}>
              Salvează
            </button>
          </>
        )}
        {editable && posted && (
          <button className="b" onClick={onUnpost} disabled={busy}>
            Anulează înregistrarea
          </button>
        )}
        {editable && documentId && !cancelled && (
          <button className="b" onClick={onCancel} disabled={busy}>
            Anulează factura
          </button>
        )}
        {editable && posted && !credit && !cancelled && (
          <button className="b" onClick={onCredit} disabled={busy}>
            Stornează
          </button>
        )}
        <button className="b" onClick={onDtKt} disabled={busy || !editable}>
          Dt/Kt
        </button>
        <button className="b" onClick={onPrint} disabled={busy || !inv}>
          Tipărește
        </button>
      </div>
      <Messages error={error} info={info} />
      {cancelled && <div className="hint warn">Factura este anulată{inv?.cancel_reason ? `: ${inv.cancel_reason}` : ""}. Numărul rămâne în registru.</div>}
      {credit && inv?.storno_number && <div className="hint">Stornează factura {inv.storno_number}.</div>}
      {meta && !meta.vat_payer && <div className="hint">Organizația nu este plătitoare de TVA la data facturii: se poate folosi doar cota 0%.</div>}

      <div className="form">
        <label htmlFor={`${tabId}-nr`}>Număr</label>
        <div className="pair">
          <input aria-label="Seria" placeholder="Seria" value={series} disabled={ro || !!posted} onChange={(e) => (touch(), setSeries(e.target.value))} style={{ width: 70 }} />
          <input id={`${tabId}-nr`} placeholder={meta ? `automat: ${meta.next_number}` : ""} value={number} disabled={ro} onChange={(e) => (touch(), setNumber(e.target.value))} />
        </div>
        <label htmlFor={`${tabId}-date`}>Data</label>
        <input id={`${tabId}-date`} type="date" value={docDate} disabled={ro} onChange={(e) => (touch(), setDocDate(e.target.value))} />
        <label htmlFor={`${tabId}-due`}>Scadența</label>
        <input id={`${tabId}-due`} type="date" value={dueDate} disabled={ro} onChange={(e) => (touch(), setDueDate(e.target.value))} />
        <label htmlFor={`${tabId}-cp`}>Client</label>
        <div>
          <CounterpartyField
            id={`${tabId}-cp`}
            value={clientId}
            options={counterparties}
            disabled={ro || credit}
            onChange={(id) => (touch(), setClientId(id))}
            onCreated={(cp) => (setExtraCp((x) => [...x, cp]), touch(), setClientId(cp.id))}
          />
          {client && !client.idno && <span className="error">Clientul nu are IDNO — completați-l în Contrapartide.</span>}
        </div>
        <label htmlFor={`${tabId}-cur`}>Valuta și cursul</label>
        <div className="pair">
          <select id={`${tabId}-cur`} value={currency} disabled={ro || credit} onChange={(e) => (touch(), setCurrency(e.target.value))}>
            {["MDL", "EUR", "USD", "RON"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          {currency !== "MDL" && (
            <>
              <input aria-label="Curs BNM" placeholder="curs BNM" value={rate} disabled={ro || credit} onChange={(e) => (touch(), setRate(e.target.value))} style={{ width: 100 }} />
              {!ro && !credit && (
                <button className="b" type="button" onClick={fetchRate}>
                  Curs BNM
                </button>
              )}
            </>
          )}
        </div>
        <label htmlFor={`${tabId}-notes`}>Mențiuni</label>
        <input id={`${tabId}-notes`} value={notes} disabled={ro} onChange={(e) => (touch(), setNotes(e.target.value))} />
      </div>

      <div className="inner-tabs">
        <span className="on">Rânduri ({rows.length})</span>
      </div>
      {!ro && (
        <div className="bar">
          <button className="b" onClick={() => (touch(), setRows((r) => [...r, emptyLine()]))}>
            Adaugă
          </button>
        </div>
      )}
      <div className="table-scroll">
        <table className="grid edit">
          <thead>
            <tr>
              <th>#</th>
              <th>Denumirea</th>
              <th>U.M.</th>
              <th className="num">Cantitatea</th>
              <th className="num">Prețul</th>
              <th className="num">Suma fără TVA</th>
              <th>Cota TVA</th>
              <th className="num">TVA</th>
              <th>Tip venit</th>
              <th>Cont venit</th>
              <th>Proiect</th>
              {!ro && <th />}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const a = num(r.amount);
              return (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>
                    <input aria-label={`Denumirea, rândul ${i + 1}`} value={r.description} disabled={ro} onChange={(e) => setRow(i, { description: e.target.value })} />
                  </td>
                  <td>
                    <input aria-label="U.M." value={r.unit ?? ""} disabled={ro} onChange={(e) => setRow(i, { unit: e.target.value })} style={{ width: 54 }} />
                  </td>
                  <td>
                    <input className="num" aria-label="Cantitatea" value={r.quantity ?? ""} disabled={ro} onChange={(e) => setRow(i, { quantity: e.target.value || null })} style={{ width: 80 }} />
                  </td>
                  <td>
                    <input className="num" aria-label="Prețul" value={r.unit_price ?? ""} disabled={ro} onChange={(e) => setRow(i, { unit_price: e.target.value || null })} style={{ width: 90 }} />
                  </td>
                  <td>
                    <input className="num" aria-label="Suma fără TVA" value={r.amount} disabled={ro} onChange={(e) => setRow(i, { amount: e.target.value })} style={{ width: 110 }} />
                  </td>
                  <td>
                    <select aria-label="Cota TVA" value={Number(r.vat_rate).toFixed(2)} disabled={ro} onChange={(e) => setRow(i, { vat_rate: e.target.value })}>
                      {vatRates.map((v) => (
                        <option key={v} value={Number(v).toFixed(2)}>
                          {Number(v)}%
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="num">{money(round2((a * num(r.vat_rate)) / 100))}</td>
                  <td>
                    <select aria-label="Tip venit" value={r.revenue_type} disabled={ro} onChange={(e) => setRow(i, { revenue_type: e.target.value })}>
                      {Object.entries(meta?.revenue_types ?? { economic: "Activitate economică (618)", organization: "Venituri ale organizației (617)" }).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select aria-label="Cont venit" value={r.account_id ?? ""} disabled={ro} onChange={(e) => setRow(i, { account_id: e.target.value || null })}>
                      <option value="">din regulă</option>
                      {revenueAccounts.map((ac) => (
                        <option key={ac.id} value={ac.id}>
                          {ac.code} {ac.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select aria-label="Proiect" value={r.grant_id ?? ""} disabled={ro} onChange={(e) => setRow(i, { grant_id: e.target.value || null })}>
                      <option value="">—</option>
                      {catalogs.grants.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.code}
                        </option>
                      ))}
                    </select>
                  </td>
                  {!ro && (
                    <td>
                      <button className="b" aria-label={`Șterge rândul ${i + 1}`} onClick={() => (touch(), setRows((rs) => (rs.length > 1 ? rs.filter((_, k) => k !== i) : rs)))}>
                        ✕
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={5}>
                <b>Total {currency !== "MDL" ? `(${currency})` : ""}</b>
              </td>
              <td className="num">
                <b>{money(totals.net)}</b>
              </td>
              <td />
              <td className="num">
                <b>{money(totals.vat)}</b>
              </td>
              <td colSpan={4}>
                <b>De plată: {money(totals.gross)}</b>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      {documentId && !credit && posted && !cancelled && (
        <>
          <div className="inner-tabs">
            <span className="on">Încasări</span>
          </div>
          <p>
            Total {money(inv?.gross)} · stornat {money(inv?.credited)} · încasat {money(inv?.paid)} · <b>de încasat {money(inv?.balance)}</b> {inv?.currency}
          </p>
          {receipts.length > 0 && (
            <table className="grid">
              <thead>
                <tr>
                  <th>Încasarea</th>
                  <th>Data</th>
                  <th className="num">Suma legată</th>
                  <th>Starea</th>
                </tr>
              </thead>
              <tbody>
                {receipts.map((r) => (
                  <tr key={r.receipt_document_id}>
                    <td>{r.doc_number}</td>
                    <td>{day(r.doc_date)}</td>
                    <td className="num">{money(r.amount)}</td>
                    <td>{r.is_posted ? "înregistrată" : "neînregistrată"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {editable && balance > 0 && !rcpt && (
            <button className="b" onClick={startReceipt}>
              Înregistrează încasare
            </button>
          )}
          {rcpt && (
            <div className="card inline-form">
              <select aria-label="Felul încasării" value={rcpt.kind} onChange={(e) => setRcpt({ ...rcpt, kind: e.target.value as "bank_receipt" | "cash_receipt" })}>
                <option value="bank_receipt">Pe cont bancar</option>
                {currency === "MDL" && <option value="cash_receipt">În numerar (casă)</option>}
              </select>
              {rcpt.kind === "bank_receipt" && (
                <select aria-label="Contul bancar" value={rcpt.bank} onChange={(e) => setRcpt({ ...rcpt, bank: e.target.value })}>
                  <option value="">— cont bancar ({currency}) —</option>
                  {banks.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.bank_name ?? "Bancă"} {b.iban.slice(-8)}
                    </option>
                  ))}
                </select>
              )}
              <input type="date" aria-label="Data încasării" value={rcpt.date} onChange={(e) => setRcpt({ ...rcpt, date: e.target.value })} />
              <input aria-label="Suma încasată" value={rcpt.amount} onChange={(e) => setRcpt({ ...rcpt, amount: e.target.value })} style={{ width: 110 }} />
              {currency !== "MDL" && <input aria-label="Cursul BNM la încasare" placeholder="curs BNM" value={rcpt.rate} onChange={(e) => setRcpt({ ...rcpt, rate: e.target.value })} style={{ width: 90 }} />}
              <button className="b primary" onClick={registerReceipt} disabled={busy}>
                Creează și înregistrează
              </button>
              <button className="b" onClick={() => setRcpt(null)}>
                Renunță
              </button>
              {existing.length > 0 && (
                <div>
                  <span className="muted">Sau legați o încasare existentă a clientului:</span>
                  {existing.map((d) => (
                    <button key={d.document_id} className="b" onClick={() => linkExisting(d)} disabled={busy}>
                      {d.doc_number} · {money(d.amount)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
      <p className="footer-note">
        <span className="kbd">Ctrl+Enter</span> înregistrează · <span className="kbd">Ctrl+S</span> salvează
      </p>
    </div>
  );
}
