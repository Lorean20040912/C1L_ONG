import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { TrancheRow } from "../../api/fix6";
import type { PaymentOrder } from "../../api/types";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const STATUS: Record<string, string> = { planned: "planificată", recognized: "recunoscută (creanță)", received: "încasată", cancelled: "anulată" };

/** Finanțare primită: tranșele tuturor granturilor — recunoaștere și legarea de încasarea din bancă. */
export function FundingReceived() {
  const { orgId, role, openTab } = useShell();
  const [rows, setRows] = useState<TrancheRow[] | null>(null);
  const [incoming, setIncoming] = useState<PaymentOrder[]>([]);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}`;

  const load = useCallback(() => {
    Promise.all([api<TrancheRow[]>(`${base}/tranches`), api<PaymentOrder[]>(`${base}/payment-orders`)])
      .then(([t, p]) => {
        setRows(t);
        setIncoming(p.filter((x) => x.direction === "incoming" && x.is_posted));
      })
      .catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const act = (t: TrancheRow, path: string, body: unknown, done: string) =>
    run(async () => {
      await api(`${base}/tranches/${t.id}/${path}`, { method: "POST", body });
      load();
      return done;
    });

  const receive = (t: TrancheRow) => {
    const doc = pick[t.id];
    if (!doc) {
      setError("Alegeți încasarea înregistrată din bancă");
      return;
    }
    return act(t, "receive", { document_id: doc }, `Tranșa ${t.grant_code} / ${t.number} este marcată ca încasată.`);
  };

  const visible = (rows ?? []).filter((t) => !filter || t.status === filter);
  const open = (t: TrancheRow) => openTab({ id: "grant-advanced", title: "Versiuni și tranșe", kind: "grant-advanced", params: { grantId: t.grant_id } });
  const totals = new Map<string, number>();
  for (const t of visible) if (t.status !== "cancelled") totals.set(t.currency, (totals.get(t.currency) ?? 0) + Number(t.amount));

  return (
    <>
      <h1>Finanțare primită</h1>
      <ReadOnlyNote show={!editable} what="finanțarea o înregistrează contabilul" />
      <div className="bar">
        <label>
          Starea{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Starea">
            <option value="">toate</option>
            {Object.entries(STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Grant</th>
            <th>Donator</th>
            <th>Tranșa</th>
            <th>Data planificată</th>
            <th className="num">Suma</th>
            <th>Starea</th>
            <th>Încasarea</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {visible.map((t) => (
            <tr key={t.id}>
              <td>
                <button className="link" onClick={() => open(t)}>
                  {t.grant_code}
                </button>
              </td>
              <td>{t.donor_name}</td>
              <td>{t.number}</td>
              <td>{day(t.planned_date)}</td>
              <td className="num">
                {money(t.amount)} {t.currency}
              </td>
              <td>{STATUS[t.status] ?? t.status}</td>
              <td>
                {t.status === "received" ? (
                  day(t.received_date)
                ) : editable && (t.status === "planned" || t.status === "recognized") ? (
                  <span className="pair">
                    <select aria-label={`Încasarea tranșei ${t.number} ${t.grant_code}`} value={pick[t.id] ?? ""} onChange={(e) => setPick((p) => ({ ...p, [t.id]: e.target.value }))}>
                      <option value="">— alegeți —</option>
                      {incoming.map((p) => (
                        <option key={p.document_id} value={p.document_id}>
                          {day(p.doc_date)} {p.doc_number} · {money(p.amount)} {p.currency}
                        </option>
                      ))}
                    </select>
                    <button className="b" onClick={() => receive(t)} disabled={busy}>
                      Leagă
                    </button>
                  </span>
                ) : null}
              </td>
              <td>
                {editable && t.status === "planned" && (
                  <button className="b" onClick={() => act(t, "recognize", {}, "Tranșa a fost recunoscută ca venit.")} disabled={busy}>
                    Recunoaște
                  </button>
                )}
                {editable && t.status === "recognized" && (
                  <button className="b" onClick={() => act(t, "unrecognize", undefined, "Recunoașterea a fost anulată.")} disabled={busy}>
                    Anulează recunoașterea
                  </button>
                )}
              </td>
            </tr>
          ))}
          {rows && visible.length === 0 && (
            <tr>
              <td colSpan={8} className="muted">
                Nu sunt tranșe. Tranșele se planifică în „Versiuni și tranșe”.
              </td>
            </tr>
          )}
        </tbody>
        {totals.size > 0 && (
          <tfoot>
            {[...totals.entries()].map(([cur, sum]) => (
              <tr key={cur}>
                <td colSpan={4}>Total ({cur})</td>
                <td className="num">{money(sum)}</td>
                <td colSpan={3} />
              </tr>
            ))}
          </tfoot>
        )}
      </table>
    </>
  );
}
