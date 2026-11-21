import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Period } from "../../api/types";
import { day } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "./Messages";

const MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"];

/** Perioadele: luna închisă nu mai primește înregistrări; redeschiderea cere motiv și rămâne în audit. */
export function PeriodsScreen() {
  const { orgId, role } = useShell();
  const [year, setYear] = useState(new Date().getFullYear());
  const [periods, setPeriods] = useState<Period[] | null>(null);
  const [reopening, setReopening] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const { busy, error, info, run } = useAction();
  const editable = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/periods`;

  const load = useCallback(() => api<Period[]>(`${base}?year=${year}`).then(setPeriods), [base, year]);

  useEffect(() => {
    load();
  }, [load]);

  const close = (month: number) =>
    run(async () => {
      await api(`${base}/${year}/${month}/close`, { method: "POST" });
      await load();
      return `Luna ${MONTHS[month - 1]} ${year} a fost închisă.`;
    });

  const reopen = (month: number) =>
    run(async () => {
      await api(`${base}/${year}/${month}/reopen`, { method: "POST", body: { reason: reason.trim() } });
      setReopening(null);
      setReason("");
      await load();
      return `Luna ${MONTHS[month - 1]} ${year} a fost redeschisă.`;
    });

  return (
    <>
      <h1>Perioade închise</h1>
      <ReadOnlyNote show={!editable} what="perioadele le închide contabilul-șef" />
      <Messages error={error} info={info} />
      <div className="bar">
        <button className="b" onClick={() => setYear((y) => y - 1)} aria-label="Anul anterior">
          ←
        </button>
        <b>{year}</b>
        <button className="b" onClick={() => setYear((y) => y + 1)} aria-label="Anul următor">
          →
        </button>
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th>Luna</th>
            <th>Statut</th>
            <th>Închisă de</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {periods?.map((p) => (
            <tr key={p.month}>
              <td>{MONTHS[p.month - 1]}</td>
              <td>{p.is_closed ? <span className="late">🔒 închisă</span> : <span className="ok">deschisă</span>}</td>
              <td>{p.is_closed ? `${p.closed_by_name ?? ""}, ${day(p.closed_at)}` : ""}</td>
              <td>
                {editable && !p.is_closed && (
                  <button className="b" onClick={() => close(p.month)} disabled={busy}>
                    Închide
                  </button>
                )}
                {editable && p.is_closed && reopening !== p.month && (
                  <button className="b" onClick={() => setReopening(p.month)} disabled={busy}>
                    Redeschide…
                  </button>
                )}
                {reopening === p.month && (
                  <span className="pair">
                    <input aria-label="Motivul redeschiderii" placeholder="Motivul (obligatoriu)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 220 }} />
                    <button className="b primary" onClick={() => reopen(p.month)} disabled={busy || reason.trim().length < 3}>
                      Redeschide
                    </button>
                    <button className="b" onClick={() => setReopening(null)}>
                      Renunță
                    </button>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
