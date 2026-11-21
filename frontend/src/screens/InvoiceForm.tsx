import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { LINE_KIND_LABELS, type BudgetWarning, type Counterparty, type Invoice, type InvoiceLine, type LineKind } from "../api/types";
import { useCatalogs } from "../catalog/useCatalogs";
import { notifyDocumentsChanged } from "../lib/events";
import { day, money, parseAmount, today } from "../lib/format";
import { newId, useShell } from "../shell/tabs";
import { BudgetLineSelect } from "./BudgetLineSelect";
import { CounterpartyField } from "./CounterpartyField";

interface Row {
  key: number;
  description: string;
  line_kind: LineKind;
  quantity: string;
  unit_price: string;
  amount: string;
  budget_line_id: string;
  account_id: string;
  put_into_use: boolean;
  fixed_asset_id?: string | null;
}

let rowKey = 0;
const emptyRow = (): Row => ({
  key: ++rowKey,
  description: "",
  line_kind: "service",
  quantity: "",
  unit_price: "",
  amount: "",
  budget_line_id: "",
  account_id: "",
  put_into_use: true,
});

const toRow = (l: InvoiceLine): Row => ({
  key: ++rowKey,
  description: l.description,
  line_kind: l.line_kind,
  quantity: l.quantity ? String(Number(l.quantity)) : "",
  unit_price: l.unit_price ? String(Number(l.unit_price)) : "",
  amount: money(l.amount),
  budget_line_id: l.budget_line_id ?? "",
  account_id: l.account_id ?? "",
  put_into_use: l.put_into_use,
  fixed_asset_id: l.fixed_asset_id,
});

const KIND_TAG: Record<LineKind, string> = {
  fixed_asset: "fa",
  low_value_item: "omv",
  material: "mat",
  goods: "mat",
  service: "srv",
};

