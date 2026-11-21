import { useCallback, useEffect, useState } from "react";
import { api, downloadFile } from "../../api/client";
import type { BankFormat, PaymentBatch, PaymentOrder } from "../../api/types";
import { useCatalogs } from "../../catalog/useCatalogs";
import { useAction } from "../../lib/useAction";
import { day, money } from "../../lib/format";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** Exportul ordinelor de plată în bancă: loturi pe bancă și cont plătitor, cu descărcarea fișierului. */
export function PaymentExportScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [orders, setOrders] = useState<PaymentOrder[]>([]);
  const [batches, setBatches] = useState<PaymentBatch[]>([]);
  const [formats, setFormats] = useState<BankFormat[]>([]);
  const [formatId, setFormatId] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [force, setForce] = useState(false);
  const { busy, error, info, run } = useAction();
  const allowed = can(role, POSTING_ROLES);

  const load = useCallback(() => {
    api<PaymentOrder[]>(`/organizations/${orgId}/payment-orders`)
      .then((rows) => setOrders(rows.filter((o) => o.direction === "outgoing" && !o.is_posted)))
      .catch(() => {});
    api<PaymentBatch[]>(`/organizations/${orgId}/payment-batches`).then(setBatches).catch(() => {});
  }, [orgId]);

  useEffect(() => {
    load();
    api<BankFormat[]>(`/organizations/${orgId}/bank-formats?direction=export`).then(setFormats).catch(() => {});
  }, [orgId, load]);

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const exportNow = () =>
    run(async () => {
      if (!formatId || picked.size === 0) throw new Error("Alegeți formatul băncii și cel puțin un ordin");
      const created = await api<PaymentBatch[]>(`/organizations/${orgId}/payment-batches`, {
        method: "POST",
        body: { document_ids: [...picked], format_id: formatId, force },
      });
      setPicked(new Set());
      load();
      return `Au fost create ${created.length} loturi (${created.reduce((s, b) => s + (b.orders_count ?? 0), 0)} ordine).`;
    });

  const account = (id: string) => catalogs.bankAccounts.find((b) => b.id === id)?.iban ?? "";

  return (
    <>
      <h1>Export ordine de plată</h1>
      <Messages error={error} info={info} />
      {allowed && (
        <div className="bar">
          <select aria-label="Formatul băncii" value={formatId} onChange={(e) => setFormatId(e.target.value)}>
            <option value="">Formatul băncii…</option>
            {formats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.bank_name} ({f.file_type})
              </option>
            ))}
          </select>
          <label>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> exportă din nou cele exportate
          </label>
          <button className="b primary" disabled={busy || picked.size === 0} onClick={exportNow}>
            Exportă în bancă ({picked.size})
          </button>
        </div>
      )}
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 24 }} />
            <th>Număr</th>
            <th>Data</th>
            <th>Beneficiar</th>
            <th className="num">Suma</th>
            <th>Valuta</th>
            <th>Stare bancă</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.document_id}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`Ordin ${o.doc_number ?? ""}`}
                  checked={picked.has(o.document_id)}
                  onChange={() => toggle(o.document_id)}
                />
              </td>
              <td>{o.doc_number}</td>
              <td>{day(o.doc_date)}</td>
              <td>{o.beneficiary_name}</td>
              <td className="num">{money(o.amount)}</td>
              <td>{o.currency}</td>
              <td>{o.bank_status}</td>
            </tr>
          ))}
          {orders.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                Nu sunt ordine de plată de exportat.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <section>
        <h2>Loturi exportate</h2>
        <table className="grid">
          <thead>
            <tr>
              <th>Data</th>
              <th>Cont plătitor</th>
              <th>Fișier</th>
              <th className="num">Ordine</th>
              <th className="num">Total</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.id}>
                <td>{day(b.created_at)}</td>
                <td>{account(b.bank_account_id)}</td>
                <td>{b.file_name}</td>
                <td className="num">{b.orders_count}</td>
                <td className="num">{money(b.total_amount)}</td>
                <td>
                  <button
                    className="b"
                    onClick={() =>
                      run(() => downloadFile(`/organizations/${orgId}/payment-batches/${b.id}/file`, b.file_name ?? "export.txt"))
                    }
                  >
                    Descarcă
                  </button>
                </td>
              </tr>
            ))}
            {batches.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Nu sunt loturi.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
