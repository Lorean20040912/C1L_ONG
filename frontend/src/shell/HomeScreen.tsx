import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ENTITY_LABELS, type BudgetLineExecution, type OrganizationBrief } from "../api/types";
import { onDocumentsChanged } from "../lib/events";
import { Meter, percent } from "../screens/BudgetExecution";
import { useShell } from "./tabs";

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
  const today = new Date().toLocaleDateString("ro-RO", { weekday: "long", day: "numeric", month: "long" });

  useEffect(() => {
    const load = () =>
      api<BudgetLineExecution[]>(`/organizations/${orgId}/budget-execution`)
        .then((rows) => setBudgets(summarize(rows)))
        .catch(() => setBudgets([]));
    load();
    return onDocumentsChanged("invoices", load);
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
          <p className="muted">Termenele IPC21, 5-CON și ONG17 apar aici odată cu modulul de rapoarte.</p>
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
