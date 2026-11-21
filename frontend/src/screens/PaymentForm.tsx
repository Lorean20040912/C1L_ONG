import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Counterparty, Invoice, InvoiceListItem, PaymentDirection, PaymentOrder } from "../api/types";
import { useCatalogs } from "../catalog/useCatalogs";
import { notifyDocumentsChanged } from "../lib/events";
import { day, money, parseAmount, today } from "../lib/format";
import { useShell } from "../shell/tabs";
import { CounterpartyField } from "./CounterpartyField";

export function PaymentForm({ tabId, documentId: initialId, invoiceId }: { tabId: string; documentId?: string; invoiceId?: string }) {
  const { orgId, openTab, closeTab, updateTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [documentId, setDocumentId] = useState(initialId);
  const [currentTab, setCurrentTab] = useState(tabId);
  const [direction, setDirection] = useState<PaymentDirection>("outgoing");
  const [docNumber, setDocNumber] = useState("");
  const [docDate, setDocDate] = useState(today());
  const [bankAccountId, setBankAccountId] = useState("");
  const [amount, setAmount] = useState("");
  const [rate, setRate] = useState("");
  const [counterpartyId, setCounterpartyId] = useState("");
  const [extraCounterparties, setExtraCounterparties] = useState<Counterparty[]>([]);
  const [invoiceDocId, setInvoiceDocId] = useState(invoiceId ?? "");
  const [purpose, setPurpose] = useState("");
  const [grantId, setGrantId] = useState("");
  const [invoices, setInvoices] = useState<InvoiceListItem[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [posted, setPosted] = useState(false);
  const [dirty, setDirty] = useState(Boolean(invoiceId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const base = `/organizations/${orgId}/payment-orders`;

  const fill = useCallback((p: PaymentOrder) => {
    setDirection(p.direction);
    setDocNumber(p.doc_number ?? "");
    setDocDate(p.doc_date ?? today());
    setBankAccountId(p.bank_account_id ?? "");
    setAmount(money(p.amount));
    setRate(p.exchange_rate ? String(Number(p.exchange_rate)) : "");
    setCounterpartyId(p.counterparty_id ?? "");
    setInvoiceDocId(p.invoice_document_id ?? "");
    setPurpose(p.purpose ?? "");
    setGrantId(p.lines[0]?.grant_id ?? "");
    setVersion(p.version);
    setPosted(Boolean(p.is_posted));
    setDirty(false);
  }, []);

  useEffect(() => {
    if (initialId)
      api<PaymentOrder>(`${base}/${initialId}`)
        .then(fill)
        .catch((e: Error) => setError(e.message));
  }, [base, initialId, fill]);

  useEffect(() => {
    api<InvoiceListItem[]>(`/organizations/${orgId}/invoices`)
      .then(setInvoices)
      .catch(() => setInvoices([]));
  }, [orgId]);

  // „Plătește” din factură: furnizorul, suma și destinația vin din factură
  useEffect(() => {
    if (!invoiceId || initialId) return;
    api<Invoice>(`/organizations/${orgId}/invoices/${invoiceId}`)
      .then((inv) => {
        setCounterpartyId(inv.counterparty_id ?? "");
        setAmount(money(inv.total_amount));
        setPurpose(`Plata facturii ${[inv.series, inv.doc_number].filter(Boolean).join(" ")} din ${day(inv.doc_date)}`);
      })
      .catch((e: Error) => setError(e.message));
  }, [orgId, invoiceId, initialId]);

  // primul cont bancar în moneda națională, implicit
  useEffect(() => {
    if (!bankAccountId && !initialId && catalogs.bankAccounts.length) {
      setBankAccountId((catalogs.bankAccounts.find((b) => b.currency === "MDL") ?? catalogs.bankAccounts[0]).id);
    }
  }, [catalogs.bankAccounts, bankAccountId, initialId]);

  useEffect(() => {
    updateTab(currentTab, { dirty });
  }, [dirty, currentTab, updateTab]);

  const touch = () => {
    setDirty(true);
    setInfo(null);
  };

  const bank = catalogs.bankAccounts.find((b) => b.id === bankAccountId);
  const foreign = bank && bank.currency !== "MDL";

  function body() {
    const value = parseAmount(amount);
    if (!docNumber.trim()) throw new Error("Completați numărul ordinului");
    if (!bankAccountId) throw new Error("Alegeți contul bancar");
    if (!value || Number(value) <= 0) throw new Error("Suma trebuie să fie pozitivă");
    return {
      direction,
      doc_number: docNumber.trim(),
      doc_date: docDate,
      amount: value,
      currency: bank?.currency,
      exchange_rate: foreign && rate ? rate.replace(",", ".") : null,
      purpose: purpose.trim() || null,
      bank_account_id: bankAccountId,
      counterparty_id: counterpartyId || null,
      invoice_document_id: direction === "outgoing" && invoiceDocId ? invoiceDocId : null,
      lines: direction === "incoming" && grantId ? [{ grant_id: grantId, amount: value }] : [],
      version,
    };
  }

  async function save(): Promise<string> {
    const payload = body();
    const p = documentId
      ? await api<PaymentOrder>(`${base}/${documentId}`, { method: "PUT", body: payload })
      : await api<PaymentOrder>(base, { method: "POST", body: payload });
    fill(p);
    const id = `payment:${p.document_id}`;
    if (!documentId) {
      updateTab(currentTab, { id, params: { documentId: p.document_id } });
      setCurrentTab(id);
      setDocumentId(p.document_id);
    }
    updateTab(id, { title: `Ordin de plată ${p.doc_number}` });
    notifyDocumentsChanged("payment-orders");
    return p.document_id;
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const onPost = (close: boolean) =>
    run(async () => {
      const id = dirty || !documentId ? await save() : documentId;
      await api(`${base}/${id}/post`, { method: "POST" });
      fill(await api<PaymentOrder>(`${base}/${id}`));
      notifyDocumentsChanged("payment-orders");
      if (close) closeTab(`payment:${id}`, { force: true });
      else setInfo("Înregistrat.");
    });

  const onUnpost = () =>
    run(async () => {
      await api(`${base}/${documentId}/unpost`, { method: "POST" });
      fill(await api<PaymentOrder>(`${base}/${documentId}`));
      notifyDocumentsChanged("payment-orders");
      setInfo("Înregistrarea a fost anulată; documentul se poate modifica.");
    });

  const onDtKt = () =>
    run(async () => {
      const id = dirty || !documentId ? await save() : documentId;
      openTab({ id: `dtkt:${id}`, title: `Dt/Kt: ordin ${docNumber}`, kind: "dtkt", params: { route: "payment-orders", documentId: id } });
    });

  const ro = posted || busy;
  const supplierInvoices = invoices.filter((i) => !counterpartyId || i.counterparty_id === counterpartyId);

  return (
    <div
      onKeyDown={(e) => {
        if (e.ctrlKey && e.key === "Enter" && !posted) {
          e.preventDefault();
          onPost(true);
        } else if (e.ctrlKey && e.key.toLowerCase() === "s" && !posted) {
          e.preventDefault();
          run(async () => {
            await save();
            setInfo("Salvat.");
          });
        }
      }}
    >
      <h1>
        Ordin de plată {documentId ? `${docNumber} din ${day(docDate)}` : "(nou)"}
        {posted && <span className="badge ok">înregistrat</span>}
      </h1>
      <div className="bar">
        {!posted && (
          <>
            <button className="b primary" onClick={() => onPost(true)} disabled={busy}>
              Înregistrează și închide
            </button>
            <button className="b" onClick={() => onPost(false)} disabled={busy}>
              Înregistrează
            </button>
            <button
              className="b"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await save();
                  setInfo("Salvat.");
                })
              }
            >
              Salvează
            </button>
          </>
        )}
        {posted && (
          <button className="b" onClick={onUnpost} disabled={busy}>
            Anulează înregistrarea
          </button>
        )}
        <button className="b" onClick={onDtKt} disabled={busy}>
          Dt/Kt
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {info && <div className="hint">{info}</div>}
      {catalogs.bankAccounts.length === 0 && <div className="hint">Organizația nu are conturi bancare; adăugați unul în Administrare.</div>}

      <div className="form">
        <label htmlFor={`${tabId}-dir`}>Tipul</label>
        <select id={`${tabId}-dir`} value={direction} disabled={ro} onChange={(e) => (touch(), setDirection(e.target.value as PaymentDirection))}>
          <option value="outgoing">Plată (ieșire din cont)</option>
          <option value="incoming">Încasare pe cont</option>
        </select>
        <label htmlFor={`${tabId}-nr`}>Număr</label>
        <input id={`${tabId}-nr`} value={docNumber} disabled={ro} onChange={(e) => (touch(), setDocNumber(e.target.value))} />

        <label htmlFor={`${tabId}-date`}>Data</label>
        <input id={`${tabId}-date`} type="date" value={docDate} disabled={ro} onChange={(e) => (touch(), setDocDate(e.target.value))} />
        <label htmlFor={`${tabId}-bank`}>Cont bancar</label>
        <select id={`${tabId}-bank`} value={bankAccountId} disabled={ro} onChange={(e) => (touch(), setBankAccountId(e.target.value))}>
          <option value="">— alegeți —</option>
          {catalogs.bankAccounts.map((b) => (
            <option key={b.id} value={b.id}>
              {b.iban} · {b.currency}
              {b.bank_name ? ` · ${b.bank_name}` : ""}
            </option>
          ))}
        </select>

        <label htmlFor={`${tabId}-sum`}>Suma{bank ? `, ${bank.currency}` : ""}</label>
        <input
          id={`${tabId}-sum`}
          className="num"
          value={amount}
          disabled={ro}
          onChange={(e) => (touch(), setAmount(e.target.value))}
          onBlur={() => parseAmount(amount) && setAmount(money(parseAmount(amount)))}
        />
        <label htmlFor={`${tabId}-rate`}>Curs BNM</label>
        <input id={`${tabId}-rate`} className="num" value={rate} disabled={ro || !foreign} placeholder={foreign ? "obligatoriu" : "—"} onChange={(e) => (touch(), setRate(e.target.value))} />

        <label htmlFor={`${tabId}-cp`}>{direction === "outgoing" ? "Beneficiar" : "Plătitor"}</label>
        <CounterpartyField
          id={`${tabId}-cp`}
          value={counterpartyId}
          options={[...catalogs.counterparties, ...extraCounterparties]}
          disabled={ro}
          onChange={(id) => (touch(), setCounterpartyId(id))}
          onCreated={(cp) => {
            setExtraCounterparties((x) => [...x, cp]);
            touch();
            setCounterpartyId(cp.id);
          }}
        />
        {direction === "outgoing" ? (
          <>
            <label htmlFor={`${tabId}-inv`}>Factura achitată</label>
            <select id={`${tabId}-inv`} value={invoiceDocId} disabled={ro} onChange={(e) => (touch(), setInvoiceDocId(e.target.value))}>
              <option value="">—</option>
              {supplierInvoices.map((i) => (
                <option key={i.document_id} value={i.document_id}>
                  {[i.series, i.doc_number].filter(Boolean).join(" ")} din {day(i.doc_date)} · {money(i.total_amount)}
                </option>
              ))}
            </select>
          </>
        ) : (
          <>
            <label htmlFor={`${tabId}-grant`}>Grant (tranșă)</label>
            <select id={`${tabId}-grant`} value={grantId} disabled={ro} onChange={(e) => (touch(), setGrantId(e.target.value))}>
              <option value="">—</option>
              {catalogs.grants.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.code} {g.title}
                </option>
              ))}
            </select>
          </>
        )}

        <label htmlFor={`${tabId}-purpose`}>Destinația plății</label>
        <input
          id={`${tabId}-purpose`}
          className="wide"
          maxLength={210}
          value={purpose}
          disabled={ro}
          onChange={(e) => (touch(), setPurpose(e.target.value))}
        />
      </div>
      <p className="footer-note">
        Destinația: {purpose.length}/210 caractere · <span className="kbd">Ctrl+Enter</span> înregistrează și închide
      </p>
    </div>
  );
}
