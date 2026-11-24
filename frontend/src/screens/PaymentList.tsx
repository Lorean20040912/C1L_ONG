import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { PaymentOrder } from "../api/types";
import { useCatalogs } from "../catalog/useCatalogs";
import { onDocumentsChanged } from "../lib/events";
import { day, money } from "../lib/format";
import { newId, useShell } from "../shell/tabs";
import { StatusIcon } from "./StatusIcon";

export function PaymentList() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<PaymentOrder[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api<PaymentOrder[]>(`/organizations/${orgId}/payment-orders`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [orgId]);

  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("payment-orders", load), [load]);

  const create = () => openTab({ id: newId("payment"), title: "Ordin de plată (nou)", kind: "payment" });
  const open = (r: PaymentOrder) =>
    openTab({ id: `payment:${r.document_id}`, title: `Ordin de plată ${r.doc_number ?? ""}`, kind: "payment", params: { documentId: r.document_id } });
  const dtkt = () => {
    const r = rows?.find((x) => x.document_id === selected);
    if (r)
      openTab({
        id: `dtkt:${r.document_id}`,
        title: `Dt/Kt: ordin ${r.doc_number ?? ""}`,
        kind: "dtkt",
        params: { route: "payment-orders", documentId: r.document_id },
      });
  };
  const counterparty = (id: string | null) => catalogs.counterparties.find((c) => c.id === id)?.name ?? "";

  return (
    <div onKeyDown={(e) => e.key === "Insert" && create()}>
      <h1>Ordine de plată</h1>
      <div className="bar">
        <button className="b primary" onClick={create}>
          Creare
        </button>
        <button className="b" onClick={dtkt} disabled={!selected}>
          Dt/Kt
        </button>
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {rows === null && !error && <p className="muted">Se încarcă…</p>}
      {rows && (
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 24 }} />
              <th>Număr</th>
              <th>Data</th>
              <th>Tip</th>
              <th>Contrapartidă</th>
              <th className="num">Suma</th>
              <th>Valuta</th>
              <th>Destinația</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.document_id}
                className={selected === r.document_id ? "sel" : ""}
                tabIndex={0}
                onClick={() => setSelected(r.document_id)}
                onDoubleClick={() => open(r)}
                onKeyDown={(e) => e.key === "Enter" && open(r)}
              >
                <td>
                  <StatusIcon posted={r.is_posted} />
                </td>
                <td>{r.doc_number}</td>
                <td>{day(r.doc_date)}</td>
                <td>{r.direction === "outgoing" ? "Plată" : "Încasare"}</td>
                <td>{r.beneficiary_name ?? counterparty(r.counterparty_id)}</td>
                <td className="num">{money(r.amount)}</td>
                <td>{r.currency}</td>
                <td>{r.purpose}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  Nu sunt ordine de plată. Apăsați „Creare” sau Insert.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <p className="footer-note">
        Dublu clic deschide documentul · <span className="kbd">Insert</span> document nou
      </p>
    </div>
  );
}
