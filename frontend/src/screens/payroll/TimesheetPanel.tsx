import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAction } from "../../lib/useAction";
import { Messages } from "../admin/Messages";

interface PayrollInput {
  contract_id: string;
  person_name: string;
  contract_type: "cim" | "civil";
  contract_number: string | null;
  working_days: number;
  worked_days: number | null;
  sick_benefit: string;
}

/** Pontajul (zile lucrate, CIM) și indemnizația de boală pe luna aleasă; se aplică la următorul calcul. */
export function TimesheetPanel({ orgId, year, month, editable }: { orgId: string; year: number; month: number; editable: boolean }) {
  const [rows, setRows] = useState<PayrollInput[]>([]);
  const [draft, setDraft] = useState<Record<string, { days: string; sick: string }>>({});
  const { busy, error, info, run } = useAction();
  const base = `/organizations/${orgId}/payroll-inputs/${year}/${month}`;

  const load = useCallback(() => {
    api<PayrollInput[]>(base).then(
      (r) => {
        setRows(r);
        setDraft(Object.fromEntries(r.map((x) => [x.contract_id, { days: x.worked_days === null ? "" : String(x.worked_days), sick: x.sick_benefit }])));
      },
      () => setRows([]),
    );
  }, [base]);
  useEffect(load, [load]);

  const save = (r: PayrollInput) =>
    run(async () => {
      const d = draft[r.contract_id];
      await api(`${base}/${r.contract_id}`, {
        method: "PUT",
        body: { worked_days: d.days === "" ? null : Number(d.days), sick_benefit: d.sick || "0" },
      });
      load();
      return "Salvat; refaceți calculul salariului pentru a-l aplica.";
    });

  if (rows.length === 0) return null;
  return (
    <section>
      <h2>Pontaj și indemnizații de boală</h2>
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Persoana</th>
            <th>Contract</th>
            <th className="num">Zile lucrătoare</th>
            <th>Zile lucrate (CIM)</th>
            <th>Indemnizație boală</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.contract_id}>
              <td>{r.person_name}</td>
              <td>{r.contract_number ?? r.contract_type}</td>
              <td className="num">{r.working_days}</td>
              <td>
                {r.contract_type === "cim" && (
                  <input
                    aria-label="Zile lucrate"
                    size={4}
                    disabled={!editable}
                    value={draft[r.contract_id]?.days ?? ""}
                    onChange={(e) => setDraft({ ...draft, [r.contract_id]: { ...draft[r.contract_id], days: e.target.value } })}
                  />
                )}
              </td>
              <td>
                <input
                  aria-label="Indemnizație de boală"
                  size={8}
                  disabled={!editable}
                  value={draft[r.contract_id]?.sick ?? ""}
                  onChange={(e) => setDraft({ ...draft, [r.contract_id]: { ...draft[r.contract_id], sick: e.target.value } })}
                />
              </td>
              <td>
                {editable && (
                  <button className="b" disabled={busy} onClick={() => save(r)}>
                    Salvează
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
