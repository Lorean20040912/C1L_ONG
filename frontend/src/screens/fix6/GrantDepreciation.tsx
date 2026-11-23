import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { FixedAsset } from "../../api/types";
import { grantLabel, useCatalogs } from "../../catalog/useCatalogs";
import { money } from "../../lib/format";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** Amortizarea pe granturi: valoarea mijloacelor fixe finanțate din fiecare grant și amortizarea acumulată. */
export function GrantDepreciation() {
  const { orgId } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [assets, setAssets] = useState<FixedAsset[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<FixedAsset[]>(`/organizations/${orgId}/fixed-assets`)
      .then(setAssets)
      .catch((e: Error) => setError(e.message));
  }, [orgId]);

  const groups = useMemo(() => {
    const by = new Map<string, FixedAsset[]>();
    for (const a of assets ?? []) {
      const key = a.grant_id ?? "";
      by.set(key, [...(by.get(key) ?? []), a]);
    }
    return [...by.entries()].sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
  }, [assets]);

  const sum = (rows: FixedAsset[], f: (a: FixedAsset) => number) => rows.reduce((s, a) => s + f(a), 0);
  const monthly = (a: FixedAsset) =>
    a.status === "in_use" && a.useful_life_months ? (Number(a.initial_cost) - Number(a.residual_value ?? 0)) / a.useful_life_months : 0;

  return (
    <>
      <h1>Amortizarea pe granturi</h1>
      <Messages error={error} info={null} />
      <div className="hint">Amortizarea mijloacelor fixe din grant diminuează fondul (Dt 341.2 — Kt 124); cea lunară e orientativă, calculul exact se face la închiderea lunii.</div>
      <table className="grid">
        <thead>
          <tr>
            <th>Grant / mijloc fix</th>
            <th className="num">Valoarea inițială</th>
            <th className="num">Amortizarea acumulată</th>
            <th className="num">Valoarea de bilanț</th>
            <th className="num">Amortizare lunară (orientativ)</th>
          </tr>
        </thead>
        <tbody>
          {groups.flatMap(([grantId, rows]) => [
            <tr key={`g:${grantId}`}>
              <td>
                <b>{grantId ? grantLabel(catalogs.grants, grantId) || "Grant" : "Fără grant (surse proprii)"}</b>
              </td>
              <td className="num">
                <b>{money(sum(rows, (a) => Number(a.initial_cost)))}</b>
              </td>
              <td className="num">
                <b>{money(sum(rows, (a) => Number(a.accumulated)))}</b>
              </td>
              <td className="num">
                <b>{money(sum(rows, (a) => Number(a.book_value)))}</b>
              </td>
              <td className="num">
                <b>{money(sum(rows, monthly))}</b>
              </td>
            </tr>,
            ...rows.map((a) => (
              <tr key={a.id}>
                <td>
                  &nbsp;&nbsp;{a.inventory_no} {a.name}
                </td>
                <td className="num">{money(a.initial_cost)}</td>
                <td className="num">{money(a.accumulated)}</td>
                <td className="num">{money(a.book_value)}</td>
                <td className="num">{monthly(a) ? money(monthly(a)) : <span className="muted">—</span>}</td>
              </tr>
            )),
          ])}
          {assets && assets.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Nu sunt mijloace fixe.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
