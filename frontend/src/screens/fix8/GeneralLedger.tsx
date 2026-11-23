import { useCallback, useEffect, useState } from "react";
import { api, download } from "../../api/client";
import { useCatalogs } from "../../catalog/useCatalogs";
import { onDocumentsChanged } from "../../lib/events";
import { money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";

interface Account {
  account_id: string;
  code: string;
  name: string;
  opening: string;
  turnover_debit: string;
  turnover_credit: string;
  closing: string;
  months: { month: string; debit: string; credit: string; balance: string }[];
}
interface Ledger {
  accounts: Account[];
  total_debit: string;
  total_credit: string;
}

/** Soldul cu semn: pozitiv = debitor, negativ = creditor. */
function balance(value: string) {
  const n = Number(value);
  if (!n) return "0,00";
  return `${money(Math.abs(n))} ${n > 0 ? "Dt" : "Kt"}`;
}

/** Cartea mare: pe fiecare cont, soldul inițial, rulajele lunare și soldul final. */
export function GeneralLedger() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const year = new Date().getFullYear();
  const [accountId, setAccountId] = useState("");
  const [grantId, setGrantId] = useState("");
  const [from, setFrom] = useState(`${year}-01`);
  const [to, setTo] = useState(`${year}-12`);
  const [data, setData] = useState<Ledger | null>(null);
  const { error, run } = useAction();

  const params = useCallback(() => {
    const p = new URLSearchParams({ date_from: `${from}-01`, date_to: `${to}-01` });
    if (accountId) p.set("account_id", accountId);
    if (grantId) p.set("grant_id", grantId);
    return p;
  }, [from, to, accountId, grantId]);

  const load = useCallback(() => {
    run(async () => setData(await api<Ledger>(`/organizations/${orgId}/reports/general-ledger?${params()}`)));
  }, [orgId, params, run]);
  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("invoices", load), [load]);

  return (
    <>
      <h1>Cartea mare</h1>
      <div className="bar">
        <select className="b" aria-label="Contul" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Toate conturile</option>
          {catalogs.accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.name}
            </option>
          ))}
        </select>
        <input className="b" type="month" aria-label="De la" value={from} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        <span className="muted">—</span>
        <input className="b" type="month" aria-label="Până la" value={to} onChange={(e) => e.target.value && setTo(e.target.value)} />
        <select className="b" aria-label="Grantul" value={grantId} onChange={(e) => setGrantId(e.target.value)}>
          <option value="">Toate granturile</option>
          {catalogs.grants.map((g) => (
            <option key={g.id} value={g.id}>
              {g.code}
            </option>
          ))}
        </select>
        <button className="b primary" onClick={load}>
          Generează
        </button>
        <button className="b" onClick={() => run(() => download(`/organizations/${orgId}/reports/general-ledger.xlsx?${params()}`, "cartea-mare.xlsx"))}>
          Excel
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {data && data.accounts.length === 0 && <p className="muted">Nicio mișcare în perioadă.</p>}
      {data && data.accounts.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>Cont</th>
              <th>Perioada</th>
              <th className="num">Rulaj Dt</th>
              <th className="num">Rulaj Kt</th>
              <th className="num">Sold</th>
            </tr>
          </thead>
          <tbody>
            {data.accounts.map((a) => (
              <LedgerBlock key={a.account_id} a={a} onCard={() => openTab({ id: `account-card:${a.account_id}`, title: `Fișa contului ${a.code}`, kind: "account-card", params: { accountId: a.account_id } })} />
            ))}
            <tr>
              <td colSpan={2}>
                <b>Total rulaje</b>
              </td>
              <td className="num">
                <b>{money(data.total_debit)}</b>
              </td>
              <td className="num">
                <b>{money(data.total_credit)}</b>
              </td>
              <td />
            </tr>
          </tbody>
        </table>
      )}
    </>
  );
}

function LedgerBlock({ a, onCard }: { a: Account; onCard: () => void }) {
  return (
    <>
      <tr>
        <td>
          <button className="link" onClick={onCard} title="Fișa contului">
            <b>{a.code}</b> {a.name}
          </button>
        </td>
        <td className="muted">Sold inițial</td>
        <td />
        <td />
        <td className="num">{balance(a.opening)}</td>
      </tr>
      {a.months.map((m) => (
        <tr key={m.month}>
          <td />
          <td>{m.month.slice(0, 7)}</td>
          <td className="num">{money(m.debit)}</td>
          <td className="num">{money(m.credit)}</td>
          <td className="num">{balance(m.balance)}</td>
        </tr>
      ))}
      <tr>
        <td />
        <td>
          <b>Total / sold final</b>
        </td>
        <td className="num">
          <b>{money(a.turnover_debit)}</b>
        </td>
        <td className="num">
          <b>{money(a.turnover_credit)}</b>
        </td>
        <td className="num">
          <b>{balance(a.closing)}</b>
        </td>
      </tr>
    </>
  );
}
