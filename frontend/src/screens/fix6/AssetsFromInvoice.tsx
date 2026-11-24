import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AssetInvoiceLine } from "../../api/fix6";
import { onDocumentsChanged } from "../../lib/events";
import { day, money } from "../../lib/format";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

const STATUS: Record<string, string> = { in_use: "în funcțiune", suspended: "nepus în funcțiune", written_off: "casat" };

/** Mijloace fixe din factură: rândurile „mijloc fix” ale facturilor primite și fișele create din ele. */
export function AssetsFromInvoice() {
  const { orgId, openTab } = useShell();
  const [rows, setRows] = useState<AssetInvoiceLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<AssetInvoiceLine[]>(`/organizations/${orgId}/fixed-assets/invoice-lines`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [orgId]);
  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("invoices", load), [load]);

  const openInvoice = (r: AssetInvoiceLine) =>
    openTab({ id: `invoice:${r.document_id}`, title: `Factura ${r.doc_number ?? ""}`.trim(), kind: "invoice", params: { documentId: r.document_id } });

  return (
    <>
      <h1>Mijloace fixe (din factură)</h1>
      <div className="bar">
        <button className="b" onClick={load}>
          Actualizează
        </button>
        <button className="b" onClick={() => openTab({ id: "invoice-list", title: "Facturi primite", kind: "invoice-list" })}>
          Factură nouă
        </button>
      </div>
      <Messages error={error} info={null} />
      <div className="hint">Fișa mijlocului fix se creează la înregistrarea facturii; anularea înregistrării o șterge.</div>
      {rows && (
        <table className="grid">
          <thead>
            <tr>
              <th>Factura</th>
              <th>Data</th>
              <th>Furnizorul</th>
              <th>Denumirea</th>
              <th className="num">Suma</th>
              <th>Factura înregistrată</th>
              <th>Fișa MF</th>
              <th>Starea</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.invoice_line_id}>
                <td>
                  <button className="link" onClick={() => openInvoice(r)}>
                    {r.doc_number || "fără număr"}
                  </button>
                </td>
                <td>{day(r.doc_date)}</td>
                <td>{r.counterparty}</td>
                <td>{r.description}</td>
                <td className="num">{money(r.amount)}</td>
                <td>{r.is_posted ? "da" : <span className="muted">nu (ciornă)</span>}</td>
                <td>{r.inventory_no ?? <span className="muted">— după înregistrare</span>}</td>
                <td>{r.asset_status ? (STATUS[r.asset_status] ?? r.asset_status) : ""}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  Nu sunt facturi cu rânduri „Mijloc fix”. Adăugați un rând de acest tip în factura primită.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </>
  );
}
