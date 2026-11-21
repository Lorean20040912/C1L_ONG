import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ENTITY_LABELS, type BudgetLineExecution, type CalendarItem, type OrganizationBrief } from "../api/types";
import { onDocumentsChanged } from "../lib/events";
import { day } from "../lib/format";
import { Meter, percent } from "../screens/BudgetExecution";
import { useShell, type Tab } from "./tabs";

const STATUS_CLASS: Record<CalendarItem["status"], string> = {
  overdue: "late",
  due_soon: "soon",
  submitted: "ok",
  upcoming: "muted",
};

function periodLabel(i: CalendarItem): string {
  const [y, m] = i.period_from.split("-").map(Number);
  if (i.code === "ONG17") return `anul ${y}`;
  if (i.code === "5-CON") return `trim. ${Math.floor((m - 1) / 3) + 1} ${y}`;
  return `${String(m).padStart(2, "0")}.${y}`;
}

function reportTab(i: CalendarItem): Tab {
  if (i.code === "ONG17" || i.code === "5-CON") {
    const kind = i.code === "ONG17" ? "ong17" : "con5";
    return { id: `${kind}:${i.period_from}`, title: `${i.code} ${periodLabel(i)}`, kind, params: { periodFrom: i.period_from } };
  }
  return { id: `screen:${i.code}`, title: i.code, kind: "placeholder" };
}

interface GrantSummary {
  code: string;
  planned: number;
  spent: number;
  overLines: string[];
}

function summarize(rows: BudgetLineExecution[]): GrantSummary[] {
  const map = new Map<string, GrantSummary>();
  for (const r of rows) {
    const g = map.get(r.grant_id) ?? { code: r.grant_code, planned: 0, spent: 0, overLines: [] };
    g.planned += Number(r.planned);
    g.spent += Number(r.spent);
    if (Number(r.over) > 0) g.overLines.push(`${r.code} ${r.name}`);
    map.set(r.grant_id, g);
  }
  return [...map.values()];
}

export function HomeScreen({ org }: { org: OrganizationBrief | undefined }) {
  const { orgId, openTab } = useShell();
  const [budgets, setBudgets] = useState<GrantSummary[] | null>(null);
  const [calendar, setCalendar] = useState<CalendarItem[] | null>(null);
  const today = new Date().toLocaleDateString("ro-RO", { weekday: "long", day: "numeric", month: "long" });

  useEffect(() => {
    const load = () =>
      api<BudgetLineExecution[]>(`/organizations/${orgId}/budget-execution`)
        .then((rows) => setBudgets(summarize(rows)))
        .catch(() => setBudgets([]));
    load();
    return onDocumentsChanged("invoices", load);
  }, [orgId]);

  useEffect(() => {
    api<CalendarItem[]>(`/organizations/${orgId}/reports/calendar`)
      .then(setCalendar)
      .catch(() => setCalendar([]));
  }, [orgId]);

  const openBudget = () => openTab({ id: "budget", title: "Execuția bugetului", kind: "budget" });

  return (
    <>
      <h1>Pagina inițială</h1>
      <div className="cols">
        <div>
          <h2>Astăzi: {today}</h2>
          {org && (
            <div className="card">
              <b>{org.name}</b>
              <div className="muted">
                IDNO {org.idno} · {ENTITY_LABELS[org.entity_type]} ·{" "}
                {org.accounting_method === "double_entry" ? "partidă dublă" : "partidă simplă"}
              </div>
            </div>
          )}
          <h2>Calendarul raportărilor</h2>
          {calendar?.length === 0 && <p className="muted">Nu sunt termene de raportare.</p>}
          {calendar && calendar.length > 0 && (
            <table className="grid">
              <thead>
                <tr>
                  <th>Termen</th>
                  <th>Raport</th>
                  <th>Perioada</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                {calendar.map((i) => (
                  <tr key={i.id}>
                    <td>{day(i.due_date)}</td>
                    <td>
                      <button className="link" title={i.title ?? ""} onClick={() => openTab(reportTab(i))}>
                        {i.code}
                      </button>
                    </td>
                    <td>{periodLabel(i)}</td>
                    <td className={STATUS_CLASS[i.status]}>
                      {i.status_label}
                      {i.status === "overdue" ? ` (${-i.days_left} zile)` : i.status === "due_soon" ? ` (${i.days_left} zile)` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div>
          <h2>Execuția bugetelor</h2>
          {budgets?.length === 0 && <p className="muted">Nu sunt granturi cu buget.</p>}
          {budgets?.map((g) => {
            const p = percent(g.spent, g.planned);
            return (
              <div className="card" key={g.code}>
                <button className="link" onClick={openBudget}>
                  {g.code}
                </button>{" "}
                — {p}%
                <Meter value={p} />
                {g.overLines.length > 0 && <div className="late small">Depășire pe linia {g.overLines.join(", ")}</div>}
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
