import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { BudgetLineExecution } from "../api/types";
import { useCatalogs } from "../catalog/useCatalogs";
import { onDocumentsChanged } from "../lib/events";
import { money } from "../lib/format";
import { useShell } from "../shell/tabs";

export function percent(spent: string | number, planned: string | number): number {
  const p = Number(planned);
  return p > 0 ? Math.round((Number(spent) / p) * 100) : 0;
}

export function Meter({ value }: { value: number }) {
  return (
    <div className="meter" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <i className={value > 100 ? "over" : ""} style={{ width: `${Math.min(value, 100)}%` }} />
    </div>
  );
}

/** Execuția bugetului: planificat / cheltuit / rest pe linii, depășirile în roșu (ToR F6.2). */
export function BudgetExecution() {
  const { orgId } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [grantId, setGrantId] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [rows, setRows] = useState<BudgetLineExecution[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (grantId) params.set("grant_id", grantId);
    if (dateTo) params.set("date_to", dateTo);
    setError(null);
    api<BudgetLineExecution[]>(`/organizations/${orgId}/budget-execution?${params}`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [orgId, grantId, dateTo]);

  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("invoices", load), [load]);

  const groups = new Map<string, BudgetLineExecution[]>();
  for (const r of rows ?? []) groups.set(r.grant_id, [...(groups.get(r.grant_id) ?? []), r]);
  const sum = (list: BudgetLineExecution[], key: "planned" | "spent" | "remaining") =>
    list.reduce((s, r) => s + Number(r[key]), 0);

  return (
    <>
      <h1>Execuția bugetului</h1>
      <div className="bar">
        <select className="b" value={grantId} onChange={(e) => setGrantId(e.target.value)} aria-label="Grantul">
          <option value="">Toate granturile</option>
          {catalogs.grants.map((g) => (
            <option key={g.id} value={g.id}>
              {g.code} {g.title}
            </option>
          ))}
        </select>
        <label className="muted" htmlFor="budget-date">
          până la
        </label>
        <input id="budget-date" className="b" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {rows?.length === 0 && <p className="muted">Nu sunt linii de buget.</p>}
      {[...groups.values()].map((lines) => {
        const grant = catalogs.grants.find((g) => g.id === lines[0].grant_id);
        const over = lines.filter((l) => Number(l.over) > 0);
        return (
          <section key={lines[0].grant_id}>
            <h2>
              {lines[0].grant_code} {grant?.title}
            </h2>
            {over.length > 0 && (
              <div className="hint warn">
                Depășire pe {over.map((l) => `${l.code} ${l.name} (${money(l.over)})`).join(", ")} — suma peste buget nu e deductibilă și
                intră în ONG17.
              </div>
            )}
            <table className="grid">
              <thead>
                <tr>
                  <th>Linia</th>
                  <th>Denumirea</th>
                  <th className="num">Planificat</th>
                  <th className="num">Cheltuit</th>
                  <th className="num">Rest</th>
                  <th style={{ width: 180 }}>Execuția</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => {
                  const p = percent(l.spent, l.planned);
                  return (
                    <tr key={l.budget_line_id} className={Number(l.over) > 0 ? "over-row" : ""}>
                      <td>{l.code}</td>
                      <td>{l.name}</td>
                      <td className="num">{money(l.planned)}</td>
                      <td className="num">{money(l.spent)}</td>
                      <td className={`num${Number(l.remaining) < 0 ? " late" : ""}`}>{money(l.remaining)}</td>
                      <td>
                        <div className="meter-cell">
                          <Meter value={p} />
                          <span>{p}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                <tr className="total-row">
                  <td colSpan={2}>Total</td>
                  <td className="num">{money(sum(lines, "planned"))}</td>
                  <td className="num">{money(sum(lines, "spent"))}</td>
                  <td className="num">{money(sum(lines, "remaining"))}</td>
                  <td>{percent(sum(lines, "spent"), sum(lines, "planned"))}%</td>
                </tr>
              </tbody>
            </table>
          </section>
        );
      })}
    </>
  );
}
