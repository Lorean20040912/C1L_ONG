import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ExchangeRate } from "../../api/types";
import { useAction } from "../../lib/useAction";
import { day, today } from "../../lib/format";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** Cursurile oficiale BNM: descărcare pe o dată și introducere manuală. */
export function ExchangeRatesScreen() {
  const { orgId, role } = useShell();
  const [rows, setRows] = useState<ExchangeRate[]>([]);
  const [date, setDate] = useState(today());
  const [currencies, setCurrencies] = useState("EUR, USD");
  const [manualCur, setManualCur] = useState("");
  const [manualRate, setManualRate] = useState("");
  const { busy, error, info, run } = useAction();
  const allowed = can(role, POSTING_ROLES);

  const load = useCallback(
    () => api<ExchangeRate[]>(`/organizations/${orgId}/exchange-rates`).then(setRows).catch(() => {}),
    [orgId],
  );
  useEffect(() => {
    load();
  }, [load]);

  const fetchBnm = () =>
    run(async () => {
      const list = currencies.split(/[\s,;]+/).filter(Boolean);
      const res = await api<ExchangeRate[]>(`/organizations/${orgId}/exchange-rates/bnm`, {
        method: "POST",
        body: { rate_date: date, currencies: list },
      });
      await load();
      return `Au fost salvate ${res.length} cursuri BNM la ${day(date)}.`;
    });

  const saveManual = () =>
    run(async () => {
      const rate = manualRate.replace(",", ".").trim();
      if (manualCur.trim().length !== 3 || !(Number(rate) > 0)) throw new Error("Introduceți valuta (3 litere) și cursul");
      await api(`/organizations/${orgId}/exchange-rates`, {
        method: "PUT",
        body: { currency: manualCur.trim().toUpperCase(), rate_date: date, rate },
      });
      await load();
      setManualRate("");
      return "Cursul a fost salvat.";
    });

  return (
    <>
      <h1>Curs BNM</h1>
      <Messages error={error} info={info} />
      {allowed && (
        <div className="form">
          <label htmlFor="r-date">Data</label>
          <input id="r-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <label htmlFor="r-cur">Valute BNM</label>
          <input id="r-cur" value={currencies} onChange={(e) => setCurrencies(e.target.value)} />
          <div className="bar">
            <button className="b primary" disabled={busy} onClick={fetchBnm}>
              Descarcă de la BNM
            </button>
          </div>
          <label htmlFor="r-mc">Manual: valuta</label>
          <input id="r-mc" value={manualCur} maxLength={3} onChange={(e) => setManualCur(e.target.value)} />
          <label htmlFor="r-mr">Manual: curs</label>
          <input id="r-mr" value={manualRate} onChange={(e) => setManualRate(e.target.value)} />
          <div className="bar">
            <button className="b" disabled={busy} onClick={saveManual}>
              Salvează manual
            </button>
          </div>
        </div>
      )}
      <table className="grid">
        <thead>
          <tr>
            <th>Data</th>
            <th>Valuta</th>
            <th className="num">Curs (MDL)</th>
            <th>Sursa</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.currency}-${r.rate_date}`}>
              <td>{day(r.rate_date)}</td>
              <td>{r.currency}</td>
              <td className="num">{Number(r.rate).toFixed(4).replace(".", ",")}</td>
              <td>{r.source}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                Nu sunt cursuri.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
