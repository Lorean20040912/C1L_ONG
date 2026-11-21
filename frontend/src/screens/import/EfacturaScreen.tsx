import { useCallback, useEffect, useState } from "react";
import { api, apiDownload } from "../../api/client";
import { readXmlFile } from "../../lib/xmlFile";
import { useAction } from "../../lib/useAction";
import { day, money } from "../../lib/format";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

interface Message {
  id: string;
  direction: "received" | "sent";
  efactura_id: string;
  status: string | null;
  document_id: string | null;
  synced_at: string | null;
}
interface InvoiceItem {
  document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  counterparty_name: string | null;
  total_amount: string | null;
}

const STATUSES = ["draft", "sent", "signed", "accepted", "rejected"];
const LABEL: Record<string, string> = {
  draft: "ciornă",
  sent: "trimisă",
  signed: "semnată",
  accepted: "acceptată",
  rejected: "respinsă",
};

/** e-Factura: import XML → factură primită, export XML al unei facturi, urmărirea statutului. */
export function EfacturaScreen() {
  const { orgId, role } = useShell();
  const [messages, setMessages] = useState<Message[]>([]);
  const [invoices, setInvoices] = useState<InvoiceItem[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [invoiceId, setInvoiceId] = useState("");
  const { busy, error, info, run } = useAction();
  const allowed = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/efactura`;

  const load = useCallback(async () => {
    setMessages(await api<Message[]>(`${base}/messages`).catch(() => []));
    setInvoices(await api<InvoiceItem[]>(`/organizations/${orgId}/invoices`).catch(() => []));
  }, [base, orgId]);
  useEffect(() => {
    load();
  }, [load]);

  const importXml = () =>
    run(async () => {
      if (!file) throw new Error("Alegeți fișierul XML al facturii");
      await api(`${base}/import`, { method: "POST", body: { xml: await readXmlFile(file) } });
      await load();
      return "Factura a fost importată ca factură primită (neînregistrată).";
    });

  const exportXml = () =>
    run(async () => {
      if (!invoiceId) throw new Error("Alegeți factura");
      const msg = await api<Message>(`${base}/invoices/${invoiceId}/export`, { method: "POST" });
      await load();
      await apiDownload(`${base}/messages/${msg.id}/xml`, `e-factura-${msg.efactura_id}.xml`);
      return "XML-ul a fost generat.";
    });

  const setStatus = (m: Message, status: string) =>
    run(async () => {
      await api(`${base}/messages/${m.id}/status`, { method: "PUT", body: { status } });
      await load();
    });

  return (
    <>
      <h1>e-Factura</h1>
      <Messages error={error} info={info} />
      <ReadOnlyNote show={!allowed} what="importul și exportul sunt permise contabililor" />
      {allowed && (
        <div className="form">
          <label htmlFor="e-file">Import: fișier XML (UBL)</label>
          <input id="e-file" type="file" accept=".xml,text/xml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="bar">
            <button className="b primary" disabled={busy || !file} onClick={importXml}>
              Importă factura
            </button>
          </div>
          <label htmlFor="e-inv">Export: factura emisă</label>
          <select id="e-inv" value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)}>
            <option value="">—</option>
            {invoices.map((i) => (
              <option key={i.document_id} value={i.document_id}>
                {i.doc_number} din {day(i.doc_date)} · {i.counterparty_name} · {money(i.total_amount)}
              </option>
            ))}
          </select>
          <div className="bar">
            <button className="b" disabled={busy || !invoiceId} onClick={exportXml}>
              Generează XML
            </button>
          </div>
        </div>
      )}
      <table className="grid">
        <thead>
          <tr>
            <th>ID e-Factura</th>
            <th>Sens</th>
            <th>Statut</th>
            <th>Actualizat</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {messages.map((m) => (
            <tr key={m.id}>
              <td>{m.efactura_id}</td>
              <td>{m.direction === "received" ? "primită" : "emisă"}</td>
              <td>
                {m.direction === "sent" && allowed ? (
                  <select value={m.status ?? "draft"} disabled={busy} onChange={(e) => setStatus(m, e.target.value)}>
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {LABEL[s]}
                      </option>
                    ))}
                  </select>
                ) : (
                  (LABEL[m.status ?? ""] ?? m.status)
                )}
              </td>
              <td>{day(m.synced_at)}</td>
              <td>
                <button className="b" onClick={() => apiDownload(`${base}/messages/${m.id}/xml`, `e-factura-${m.efactura_id}.xml`)}>
                  XML
                </button>
              </td>
            </tr>
          ))}
          {messages.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Nu sunt mesaje e-Factura.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
