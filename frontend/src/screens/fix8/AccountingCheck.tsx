import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAction } from "../../lib/useAction";
import { useShell, type Tab } from "../../shell/tabs";

interface Item {
  message: string;
  document_id: string | null;
  doc_type: string | null;
  doc_number: string | null;
  account_id: string | null;
  amount: string | null;
}
interface Check {
  code: string;
  title: string;
  severity: "ok" | "warning" | "error";
  count: number;
  items: Item[];
}
interface Result {
  ok: boolean;
  checks: Check[];
}

const MARK = { ok: "✔", warning: "⚠", error: "✖" } as const;

/** Deschide documentul sau fișa contului la care trimite constatarea. */
function target(item: Item): Tab | null {
  if (item.document_id) {
    const id = item.document_id;
    const label = item.doc_number ?? "";
    if (item.doc_type === "invoice") return { id: `invoice:${id}`, title: `Factură primită ${label}`, kind: "invoice", params: { documentId: id } };
    if (item.doc_type === "payment_order") return { id: `payment:${id}`, title: `Ordin de plată ${label}`, kind: "payment", params: { documentId: id } };
    return { id: `dtkt:${id}`, title: `Dt/Kt: ${label}`, kind: "dtkt", params: { route: "documents", documentId: id } };
  }
  if (item.account_id) return { id: `account-card:${item.account_id}`, title: "Fișa contului", kind: "account-card", params: { accountId: item.account_id } };
  return null;
}

/** Verificarea contabilității: controale de coerență pe perioadă, cu trimitere la documente și conturi. */
export function AccountingCheck() {
  const { orgId, openTab } = useShell();
  const year = new Date().getFullYear();
  const [from, setFrom] = useState(`${year}-01-01`);
  const [to, setTo] = useState(`${year}-12-31`);
  const [data, setData] = useState<Result | null>(null);
  const { error, busy, run } = useAction();

  const load = useCallback(() => {
    run(async () => setData(await api<Result>(`/organizations/${orgId}/reports/accounting-check?date_from=${from}&date_to=${to}`)));
  }, [orgId, from, to, run]);
  useEffect(load, [load]);

  return (
    <>
      <h1>Verificarea contabilității</h1>
      <div className="bar">
        <input className="b" type="date" aria-label="De la" value={from} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        <span className="muted">—</span>
        <input className="b" type="date" aria-label="Până la" value={to} onChange={(e) => e.target.value && setTo(e.target.value)} />
        <button className="b primary" onClick={load} disabled={busy}>
          Verifică
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {data && <p>{data.ok ? "Toate controalele sunt în regulă." : "Există constatări de verificat."}</p>}
      {data?.checks.map((c) => (
        <div key={c.code}>
          <h3>
            {MARK[c.severity]} {c.title}
            {c.count > 0 && <span className="muted"> · {c.count}</span>}
          </h3>
          {c.items.length > 0 && (
            <ul>
              {c.items.map((it, i) => {
                const tab = target(it);
                return (
                  <li key={i}>
                    {tab ? (
                      <button className="link" onClick={() => openTab(tab)}>
                        {it.message}
                      </button>
                    ) : (
                      it.message
                    )}
                    {it.doc_number && <span className="muted"> · {it.doc_number}</span>}
                  </li>
                );
              })}
              {c.count > c.items.length && <li className="muted">… și încă {c.count - c.items.length}</li>}
            </ul>
          )}
        </div>
      ))}
    </>
  );
}
