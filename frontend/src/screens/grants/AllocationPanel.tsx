import { useState } from "react";
import { api } from "../../api/client";
import type { MonthClose, StepPreview } from "../../api/types";
import { useCatalogs } from "../../catalog/useCatalogs";
import { useShell } from "../../shell/tabs";

interface Props {
  base: string; // /organizations/{id}/month-close/{an}/{luna}
  busy: boolean;
  run: (action: () => Promise<void>) => Promise<void>;
  onState: (state: MonthClose) => void;
  onPreview: (preview: StepPreview) => void;
}

/** Parametrii pasului „Repartizarea cheltuielilor pe granturi”: contul cheltuielilor comune și coeficienții pe linii. */
export function AllocationPanel({ base, busy, run, onState, onPreview }: Props) {
  const { orgId } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [accountId, setAccountId] = useState("");
  const [coefficients, setCoefficients] = useState<Record<string, string>>({});

  const params = () => {
    const lines = Object.entries(coefficients)
      .filter(([, v]) => Number(v.replace(",", ".")) > 0)
      .map(([id, v]) => ({ budget_line_id: id, coefficient: v.replace(",", ".") }));
    if (!accountId) throw new Error("Alegeți contul cheltuielilor comune");
    if (lines.length === 0) throw new Error("Introduceți coeficientul pentru cel puțin o linie de buget");
    return { source_account_id: accountId, lines };
  };

  return (
    <section>
      <h2>Repartizarea cheltuielilor comune</h2>
      <div className="hint">
        Cheltuielile lunii înregistrate pe contul ales, fără proiect, se repartizează proporțional cu coeficienții (pontaj, %): Dt 716 — Kt contul ales.
      </div>
      <div className="form">
        <label htmlFor="al-acc">Contul cheltuielilor comune</label>
        <select id="al-acc" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">— alegeți —</option>
          {catalogs.accounts
            .filter((a) => !a.is_group && /^7/.test(a.code))
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} {a.name}
              </option>
            ))}
        </select>
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th>Grant / linie de buget</th>
            <th className="num">Coeficient</th>
          </tr>
        </thead>
        <tbody>
          {catalogs.grants
            .filter((g) => !g.is_closed)
            .flatMap((g) =>
              g.budget_lines.map((l) => (
                <tr key={l.id}>
                  <td>
                    {g.code} / {l.code} {l.name}
                  </td>
                  <td className="num">
                    <input
                      aria-label={`Coeficient ${g.code} ${l.code}`}
                      value={coefficients[l.id] ?? ""}
                      onChange={(e) => setCoefficients({ ...coefficients, [l.id]: e.target.value })}
                      size={8}
                    />
                  </td>
                </tr>
              )),
            )}
        </tbody>
      </table>
      <div className="bar">
        <button className="b" disabled={busy} onClick={() => run(async () => onPreview(await api<StepPreview>(`${base}/allocation/preview`, { method: "POST", body: params() })))}>
          Previzualizare
        </button>
        <button className="b primary" disabled={busy} onClick={() => run(async () => onState(await api<MonthClose>(`${base}/allocation/run`, { method: "POST", body: params() })))}>
          Execută repartizarea
        </button>
      </div>
    </section>
  );
}
