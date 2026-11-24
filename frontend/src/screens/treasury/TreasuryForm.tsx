import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Person } from "../../api/payroll";
import type { Counterparty } from "../../api/types";
import type { KindMeta, OpMeta, TreasuryDoc, TreasuryKind, TreasuryLine, TreasuryPostResult } from "../../api/treasury";
import { useCatalogs } from "../../catalog/useCatalogs";
import { notifyDocumentsChanged } from "../../lib/events";
import { day, money, parseAmount, today } from "../../lib/format";
import { printDocument } from "../../lib/printDoc";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { BudgetLineSelect } from "../BudgetLineSelect";
import { CounterpartyField } from "../CounterpartyField";
import { SettlementsPanel } from "./SettlementsPanel";
import { KIND_TITLES } from "./TreasuryList";

const LINE_KINDS: Record<string, string> = { service: "Serviciu", material: "Material", goods: "Marfă", low_value_item: "OMVSD" };
const emptyLine = (): TreasuryLine => ({ description: "", amount: "", line_kind: "service", quantity: null, account_id: null, budget_line_id: null, cost_item_id: null });

/** Formularul documentelor de trezorerie: câmpurile se adaptează operațiunii (de ce are nevoie fiecare). */
export function TreasuryForm({ tabId, kind, documentId: initialId }: { tabId: string; kind: TreasuryKind; documentId?: string }) {
  const { orgId, role, openTab, closeTab, updateTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const base = `/organizations/${orgId}/treasury`;
  const titles = KIND_TITLES[kind];
  const isLines = kind === "advance_report" || kind === "service_act";
  const isCash = kind === "cash_receipt" || kind === "cash_payment";

  const [meta, setMeta] = useState<OpMeta[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [extraCp, setExtraCp] = useState<Counterparty[]>([]);
  const [documentId, setDocumentId] = useState(initialId);
  const [currentTab, setCurrentTab] = useState(tabId);
  const [operation, setOperation] = useState("");
  const [docNumber, setDocNumber] = useState("");
  const [docDate, setDocDate] = useState(today());
  const [bankId, setBankId] = useState("");
  const [amount, setAmount] = useState("");
  const [rate, setRate] = useState("");
  const [counterpartyId, setCounterpartyId] = useState("");
  const [personId, setPersonId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [grantId, setGrantId] = useState("");
  const [purpose, setPurpose] = useState("");
  const [basis, setBasis] = useState("");
  const [lines, setLines] = useState<TreasuryLine[]>([emptyLine()]);
  const [version, setVersion] = useState<number | null>(null);
  const [posted, setPosted] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [balance, setBalance] = useState<string | null>(null);
  const editable = can(role, POSTING_ROLES);
  const ro = posted || busy || !editable;

  useEffect(() => {
    api<KindMeta[]>(`${base}/meta`).then((m) => {
      const ops = m.find((k) => k.kind === kind)?.operations ?? [];
      setMeta(ops);
      setOperation((cur) => cur || ops[0]?.code || "");
    }, (e: Error) => setError(e.message));
    api<Person[]>(`/organizations/${orgId}/persons`).then(setPersons, () => setPersons([]));
  }, [base, kind, orgId]);

  const op = meta.find((o) => o.code === operation);
  const wants = (field: string) => isLines ? false : !!op && (op.needs.includes(field) || op.optional.includes(field));
  const needs = (field: string) => !!op && op.needs.includes(field);
  const bank = catalogs.bankAccounts.find((b) => b.id === bankId);
  const foreign = !!bank && bank.currency !== "MDL";
  const accounts = catalogs.accounts.filter((a) => !a.is_group);
  const cps = [...catalogs.counterparties, ...extraCp.filter((c) => !catalogs.counterparties.some((x) => x.id === c.id))];
  const touch = () => setDirty(true);

  // contul de avans: se propune 226/224 dacă există
  useEffect(() => {
    if (kind === "advance_report" && !accountId && accounts.length) {
      const pick = accounts.find((a) => a.code === "226") ?? accounts.find((a) => a.code === "224");
      if (pick) setAccountId(pick.id);
    }
  }, [kind, accountId, accounts]);

  const fill = useCallback((d: TreasuryDoc) => {
    setOperation(d.operation ?? "");
    setDocNumber(d.doc_number ?? "");
    setDocDate(d.doc_date ?? today());
    setBankId(d.bank_account_id ?? "");
    setAmount(d.amount ?? "");
    setRate(d.exchange_rate ?? "");
    setCounterpartyId(d.counterparty_id ?? "");
    setPersonId(d.person_id ?? "");
    setAccountId(d.account_id ?? "");
    setGrantId(d.grant_id ?? "");
    setPurpose(d.purpose ?? "");
    setBasis(d.basis ?? "");
    setLines(d.lines.length ? d.lines : [emptyLine()]);
    setVersion(d.version);
    setPosted(Boolean(d.is_posted));
    setDirty(false);
  }, []);

  useEffect(() => {
    if (initialId) api<TreasuryDoc>(`${base}/docs/${initialId}`).then(fill, (e: Error) => setError(e.message));
  }, [base, initialId, fill]);

  // soldul casei / avansul nejustificat, ca să se vadă înainte de înregistrare
  useEffect(() => {
    if (isCash) api<{ balance: string }>(`${base}/cash-balance?on_date=${docDate}`).then((r) => setBalance(r.balance), () => setBalance(null));
    else if (kind === "advance_report" && personId && accountId)
      api<{ balance: string }>(`${base}/advance-balance?person_id=${personId}&account_id=${accountId}&on_date=${docDate}`).then((r) => setBalance(r.balance), () => setBalance(null));
    else setBalance(null);
  }, [base, isCash, kind, docDate, personId, accountId, posted]);

  useEffect(() => {
    updateTab(currentTab, { dirty });
  }, [dirty, currentTab, updateTab]);

  const linesTotal = useMemo(() => lines.reduce((s, l) => s + Number(parseAmount(l.amount) ?? 0), 0), [lines]);

  function body() {
    const common = {
      kind, doc_number: docNumber.trim() || null, doc_date: docDate, counterparty_id: counterpartyId || null,
      person_id: personId || null, account_id: accountId || null, grant_id: grantId || null,
      purpose: purpose.trim() || null, basis: basis.trim() || null, bank_account_id: bankId || null, version,
      exchange_rate: foreign && rate ? rate.replace(",", ".") : null, currency: bank?.currency ?? null,
    };
    if (isLines) {
      const out = lines.map((l, i) => {
        const a = parseAmount(l.amount);
        if (!l.description.trim()) throw new Error(`Rândul ${i + 1}: completați descrierea`);
        if (!a || Number(a) <= 0) throw new Error(`Rândul ${i + 1}: suma trebuie să fie pozitivă, cu cel mult 2 zecimale`);
        return { ...l, description: l.description.trim(), amount: a, quantity: l.quantity ? l.quantity.replace(",", ".") : null };
      });
      return { ...common, operation: null, amount: null, lines: out };
    }
    const value = parseAmount(amount);
    if (!value || Number(value) <= 0) throw new Error("Suma trebuie să fie pozitivă, cu cel mult 2 zecimale");
    if (foreign && !rate) throw new Error(`Contul bancar e în ${bank?.currency}: indicați cursul BNM`);
    return { ...common, operation, amount: value, lines: [] };
  }

  async function save(): Promise<string> {
    const payload = body();
    const d = documentId
      ? await api<TreasuryDoc>(`${base}/docs/${documentId}`, { method: "PUT", body: payload })
      : await api<TreasuryDoc>(`${base}/docs`, { method: "POST", body: payload });
    fill(d);
    const id = `tr:${d.document_id}`;
    if (!documentId) {
      updateTab(currentTab, { id, params: { kind, documentId: d.document_id } });
      setCurrentTab(id);
      setDocumentId(d.document_id);
    }
    updateTab(id, { title: `${titles.one} ${d.doc_number}` });
    notifyDocumentsChanged("treasury");
    return d.document_id;
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setInfo(null);
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
      const res = await api<TreasuryPostResult>(`${base}/docs/${id}/post`, { method: "POST" });
      fill(await api<TreasuryDoc>(`${base}/docs/${id}`));
      notifyDocumentsChanged("treasury");
      const over = res.warnings.map((w) => w.message).join(" ");
      if (close && !over) closeTab(`tr:${id}`, { force: true });
      else setInfo(`Înregistrat.${over ? ` Atenție: ${over}` : ""}`);
    });
  const onUnpost = () =>
    run(async () => {
      await api(`${base}/docs/${documentId}/unpost`, { method: "POST" });
      fill(await api<TreasuryDoc>(`${base}/docs/${documentId}`));
      notifyDocumentsChanged("treasury");
      setInfo("Înregistrarea a fost anulată; documentul se poate modifica.");
    });
  const onDtKt = () =>
    run(async () => {
      const id = dirty || !documentId ? await save() : documentId;
      openTab({ id: `dtkt:${id}`, title: `Dt/Kt: ${docNumber || titles.one}`, kind: "dtkt", params: { route: "treasury/docs", documentId: id } });
    });

  const nameOf = {
    cp: cps.find((c) => c.id === counterpartyId)?.name ?? "",
    person: persons.find((p) => p.id === personId)?.full_name ?? "",
    bank: bank ? `${bank.bank_name ?? "Bancă"} ${bank.iban}` : "",
    account: accounts.find((a) => a.id === accountId),
  };
  async function onPrint() {
    const org = await api<{ name: string }>(`/organizations/${orgId}`).then((o) => o.name, () => undefined);
    const fields = [
      { label: "Număr / data", value: `${docNumber || "—"} din ${day(docDate)}` },
      ...(op ? [{ label: "Operațiunea", value: op.label }] : []),
      ...(nameOf.cp ? [{ label: kind === "service_act" ? "Prestator" : "Contrapartida", value: nameOf.cp }] : []),
      ...(nameOf.person ? [{ label: "Persoana", value: nameOf.person }] : []),
      ...(nameOf.bank ? [{ label: "Cont bancar", value: nameOf.bank }] : []),
      ...(nameOf.account ? [{ label: "Cont contabil", value: `${nameOf.account.code} ${nameOf.account.name}` }] : []),
      ...(isLines ? [] : [{ label: "Suma", value: `${money(amount.replace(",", "."))} ${bank?.currency ?? "MDL"}` }]),
      ...(purpose ? [{ label: "Destinația / scopul", value: purpose }] : []),
      ...(basis ? [{ label: "Temei", value: basis }] : []),
    ];
    const title = {
      cash_receipt: "ORDIN DE ÎNCASARE ÎN NUMERAR", cash_payment: "ORDIN DE PLATĂ ÎN NUMERAR", advance_report: "DECONT DE AVANS",
      service_act: "ACT DE PRIMIRE A SERVICIILOR", bank_receipt: "ÎNCASARE PE CONT", bank_payment: "PLATĂ DIN CONT",
    }[kind];
    const ok = printDocument({
      title, organization: org, fields,
      table: isLines ? {
        head: ["Nr.", "Descrierea", "Tipul", "Suma"],
        rows: lines.map((l, i) => [String(i + 1), l.description, LINE_KINDS[l.line_kind] ?? l.line_kind, money(parseAmount(l.amount) ?? 0)]),
        foot: ["", "Total", "", money(linesTotal)],
      } : undefined,
      signatures: kind === "cash_receipt" ? ["Contabil-șef", "Casier"] : kind === "cash_payment" ? ["Conducător", "Contabil-șef", "Casier", "Primit (semnătura)"]
        : kind === "advance_report" ? ["Persoana responsabilă", "Contabil-șef", "Conducător"] : kind === "service_act" ? ["Prestator", "Beneficiar"] : ["Contabil-șef"],
    });
    if (!ok) setError("Fereastra de tipărire a fost blocată de browser; permiteți ferestrele noi.");
  }

  const setLine = (i: number, patch: Partial<TreasuryLine>) => (touch(), setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l))));
  const id = (s: string) => `${tabId}-${s}`;

  return (
    <div
      onKeyDown={(e) => {
        if (e.ctrlKey && e.key === "Enter" && !ro) (e.preventDefault(), onPost(true));
        else if (e.ctrlKey && e.key.toLowerCase() === "s" && !ro) (e.preventDefault(), run(async () => (await save(), setInfo("Salvat."))));
      }}
    >
      <h1>
        {titles.one} {documentId ? `${docNumber} din ${day(docDate)}` : "(nou)"}
        {posted && <span className="badge ok">înregistrat</span>}
      </h1>
      <div className="bar">
        {!posted && editable && (
          <>
            <button className="b primary" onClick={() => onPost(true)} disabled={busy}>
              Înregistrează și închide
            </button>
            <button className="b" onClick={() => onPost(false)} disabled={busy}>
              Înregistrează
            </button>
            <button className="b" disabled={busy} onClick={() => run(async () => (await save(), setInfo("Salvat.")))}>
              Salvează
            </button>
          </>
        )}
        {posted && editable && (
          <button className="b" onClick={onUnpost} disabled={busy}>
            Anulează înregistrarea
          </button>
        )}
        <button className="b" onClick={onDtKt} disabled={busy || !editable}>
          Dt/Kt
        </button>
        <button className="b" onClick={onPrint} disabled={busy}>
          Tipărire
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {info && <div className="hint">{info}</div>}
      {isCash && balance !== null && <div className="hint">Soldul casei la {day(docDate)}: {money(balance)} MDL</div>}
      {kind === "advance_report" && balance !== null && (
        <div className="hint">
          Avans nejustificat al persoanei: {money(balance)} MDL
          {linesTotal > Number(balance) ? ` · decontul îl depășește cu ${money(linesTotal - Number(balance))} (se datorează persoanei)` : linesTotal > 0 ? ` · rest de restituit: ${money(Number(balance) - linesTotal)}` : ""}
        </div>
      )}

      <div className="form">
        <label htmlFor={id("num")}>Număr</label>
        <input id={id("num")} value={docNumber} disabled={ro} placeholder="se atribuie automat" onChange={(e) => (touch(), setDocNumber(e.target.value))} />
        <label htmlFor={id("date")}>Data</label>
        <input id={id("date")} type="date" value={docDate} disabled={ro} onChange={(e) => (touch(), setDocDate(e.target.value))} />

        {!isLines && (
          <>
            <label htmlFor={id("op")}>Operațiunea</label>
            <select id={id("op")} value={operation} disabled={ro} onChange={(e) => (touch(), setOperation(e.target.value))}>
              {meta.map((o) => (
                <option key={o.code} value={o.code}>
                  {o.label}
                </option>
              ))}
            </select>
            <label htmlFor={id("sum")}>Suma</label>
            <input id={id("sum")} className="num" inputMode="decimal" value={amount} disabled={ro} onChange={(e) => (touch(), setAmount(e.target.value))} />
          </>
        )}

        {wants("bank") && (
          <>
            <label htmlFor={id("bank")}>Cont bancar</label>
            <select id={id("bank")} value={bankId} disabled={ro} onChange={(e) => (touch(), setBankId(e.target.value))}>
              <option value="">— alegeți —</option>
              {catalogs.bankAccounts.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.bank_name ?? "Bancă"} {b.iban} ({b.currency})
                </option>
              ))}
            </select>
            <label htmlFor={id("rate")}>Curs BNM</label>
            <input id={id("rate")} className="num" value={rate} disabled={ro || !foreign} placeholder={foreign ? "obligatoriu" : "—"} onChange={(e) => (touch(), setRate(e.target.value))} />
          </>
        )}

        {(wants("counterparty") || kind === "service_act") && (
          <>
            <label htmlFor={id("cp")}>{kind === "service_act" ? "Prestator" : "Contrapartidă"}{needs("counterparty") || kind === "service_act" ? " *" : ""}</label>
            <div className="wide">
              <CounterpartyField id={id("cp")} value={counterpartyId} options={cps} disabled={ro} onChange={(v) => (touch(), setCounterpartyId(v))} onCreated={(c) => (setExtraCp((x) => [...x, c]), touch(), setCounterpartyId(c.id))} />
            </div>
          </>
        )}

        {(wants("person") || kind === "advance_report") && (
          <>
            <label htmlFor={id("person")}>Persoana{needs("person") || kind === "advance_report" ? " *" : ""}</label>
            <select id={id("person")} className="wide" value={personId} disabled={ro} onChange={(e) => (touch(), setPersonId(e.target.value))}>
              <option value="">— alegeți —</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name}
                </option>
              ))}
            </select>
          </>
        )}

        {(wants("account") || kind === "advance_report") && (
          <>
            <label htmlFor={id("acc")}>{kind === "advance_report" ? "Cont de avans *" : "Contul contabil *"}</label>
            <select id={id("acc")} className="wide" value={accountId} disabled={ro} onChange={(e) => (touch(), setAccountId(e.target.value))}>
              <option value="">— alegeți —</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </select>
          </>
        )}

        {wants("grant") && (
          <>
            <label htmlFor={id("grant")}>Grant{needs("grant") ? " *" : ""}</label>
            <select id={id("grant")} className="wide" value={grantId} disabled={ro} onChange={(e) => (touch(), setGrantId(e.target.value))}>
              <option value="">— fără grant —</option>
              {catalogs.grants.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.code} {g.title}
                </option>
              ))}
            </select>
          </>
        )}

        <label htmlFor={id("purpose")}>{kind === "advance_report" ? "Scopul avansului" : "Destinația"}</label>
        <input id={id("purpose")} className="wide" maxLength={210} value={purpose} disabled={ro} onChange={(e) => (touch(), setPurpose(e.target.value))} />
        {(isCash || kind === "advance_report") && (
          <>
            <label htmlFor={id("basis")}>Temei</label>
            <input id={id("basis")} className="wide" maxLength={210} value={basis} disabled={ro} placeholder="ex. cerere, dispoziție, contract" onChange={(e) => (touch(), setBasis(e.target.value))} />
          </>
        )}
      </div>

      {isLines && (
        <>
          <h2>{kind === "advance_report" ? "Cheltuieli justificate" : "Servicii primite"}</h2>
          <table className="grid edit">
            <thead>
              <tr>
                <th>Descrierea</th>
                <th>Tipul</th>
                <th className="num">Cant.</th>
                <th className="num">Suma</th>
                <th>Cont cheltuieli</th>
                <th>Linia de buget</th>
                <th>Articol</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td>
                    <input aria-label={`Descrierea rândului ${i + 1}`} value={l.description} disabled={ro} onChange={(e) => setLine(i, { description: e.target.value })} />
                  </td>
                  <td>
                    <select aria-label="Tipul rândului" value={l.line_kind} disabled={ro} onChange={(e) => setLine(i, { line_kind: e.target.value })}>
                      {Object.entries(LINE_KINDS).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input aria-label="Cantitatea" className="num" value={l.quantity ?? ""} disabled={ro} onChange={(e) => setLine(i, { quantity: e.target.value || null })} />
                  </td>
                  <td>
                    <input aria-label={`Suma rândului ${i + 1}`} className="num" inputMode="decimal" value={l.amount} disabled={ro} onChange={(e) => setLine(i, { amount: e.target.value })} />
                  </td>
                  <td>
                    <select aria-label="Cont cheltuieli" value={l.account_id ?? ""} disabled={ro} onChange={(e) => setLine(i, { account_id: e.target.value || null })}>
                      <option value="">— după regulă —</option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.code} {a.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <BudgetLineSelect grants={catalogs.grants} value={l.budget_line_id ?? ""} disabled={ro} label="Linia de buget" onChange={(v) => setLine(i, { budget_line_id: v || null })} />
                  </td>
                  <td>
                    <select aria-label="Articol de cheltuieli" value={l.cost_item_id ?? ""} disabled={ro} onChange={(e) => setLine(i, { cost_item_id: e.target.value || null })}>
                      <option value="">—</option>
                      {catalogs.costItems.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {!ro && lines.length > 1 && (
                      <button className="b" aria-label={`Șterge rândul ${i + 1}`} onClick={() => (touch(), setLines((ls) => ls.filter((_, j) => j !== i)))}>
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3}>
                  <b>Total</b>
                </td>
                <td className="num">
                  <b>{money(linesTotal)}</b>
                </td>
                <td colSpan={4} />
              </tr>
            </tfoot>
          </table>
          {!ro && (
            <div className="bar">
              <button className="b" onClick={() => (touch(), setLines((ls) => [...ls, emptyLine()]))}>
                Adaugă rând
              </button>
            </div>
          )}
        </>
      )}
      {documentId && !dirty && operation === "supplier" && counterpartyId && (kind === "bank_payment" || kind === "cash_payment") && (
        <SettlementsPanel key={`${documentId}:${posted}`} orgId={orgId} paymentId={documentId} editable={editable} />
      )}
      <p className="footer-note">
        <span className="kbd">Ctrl+Enter</span> înregistrează și închide · <span className="kbd">Ctrl+S</span> salvează
      </p>
    </div>
  );
}
