import { useCallback, useEffect, useState } from "react";
import { api, download } from "../../api/client";
import { useCatalogs } from "../../catalog/useCatalogs";
import { onDocumentsChanged } from "../../lib/events";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";

interface CardRow {
  entry_line_id: number;
  entry_date: string;
  doc_number: string | null;
  description: string | null;
  account: string;
  corresponding_account: string;
  debit: string;
  credit: string;
  balance: string;
  grant_code: string | null;
}

interface AnalysisRow {
  account_id: string;
  code: string;
  name: string;
  debit: string;
  credit: string;
}

interface Result<R> {
  code: string;
  name: string;
  opening: string;
  turnover_debit: string;
  turnover_credit: string;
  closing: string;
  rows: R[];
}

/** Soldul cu semn: pozitiv = debitor, negativ = creditor. */
function balance(value: string) {
  const n = Number(value);
  if (!n) return "0,00";
  return `${money(Math.abs(n))} ${n > 0 ? "Dt" : "Kt"}`;
}

/** Fișa contului și analiza contului (ToR F1.6): același filtru, două prezentări. */
export function AccountReports({ mode, accountId: initialAccount }: { mode: "card" | "analysis"; accountId?: string }) {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const year = new Date().getFullYear();
  const [accountId, setAccountId] = useState(initialAccount ?? "");
  const [from, setFrom] = useState(`${year}-01-01`);
  const [to, setTo] = useState(`${year}-12-31`);
  const [grantId, setGrantId] = useState("");
  const [counterpartyId, setCounterpartyId] = useState("");
  const [card, setCard] = useState<Result<CardRow> | null>(null);
  const [analysis, setAnalysis] = useState<Result<AnalysisRow> | null>(null);
  const { error, run } = useAction();

  const params = useCallback(() => {
    const p = new URLSearchParams({ account_id: accountId, date_from: from, date_to: to });
    if (grantId) p.set("grant_id", grantId);
    if (counterpartyId) p.set("counterparty_id", counterpartyId);
    return p;
  }, [accountId, from, to, grantId, counterpartyId]);

  const load = useCallback(() => {
    if (!accountId) return;
    const path = `/organizations/${orgId}/reports/${mode === "card" ? "account-card" : "account-analysis"}?${params()}`;
    run(async () => {
      if (mode === "card") setCard(await api<Result<CardRow>>(path));
      else setAnalysis(await api<Result<AnalysisRow>>(path));
    });
  }, [orgId, mode, accountId, params, run]);

  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("invoices", load), [load]);

  const accounts = catalogs.accounts;
  const data = mode === "card" ? card : analysis;

  return (
    <>
      <h1>{mode === "card" ? "Fișa contului" : "Analiza contului"}</h1>
      <div className="bar">
        <select className="b" aria-label="Contul" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">— contul —</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.name}
            </option>
          ))}
        </select>
        <input className="b" type="date" aria-label="De la" value={from} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        <span className="muted">—</span>
        <input className="b" type="date" aria-label="Până la" value={to} onChange={(e) => e.target.value && setTo(e.target.value)} />
        <select className="b" aria-label="Grantul" value={grantId} onChange={(e) => setGrantId(e.target.value)}>
          <option value="">Toate granturile</option>
          {catalogs.grants.map((g) => (
            <option key={g.id} value={g.id}>
              {g.code}
            </option>
          ))}
        </select>
        <select className="b" aria-label="Contrapartida" value={counterpartyId} onChange={(e) => setCounterpartyId(e.target.value)}>
          <option value="">Toate contrapartidele</option>
          {catalogs.counterparties.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button className="b primary" onClick={load} disabled={!accountId}>
          Generează
        </button>
        {mode === "card" && card && (
          <button className="b" onClick={() => run(() => download(`/organizations/${orgId}/reports/account-card.xlsx?${params()}`, `fisa-${card.code}.xlsx`))}>
            Excel
          </button>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      {!accountId && <p className="muted">Alegeți contul.</p>}
      {accountId && data && (
        <table className="grid">
          <thead>
            {mode === "card" ? (
              <tr>
                <th>Data</th>
                <th>Document</th>
                <th>Conținut</th>
                <th>Grant</th>
                <th>Cont</th>
                <th>Corespondent</th>
                <th className="num">Debit</th>
                <th className="num">Credit</th>
                <th className="num">Sold</th>
              </tr>
            ) : (
              <tr>
                <th>Cont corespondent</th>
                <th>Denumire</th>
                <th className="num">Debit (din creditul)</th>
                <th className="num">Credit (în debitul)</th>
              </tr>
            )}
          </thead>
          <tbody>
            <tr className="total-row">
              <td colSpan={mode === "card" ? 8 : 2}>Sold inițial</td>
              <td className="num" colSpan={mode === "card" ? 1 : 2}>
                {balance(data.opening)}
              </td>
            </tr>
            {mode === "card"
              ? card!.rows.map((r, i) => (
                  <tr key={`${r.entry_line_id}-${i}`}>
                    <td>{day(r.entry_date)}</td>
                    <td>{r.doc_number}</td>
                    <td>{r.description}</td>
                    <td>{r.grant_code}</td>
                    <td>{r.account}</td>
                    <td>{r.corresponding_account}</td>
                    <td className="num">{Number(r.debit) ? money(r.debit) : ""}</td>
                    <td className="num">{Number(r.credit) ? money(r.credit) : ""}</td>
                    <td className="num">{balance(r.balance)}</td>
                  </tr>
                ))
              : analysis!.rows.map((r) => (
                  <tr key={r.account_id}>
                    <td>
                      <button
                        className="link"
                        title="Fișa contului corespondent"
                        onClick={() => openTab({ id: `account-card:${r.account_id}`, title: `Fișa contului ${r.code}`, kind: "account-card", params: { accountId: r.account_id } })}
                      >
                        {r.code}
                      </button>
                    </td>
                    <td>{r.name}</td>
                    <td className="num">{Number(r.debit) ? money(r.debit) : ""}</td>
                    <td className="num">{Number(r.credit) ? money(r.credit) : ""}</td>
                  </tr>
                ))}
            {data.rows.length === 0 && (
              <tr>
                <td colSpan={mode === "card" ? 9 : 4} className="muted">
                  Nu sunt înregistrări în perioadă.
                </td>
              </tr>
            )}
            <tr className="total-row">
              <td colSpan={mode === "card" ? 6 : 2}>Rulaj</td>
              <td className="num">{money(data.turnover_debit)}</td>
              <td className="num">{money(data.turnover_credit)}</td>
              {mode === "card" && <td />}
            </tr>
            <tr className="total-row">
              <td colSpan={mode === "card" ? 8 : 2}>Sold final</td>
              <td className="num" colSpan={mode === "card" ? 1 : 2}>
                {balance(data.closing)}
              </td>
            </tr>
          </tbody>
        </table>
      )}
    </>
  );
}
