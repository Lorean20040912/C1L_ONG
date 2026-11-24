import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { PAYMENT_STATE_LABELS, type PaymentSettlements } from "../../api/treasury";
import { day, money, parseAmount } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { Messages } from "../admin/Messages";

/** „Facturi achitate cu această plată”: legarea unei plăți către furnizor de facturile primite (stingere pe factură). */
export function SettlementsPanel({ orgId, paymentId, editable, onChanged }: { orgId: string; paymentId: string; editable: boolean; onChanged?: () => void }) {
  const [data, setData] = useState<PaymentSettlements | null>(null);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const { busy, error, info, run, setError } = useAction();
  const url = `/organizations/${orgId}/treasury/payments/${paymentId}/settlements`;

  const load = useCallback(() => {
    api<PaymentSettlements>(url).then((d) => {
      setData(d);
      setAmounts(Object.fromEntries(d.items.map((i) => [i.invoice_document_id, money(i.amount)])));
    }, (e: Error) => setError(e.message));
  }, [url, setError]);
  useEffect(load, [load]);

  const total = Object.values(amounts).reduce((s, v) => s + Number(parseAmount(v) ?? 0), 0);
  const save = () =>
    run(async () => {
      const items = Object.entries(amounts)
        .filter(([, v]) => v.trim() !== "")
        .map(([invoice_document_id, v]) => {
          const amount = parseAmount(v);
          if (amount === null) throw new Error("Suma stingerii nu e un număr");
          return { invoice_document_id, amount };
        })
        .filter((i) => Number(i.amount) > 0);
      const d = await api<PaymentSettlements>(url, { method: "PUT", body: { items } });
      setData(d);
      setAmounts(Object.fromEntries(d.items.map((i) => [i.invoice_document_id, money(i.amount)])));
      onChanged?.();
      return items.length ? "Stingerile au fost salvate." : "Plata nu mai este legată de facturi.";
    });
  // propune restul facturii, în limita sumei rămase libere a plății
  const fill = (id: string, remaining: string) => {
    const others = Object.entries(amounts).filter(([k]) => k !== id).reduce((s, [, v]) => s + Number(parseAmount(v) ?? 0), 0);
    const free = Math.max(Number(data?.amount ?? 0) - others, 0);
    setAmounts({ ...amounts, [id]: money(Math.min(free, Number(remaining))) });
  };

  if (!data) return error ? <Messages error={error} info={null} /> : null;
  return (
    <section>
      <h2>Facturile achitate cu această plată</h2>
      <Messages error={error} info={info} />
      <table className="grid edit">
        <thead>
          <tr>
            <th>Factura</th>
            <th>Data</th>
            <th className="num">Total</th>
            <th className="num">Achitat</th>
            <th className="num">Rest</th>
            <th>Starea</th>
            <th className="num">Stinge cu această plată</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.open_invoices.map((i) => (
            <tr key={i.document_id}>
              <td>
                {i.series ?? ""} {i.doc_number}
              </td>
              <td>{day(i.doc_date)}</td>
              <td className="num">{money(i.total)}</td>
              <td className="num">{money(i.paid)}</td>
              <td className="num">{money(i.remaining)}</td>
              <td>{PAYMENT_STATE_LABELS[i.payment_status]}</td>
              <td className="num">
                <input
                  aria-label={`Suma stinsă pe factura ${i.doc_number ?? ""}`}
                  className="num"
                  inputMode="decimal"
                  value={amounts[i.document_id] ?? ""}
                  disabled={!editable || busy}
                  onChange={(e) => setAmounts({ ...amounts, [i.document_id]: e.target.value })}
                />
              </td>
              <td>
                {editable && (
                  <button className="b" disabled={busy} onClick={() => fill(i.document_id, i.remaining)}>
                    Restul
                  </button>
                )}
              </td>
            </tr>
          ))}
          {data.open_invoices.length === 0 && (
            <tr>
              <td colSpan={8} className="muted">
                Furnizorul nu are facturi primite neachitate.
              </td>
            </tr>
          )}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={6}>
              <b>Total stins din {money(data.amount)}</b>
            </td>
            <td className={`num ${total > Number(data.amount) ? "late" : ""}`}>
              <b>{money(total)}</b>
            </td>
            <td />
          </tr>
        </tfoot>
      </table>
      {editable && (
        <div className="bar">
          <button className="b primary" onClick={save} disabled={busy}>
            Salvează stingerile
          </button>
        </div>
      )}
      <p className="footer-note">Factura se consideră achitată doar după înregistrarea plății. Plata nestinsă rămâne ca avans / sold la furnizor.</p>
    </section>
  );
}
