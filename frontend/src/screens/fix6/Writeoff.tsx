import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AssetEvent } from "../../api/fix6";
import type { FixedAsset } from "../../api/types";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

/** Casarea mijloacelor fixe: Dt amortizarea acumulată — Kt mijlocul fix; valoarea rămasă — Dt contul de cheltuieli. */
export function Writeoff() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [assets, setAssets] = useState<FixedAsset[]>([]);
  const [events, setEvents] = useState<AssetEvent[]>([]);
  const [assetId, setAssetId] = useState("");
  const [date, setDate] = useState(today());
  const [reason, setReason] = useState("");
  const [lossAccount, setLossAccount] = useState("");
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}`;

  const load = useCallback(() => {
    Promise.all([api<FixedAsset[]>(`${base}/fixed-assets`), api<AssetEvent[]>(`${base}/fixed-asset-events?kind=writeoff`)])
      .then(([a, e]) => {
        setAssets(a.filter((x) => x.status !== "written_off"));
        setEvents(e);
      })
      .catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const selected = assets.find((a) => a.id === assetId);
  const needsLoss = selected !== undefined && Number(selected.book_value) > 0;

  const post = () =>
    run(async () => {
      if (!assetId) throw new Error("Alegeți mijlocul fix");
      if (reason.trim().length < 3) throw new Error("Indicați motivul casării");
      if (needsLoss && !lossAccount) throw new Error("Alegeți contul de cheltuieli pentru valoarea de bilanț rămasă");
      await api(`${base}/fixed-assets/${assetId}/writeoff`, {
        method: "POST",
        body: { writeoff_date: date, reason: reason.trim(), loss_account_id: lossAccount || null },
      });
      setAssetId("");
      setReason("");
      load();
      return "Mijlocul fix a fost casat și înregistrat contabil.";
    });

  const cancel = (e: AssetEvent) =>
    run(async () => {
      await api(`${base}/fixed-asset-events/${e.id}/cancel-writeoff`, { method: "POST" });
      load();
      return `Casarea ${e.inventory_no} a fost anulată.`;
    });

  return (
    <>
      <h1>Casare</h1>
      <ReadOnlyNote show={!editable} what="casarea o fac contabilul sau contabilul-șef" />
      <Messages error={error} info={info} />
      {editable && (
        <section>
          <h2>Act de casare nou</h2>
          <div className="form">
            <label htmlFor="w-asset">Mijlocul fix</label>
            <select id="w-asset" value={assetId} onChange={(e) => setAssetId(e.target.value)}>
              <option value="">— alegeți —</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.inventory_no} {a.name}
                </option>
              ))}
            </select>
            <label htmlFor="w-date">Data casării</label>
            <input id="w-date" type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
            <label htmlFor="w-reason">Motivul</label>
            <input id="w-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="uzură, pierdere, deteriorare…" />
            {selected && (
              <>
                <span>Valoarea de bilanț</span>
                <span>
                  {money(selected.book_value)} (inițială {money(selected.initial_cost)}, amortizare {money(selected.accumulated)})
                </span>
              </>
            )}
            {needsLoss && (
              <>
                <label htmlFor="w-loss">Cont de cheltuieli</label>
                <select id="w-loss" value={lossAccount} onChange={(e) => setLossAccount(e.target.value)}>
                  <option value="">— alegeți —</option>
                  {catalogs.accounts
                    .filter((a) => /^[67]/.test(a.code) && !a.is_group)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.code} {a.name}
                      </option>
                    ))}
                </select>
              </>
            )}
          </div>
          <div className="bar">
            <button className="b primary" onClick={post} disabled={busy || !assetId}>
              Casează și înregistrează
            </button>
          </div>
        </section>
      )}
      <h2>Acte de casare</h2>
      <table className="grid">
        <thead>
          <tr>
            <th>Data</th>
            <th>Nr. inventar</th>
            <th>Denumirea</th>
            <th>Motivul</th>
            <th className="num">Valoare rămasă</th>
            <th>Starea</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td>{day(e.event_date)}</td>
              <td>{e.inventory_no}</td>
              <td>{e.asset_name}</td>
              <td>{e.reason}</td>
              <td className="num">{money(e.amount)}</td>
              <td>{e.status === "posted" ? "înregistrat" : "anulat"}</td>
              <td>
                {editable && e.status === "posted" && (
                  <button className="b" onClick={() => cancel(e)} disabled={busy}>
                    Anulează
                  </button>
                )}
              </td>
            </tr>
          ))}
          {events.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                Nu sunt acte de casare.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
