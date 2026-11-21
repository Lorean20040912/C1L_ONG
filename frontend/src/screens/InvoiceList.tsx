import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { InvoiceListItem } from "../api/types";
import { onDocumentsChanged } from "../lib/events";
import { day, money } from "../lib/format";
import { newId, useShell } from "../shell/tabs";
import { StatusIcon } from "./StatusIcon";

export function InvoiceList() {
  const { orgId, openTab } = useShell();
  const [rows, setRows] = useState<InvoiceListItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api<InvoiceListItem[]>(`/organizations/${orgId}/invoices`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [orgId]);

  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("invoices", load), [load]);

  const create = () => openTab({ id: newId("invoice"), title: "Factură primită (nouă)", kind: "invoice" });
  const open = (r: InvoiceListItem) =>
    openTab({
      id: `invoice:${r.document_id}`,
      title: `Factură primită ${r.doc_number ?? ""}`,
      kind: "invoice",
      params: { documentId: r.document_id },
    });
  const dtkt = () => {
    const r = rows?.find((x) => x.document_id === selected);
    if (r)
      openTab({
        id: `dtkt:${r.document_id}`,
        title: `Dt/Kt: ${r.doc_number ?? ""}`,
        kind: "dtkt",
        params: { route: "invoices", documentId: r.document_id },
      });
  };

  const q = search.trim().toLowerCase();
  const visible = (rows ?? []).filter(
    (r) => !q || `${r.doc_number} ${r.counterparty_name}`.toLowerCase().includes(q),
  );

  return (
    <div
      onKeyDown={(e) => {
        if (e.key === "Insert") create();
      }}
    >
      <h1>Facturi primite</h1>
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
        <span className="sp" />
        <input className="b" placeholder="Căutare" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Căutare în listă" />
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
              <th>Contrapartidă</th>
              <th className="num">Suma, lei</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.document_id}
                className={selected === r.document_id ? "sel" : ""}
                tabIndex={0}
                onClick={() => setSelected(r.document_id)}
                onDoubleClick={() => open(r)}
                onKeyDown={(e) => e.key === "Enter" && open(r)}
              >
                <td>
                  <StatusIcon posted={r.is_posted} deleted={r.deletion_mark} />
                </td>
                <td>{[r.series, r.doc_number].filter(Boolean).join(" ")}</td>
                <td>{day(r.doc_date)}</td>
                <td>{r.counterparty_name}</td>
                <td className="num">{money(r.total_amount)}</td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  Nu sunt facturi. Apăsați „Creare” sau Insert.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <p className="footer-note">
        Dublu clic deschide documentul · <span className="kbd">Insert</span> document nou · <span className="kbd">Esc</span> închide fila
      </p>
    </div>
  );
}
