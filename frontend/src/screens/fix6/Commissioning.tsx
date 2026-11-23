import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AssetEvent } from "../../api/fix6";
import type { FixedAsset } from "../../api/types";
import { day, money, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

/** Punerea în funcțiune: mijloacele fixe recepționate, dar încă nepuse în funcțiune; din luna următoare se amortizează. */
export function Commissioning() {
  const { orgId, role } = useShell();
  const [assets, setAssets] = useState<FixedAsset[]>([]);
  const [events, setEvents] = useState<AssetEvent[]>([]);
  const [assetId, setAssetId] = useState("");
  const [date, setDate] = useState(today());
  const [life, setLife] = useState("");
  const [note, setNote] = useState("");
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}`;

  const load = useCallback(() => {
    Promise.all([api<FixedAsset[]>(`${base}/fixed-assets`), api<AssetEvent[]>(`${base}/fixed-asset-events?kind=commissioning`)])
      .then(([a, e]) => {
        setAssets(a.filter((x) => x.status === "suspended"));
        setEvents(e);
      })
      .catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const selected = assets.find((a) => a.id === assetId);

  const post = () =>
    run(async () => {
      if (!assetId) throw new Error("Alegeți mijlocul fix");
      const months = life.trim() ? Number(life) : selected?.useful_life_months;
      if (!months || !Number.isInteger(months) || months <= 0) throw new Error("Durata se scrie în luni întregi, mai mare decât zero");
      await api(`${base}/fixed-assets/${assetId}/commissioning`, {
        method: "POST",
        body: { commissioning_date: date, useful_life_months: months, note: note.trim() || null },
      });
      setAssetId("");
      setLife("");
      setNote("");
      load();
      return "Mijlocul fix a fost pus în funcțiune; amortizarea începe din luna următoare.";
    });

  const cancel = (e: AssetEvent) =>
    run(async () => {
      await api(`${base}/fixed-asset-events/${e.id}/cancel-commissioning`, { method: "POST" });
      load();
      return `Punerea în funcțiune a ${e.inventory_no} a fost anulată.`;
    });

  return (
    <>
      <h1>Punere în funcțiune</h1>
      <ReadOnlyNote show={!editable} what="punerea în funcțiune o fac contabilul sau contabilul-șef" />
      <Messages error={error} info={info} />
      {editable && (
        <section>
          <h2>Document nou</h2>
          <div className="form">
            <label htmlFor="c-asset">Mijlocul fix</label>
            <select id="c-asset" value={assetId} onChange={(e) => setAssetId(e.target.value)}>
              <option value="">— alegeți —</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.inventory_no} {a.name} ({money(a.initial_cost)})
                </option>
              ))}
            </select>
            <label htmlFor="c-date">Data punerii în funcțiune</label>
            <input id="c-date" type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
            <label htmlFor="c-life">Durata de utilizare, luni</label>
            <input
              id="c-life"
              className="num"
              inputMode="numeric"
              value={life}
              placeholder={selected?.useful_life_months ? String(selected.useful_life_months) : ""}
              onChange={(e) => setLife(e.target.value)}
            />
            <label htmlFor="c-note">Observații</label>
            <input id="c-note" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          {assets.length === 0 && <div className="hint">Nu sunt mijloace fixe în așteptarea punerii în funcțiune.</div>}
          <div className="bar">
            <button className="b primary" onClick={post} disabled={busy || !assetId}>
              Pune în funcțiune
            </button>
          </div>
        </section>
      )}
      <h2>Documente</h2>
      <table className="grid">
        <thead>
          <tr>
            <th>Data</th>
            <th>Nr. inventar</th>
            <th>Denumirea</th>
            <th>Observații</th>
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
              <td colSpan={6} className="muted">
                Nu sunt documente de punere în funcțiune.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