export function InvoiceForm({ tabId, documentId: initialId }: { tabId: string; documentId?: string }) {
  const { orgId, openTab, closeTab, updateTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [documentId, setDocumentId] = useState(initialId);
  const [currentTab, setCurrentTab] = useState(tabId);
  const [docNumber, setDocNumber] = useState("");
  const [series, setSeries] = useState("");
  const [docDate, setDocDate] = useState(today());
  const [counterpartyId, setCounterpartyId] = useState("");
  const [extraCounterparties, setExtraCounterparties] = useState<Counterparty[]>([]);
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const [version, setVersion] = useState<number | null>(null);
  const [posted, setPosted] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<BudgetWarning[]>([]);

  const base = `/organizations/${orgId}/invoices`;

  const fill = useCallback((inv: Invoice) => {
    setDocNumber(inv.doc_number ?? "");
    setSeries(inv.series ?? "");
    setDocDate(inv.doc_date ?? today());
    setCounterpartyId(inv.counterparty_id ?? "");
    setRows(inv.lines.length ? inv.lines.map(toRow) : [emptyRow()]);
    setVersion(inv.version);
    setPosted(Boolean(inv.is_posted));
    setDirty(false);
  }, []);

  useEffect(() => {
    if (!initialId) return;
    api<Invoice>(`${base}/${initialId}`)
      .then(fill)
      .catch((e: Error) => setError(e.message));
  }, [base, initialId, fill]);

  useEffect(() => {
    updateTab(currentTab, { dirty });
  }, [dirty, currentTab, updateTab]);

  const touch = () => {
    setDirty(true);
    setInfo(null);
  };
  const setRow = (key: number, patch: Partial<Row>) => {
    touch();
    setRows((rs) =>
      rs.map((r) => {
        if (r.key !== key) return r;
        const next = { ...r, ...patch };
        // cantitate × preț → suma (se poate corecta manual)
        if (("quantity" in patch || "unit_price" in patch) && next.quantity && next.unit_price) {
          const q = Number(next.quantity.replace(",", "."));
          const p = Number(next.unit_price.replace(",", "."));
          if (!Number.isNaN(q) && !Number.isNaN(p)) next.amount = money(q * p);
        }
        return next;
      }),
    );
  };

  const total = rows.reduce((s, r) => s + Number(parseAmount(r.amount) ?? 0), 0);

  function body() {
    const lines = rows.filter((r) => r.description.trim() || r.amount.trim());
    if (!docNumber.trim()) throw new Error("Completați numărul facturii");
    if (!counterpartyId) throw new Error("Alegeți furnizorul");
    if (lines.length === 0) throw new Error("Adăugați cel puțin un rând");
    return {
      doc_number: docNumber.trim(),
      series: series.trim() || null,
      doc_date: docDate,
      counterparty_id: counterpartyId,
      version,
      lines: lines.map((r, i) => {
        const amount = parseAmount(r.amount);
        if (!r.description.trim()) throw new Error(`Rândul ${i + 1}: completați denumirea`);
        if (!amount || Number(amount) <= 0) throw new Error(`Rândul ${i + 1}: suma trebuie să fie pozitivă`);
        return {
          description: r.description.trim(),
          line_kind: r.line_kind,
          quantity: r.quantity ? r.quantity.replace(",", ".") : null,
          unit_price: r.unit_price ? r.unit_price.replace(",", ".") : null,
          amount,
          budget_line_id: r.budget_line_id || null,
          account_id: r.account_id || null,
          put_into_use: r.put_into_use,
        };
      }),
    };
  }

  /** Salvează și întoarce id-ul documentului. */
  async function save(): Promise<string> {
    const payload = body();
    const inv = documentId
      ? await api<Invoice>(`${base}/${documentId}`, { method: "PUT", body: payload })
      : await api<Invoice>(base, { method: "POST", body: payload });
    fill(inv);
    if (!documentId) {
      const id = `invoice:${inv.document_id}`;
      updateTab(currentTab, { id, params: { documentId: inv.document_id } });
      setCurrentTab(id);
      setDocumentId(inv.document_id);
    }
    updateTab(documentId ? currentTab : `invoice:${inv.document_id}`, { title: `Factură primită ${inv.doc_number}` });
    notifyDocumentsChanged("invoices");
    return inv.document_id;
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

  const onSave = () =>
    run(async () => {
      await save();
      setInfo("Salvat.");
    });

  const onPost = (close: boolean) =>
    run(async () => {
      const id = dirty || !documentId ? await save() : documentId;
      const result = await api<{ warnings: BudgetWarning[] }>(`${base}/${id}/post`, { method: "POST" });
      fill(await api<Invoice>(`${base}/${id}`));
      notifyDocumentsChanged("invoices");
      setWarnings(result.warnings);
      // cu depășire de buget fila rămâne deschisă, ca avertismentul să fie văzut
      if (close && result.warnings.length === 0) closeTab(`invoice:${id}`, { force: true });
      else setInfo("Înregistrat.");
    });

  const onUnpost = () =>
    run(async () => {
      await api(`${base}/${documentId}/unpost`, { method: "POST" });
      fill(await api<Invoice>(`${base}/${documentId}`));
      notifyDocumentsChanged("invoices");
      setWarnings([]);
      setInfo("Înregistrarea a fost anulată; documentul se poate modifica.");
    });

  const onDtKt = () =>
    run(async () => {
      const id = dirty || !documentId ? await save() : documentId;
      openTab({ id: `dtkt:${id}`, title: `Dt/Kt: ${docNumber}`, kind: "dtkt", params: { route: "invoices", documentId: id } });
    });

  const onPay = () => {
    if (!documentId) return;
    openTab({ id: newId("payment"), title: "Ordin de plată (nou)", kind: "payment", params: { invoiceId: documentId } });
  };

  const counterparties = [...catalogs.counterparties, ...extraCounterparties];
  const accounts = catalogs.accounts.filter((a) => !a.is_group);
  const ro = posted || busy;

  return (
    <div
      onKeyDown={(e) => {
        if (e.ctrlKey && e.key === "Enter") {
          e.preventDefault();
          if (!posted) onPost(true);
        } else if (e.ctrlKey && e.key.toLowerCase() === "s") {
          e.preventDefault();
          if (!posted) onSave();
        }
      }}
    >
      <h1>
        Factură primită {documentId ? `${docNumber} din ${day(docDate)}` : "(nouă)"}
        {posted && <span className="badge ok">înregistrată</span>}
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
            <button className="b" onClick={onSave} disabled={busy}>
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
        <button className="b" onClick={onPay} disabled={!documentId || busy}>
          Plătește
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {info && <div className="hint">{info}</div>}
      {warnings.length > 0 && (
        <div className="hint warn" role="status">
          <b>Depășire de buget:</b>
          {warnings.map((w) => (
            <div key={w.budget_line_id}>
              • {w.label}: cheltuit {money(w.spent)} din {money(w.planned)}, peste buget {money(w.over)}
            </div>
          ))}
          Suma peste buget nu e deductibilă (ONG17). Documentul a fost înregistrat.
        </div>
      )}

      <div className="form">
        <label htmlFor={`${tabId}-nr`}>Număr</label>
        <div className="pair">
          <input id={`${tabId}-series`} aria-label="Seria" placeholder="Seria" value={series} disabled={ro} onChange={(e) => (touch(), setSeries(e.target.value))} style={{ width: 70 }} />
          <input id={`${tabId}-nr`} value={docNumber} disabled={ro} onChange={(e) => (touch(), setDocNumber(e.target.value))} />
        </div>
        <label htmlFor={`${tabId}-date`}>Data</label>
        <input id={`${tabId}-date`} type="date" value={docDate} disabled={ro} onChange={(e) => (touch(), setDocDate(e.target.value))} />
        <label htmlFor={`${tabId}-cp`}>Furnizor</label>
        <CounterpartyField
          id={`${tabId}-cp`}
          value={counterpartyId}
          options={counterparties}
          disabled={ro}
          onChange={(id) => (touch(), setCounterpartyId(id))}
          onCreated={(cp) => {
            setExtraCounterparties((x) => [...x, cp]);
            touch();
            setCounterpartyId(cp.id);
          }}
        />
      </div>

      <div className="inner-tabs">
        <span className="on">Rânduri ({rows.length})</span>
      </div>
      {!posted && (
        <div className="hint">
          O singură factură pentru tot: fiecare rând are <b>tipul</b> lui. Pentru „Mijloc fix” fișa se creează automat la înregistrare, iar
          amortizarea începe din luna următoare. Contul gol = contul din regula de înregistrare.
        </div>
      )}
      {!ro && (
        <div className="bar">
          <button className="b" onClick={() => (touch(), setRows((r) => [...r, emptyRow()]))}>
            Adaugă
          </button>
        </div>
      )}
      <div className="table-scroll">
        <table className="grid edit">
          <thead>
            <tr>
              <th>N</th>
              <th>Denumire</th>
              <th>Tip rând</th>
              <th className="num">Cant.</th>
              <th className="num">Preț</th>
              <th className="num">Suma</th>
              <th>Linie de buget</th>
              <th>Cont</th>
              <th>În exploatare</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.key}>
                <td>{i + 1}</td>
                <td>
                  <input aria-label={`Denumire rând ${i + 1}`} value={r.description} disabled={ro} onChange={(e) => setRow(r.key, { description: e.target.value })} />
                </td>
                <td>
                  {ro ? (
                    <span className={`tag ${KIND_TAG[r.line_kind]}`}>{LINE_KIND_LABELS[r.line_kind]}</span>
                  ) : (
                    <select aria-label={`Tip rând ${i + 1}`} value={r.line_kind} onChange={(e) => setRow(r.key, { line_kind: e.target.value as LineKind })}>
                      {Object.entries(LINE_KIND_LABELS).map(([v, l]) => (
                        <option key={v} value={v}>
                          {l}
                        </option>
                      ))}
                    </select>
                  )}
                </td>
                <td className="num">
                  <input aria-label={`Cantitate rând ${i + 1}`} className="num" value={r.quantity} disabled={ro} onChange={(e) => setRow(r.key, { quantity: e.target.value })} style={{ width: 60 }} />
                </td>
                <td className="num">
                  <input aria-label={`Preț rând ${i + 1}`} className="num" value={r.unit_price} disabled={ro} onChange={(e) => setRow(r.key, { unit_price: e.target.value })} style={{ width: 80 }} />
                </td>
                <td className="num">
                  <input
                    aria-label={`Suma rând ${i + 1}`}
                    className="num"
                    value={r.amount}
                    disabled={ro}
                    onChange={(e) => setRow(r.key, { amount: e.target.value })}
                    onBlur={() => parseAmount(r.amount) && setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, amount: money(parseAmount(x.amount)) } : x)))}
                    style={{ width: 100 }}
                  />
                </td>
                <td>
                  <BudgetLineSelect
                    label={`Linie de buget rând ${i + 1}`}
                    grants={catalogs.grants}
                    value={r.budget_line_id}
                    disabled={ro}
                    onChange={(v) => setRow(r.key, { budget_line_id: v })}
                  />
                </td>
                <td>
                  <select aria-label={`Cont rând ${i + 1}`} value={r.account_id} disabled={ro} onChange={(e) => setRow(r.key, { account_id: e.target.value })}>
                    <option value="">după regulă</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id} title={a.name}>
                        {a.code}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  {(r.line_kind === "fixed_asset" || r.line_kind === "low_value_item") && (
                    <input
                      type="checkbox"
                      aria-label={`Dat în exploatare rând ${i + 1}`}
                      checked={r.put_into_use}
                      disabled={ro}
                      onChange={(e) => setRow(r.key, { put_into_use: e.target.checked })}
                    />
                  )}
                  {r.fixed_asset_id && <span className="ok"> → fișa MF creată</span>}
                </td>
                <td>
                  {!ro && rows.length > 1 && (
                    <button className="x-btn" aria-label={`Șterge rândul ${i + 1}`} onClick={() => (touch(), setRows((rs) => rs.filter((x) => x.key !== r.key)))}>
                      ×
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="totals">
        <span>
          Total: <b>{money(total)}</b> lei
        </span>
      </div>
      <p className="footer-note">
        <span className="kbd">Ctrl+Enter</span> înregistrează și închide · <span className="kbd">Ctrl+S</span> salvează ·{" "}
        <span className="kbd">Esc</span> închide fila
      </p>
    </div>
  );
}
