import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { FixedAsset } from "../api/types";
import { grantLabel, useCatalogs } from "../catalog/useCatalogs";
import { onDocumentsChanged } from "../lib/events";
import { day, money } from "../lib/format";
import { useShell } from "../shell/tabs";

/** Fișa mijloacelor fixe: valoarea, amortizarea acumulată, valoarea de bilanț; durata se completează aici. */
export function FixedAssets() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<FixedAsset[] | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api<FixedAsset[]>(`/organizations/${orgId}/fixed-assets`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [orgId]);

  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("invoices", load), [load]);

  async function saveLife(asset: FixedAsset) {
    const months = Number(edits[asset.id]);
    if (!Number.isInteger(months) || months <= 0) {
      setError("Durata se scrie în luni întregi, mai mare decât zero");
      return;
    }
    setError(null);
    try {
      const updated = await api<FixedAsset>(`/organizations/${orgId}/fixed-assets/${asset.id}`, {
        method: "PATCH",
        body: { useful_life_months: months },
      });
      setRows((rs) => rs?.map((r) => (r.id === updated.id ? updated : r)) ?? null);
      setEdits(({ [asset.id]: _, ...rest }) => rest);
      setInfo(`${asset.inventory_no}: durata ${months} luni salvată.`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const openInvoice = (a: FixedAsset) =>
    a.document_id &&
    openTab({ id: `invoice:${a.document_id}`, title: "Factură primită", kind: "invoice", params: { documentId: a.document_id } });

  return (
    <>
      <h1>Fișa mijloacelor fixe</h1>
      <div className="bar">
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {info && <div className="hint">{info}</div>}
      {rows?.some((r) => !r.useful_life_months && r.status === "in_use") && (
        <div className="hint warn">Mijloacele fixe fără durată de utilizare nu se pot amortiza; completați durata în luni.</div>
      )}
      {rows && (
        <table className="grid">
          <thead>
            <tr>
              <th>Nr. inventar</th>
              <th>Denumirea</th>
              <th>Punere în funcțiune</th>
              <th>Durata, luni</th>
              <th className="num">Valoarea inițială</th>
              <th className="num">Amortizarea acumulată</th>
              <th className="num">Valoarea de bilanț</th>
              <th>Grant</th>
              <th>Factura</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => {
              const editing = a.id in edits;
              return (
                <tr key={a.id}>
                  <td>{a.inventory_no}</td>
                  <td>{a.name}</td>
                  <td>{a.status === "in_use" ? day(a.commissioning_date) : <span className="muted">nepus în funcțiune</span>}</td>
                  <td>
                    {editing || !a.useful_life_months ? (
                      <span className="pair">
                        <input
                          aria-label={`Durata ${a.inventory_no}`}
                          className="num short"
                          inputMode="numeric"
                          value={edits[a.id] ?? ""}
                          onChange={(e) => setEdits((x) => ({ ...x, [a.id]: e.target.value }))}
                          onKeyDown={(e) => e.key === "Enter" && saveLife(a)}
                        />
                        <button className="b" onClick={() => saveLife(a)} disabled={!edits[a.id]}>
                          Salvează
                        </button>
                      </span>
                    ) : (
                      <button className="link" onClick={() => setEdits((x) => ({ ...x, [a.id]: String(a.useful_life_months) }))}>
                        {a.useful_life_months}
                      </button>
                    )}
                  </td>
                  <td className="num">{money(a.initial_cost)}</td>
                  <td className="num">{money(a.accumulated)}</td>
                  <td className="num">{money(a.book_value)}</td>
                  <td>{grantLabel(catalogs.grants, a.grant_id)}</td>
                  <td>
                    {a.document_id && (
                      <button className="link" onClick={() => openInvoice(a)}>
                        deschide
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="muted">
                  Nu sunt mijloace fixe. Fișele se creează din rândurile „Mijloc fix” ale facturilor primite.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </>
  );
}
