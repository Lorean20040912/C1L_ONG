import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { EXEMPTION_LABELS, type Contract, type ContractType, type Exemption, type Funding, type Person } from "../../api/payroll";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, parseAmount } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

interface Form {
  person_id: string;
  type: ContractType;
  is_main_job: boolean;
  number: string;
  start_date: string;
  end_date: string;
  gross: string;
  special_function_code: string;
  funding: Funding[];
  exemptions: Exemption[];
}

const START = `${new Date().getFullYear()}-01-01`;
const EMPTY: Form = {
  person_id: "",
  type: "cim",
  is_main_job: true,
  number: "",
  start_date: START,
  end_date: "",
  gross: "",
  special_function_code: "",
  funding: [],
  exemptions: [],
};

/** Contractele (CIM / civil) cu repartizarea pe granturi și cererile de scutire (ToR F3.1–F3.3). */
export function ContractsScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<Contract[] | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const { busy, error, info, run } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}`;

  const load = useCallback(() => {
    api<Contract[]>(`${base}/contracts`).then(setRows, () => setRows([]));
    api<Person[]>(`${base}/persons`).then(setPersons, () => setPersons([]));
  }, [base]);
  useEffect(load, [load]);

  const edit = (c: Contract | null) => {
    setEditId(c?.id ?? null);
    setForm(
      c
        ? {
            person_id: c.person_id,
            type: c.type,
            is_main_job: c.is_main_job,
            number: c.number ?? "",
            start_date: c.start_date,
            end_date: c.end_date ?? "",
            gross: c.gross_amount,
            special_function_code: c.special_function_code ?? "",
            funding: c.funding,
            exemptions: c.exemptions,
          }
        : EMPTY,
    );
  };

  const exemptionsAllowed = form.type === "cim" && form.is_main_job;
  const fundingTotal = form.funding.reduce((s, f) => s + Number(f.share_percent || 0), 0);
  const grantCode = (id: string) => catalogs.grants.find((g) => g.id === id)?.code ?? "";

  const setFunding = (i: number, patch: Partial<Funding>) =>
    setForm({ ...form, funding: form.funding.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const setExemption = (i: number, patch: Partial<Exemption>) =>
    setForm({ ...form, exemptions: form.exemptions.map((e, j) => (j === i ? { ...e, ...patch } : e)) });

  const save = () =>
    run(async () => {
      const gross = parseAmount(form.gross);
      if (!form.person_id) throw new Error("Alegeți persoana");
      if (!gross) throw new Error("Indicați salariul / onorariul lunar");
      const body = {
        person_id: form.person_id,
        type: form.type,
        is_main_job: form.type === "cim" && form.is_main_job,
        number: form.number.trim() || null,
        start_date: form.start_date,
        end_date: form.end_date || null,
        gross_amount: gross,
        special_function_code: form.special_function_code.trim() || null,
        funding: form.funding.map((f) => ({ ...f, budget_line_id: f.budget_line_id || null, valid_to: f.valid_to || null })),
        exemptions: exemptionsAllowed ? form.exemptions.map((e) => ({ ...e, valid_to: e.valid_to || null })) : [],
      };
      await api(editId ? `${base}/contracts/${editId}` : `${base}/contracts`, { method: editId ? "PUT" : "POST", body });
      edit(null);
      load();
      return "Contractul a fost salvat.";
    });

  return (
    <>
      <h1>Contracte (CIM și civile)</h1>
      <ReadOnlyNote show={!editable} what="contractele le introduce contabilul" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Persoana</th>
            <th>Tip</th>
            <th>Nr.</th>
            <th>Perioada</th>
            <th className="num">Lunar</th>
            <th>Finanțare</th>
            <th>Scutiri</th>
          </tr>
        </thead>
        <tbody>
          {rows?.map((c) => (
            <tr key={c.id} className={editId === c.id ? "sel" : ""} onDoubleClick={() => editable && edit(c)} onClick={() => editable && edit(c)}>
              <td>{c.person_name}</td>
              <td>{c.type === "cim" ? (c.is_main_job ? "CIM (de bază)" : "CIM (cumul)") : "Contract civil"}</td>
              <td>{c.number}</td>
              <td>
                {day(c.start_date)} – {c.end_date ? day(c.end_date) : "nedeterminat"}
              </td>
              <td className="num">{money(c.gross_amount)}</td>
              <td>{c.funding.map((f) => `${grantCode(f.grant_id)} ${Number(f.share_percent)}%`).join(", ")}</td>
              <td>{c.exemptions.map((e) => EXEMPTION_LABELS[e.kind] ?? e.kind).join(", ")}</td>
            </tr>
          ))}
          {rows?.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                Nu sunt contracte.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {editable && (
        <section>
          <h2>{editId ? "Modificarea contractului" : "Contract nou"}</h2>
          <div className="form">
            <label htmlFor="c-person">Persoana</label>
            <select id="c-person" value={form.person_id} onChange={(e) => setForm({ ...form, person_id: e.target.value })}>
              <option value="">— alegeți —</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name}
                </option>
              ))}
            </select>
            <label htmlFor="c-type">Tipul</label>
            <select id="c-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as ContractType })}>
              <option value="cim">Contract individual de muncă (cod SAL)</option>
              <option value="civil">Contract civil / prestări servicii (cod PL)</option>
            </select>
            {form.type === "cim" && (
              <>
                <label htmlFor="c-main">Locul de muncă de bază</label>
                <input id="c-main" type="checkbox" checked={form.is_main_job} onChange={(e) => setForm({ ...form, is_main_job: e.target.checked })} />
              </>
            )}
            <label htmlFor="c-number">Numărul</label>
            <input id="c-number" value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} />
            <label htmlFor="c-start">De la</label>
            <input id="c-start" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
            <label htmlFor="c-end">Până la</label>
            <input id="c-end" type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
            <label htmlFor="c-gross">{form.type === "cim" ? "Salariul lunar" : "Onorariul lunar"}</label>
            <input id="c-gross" value={form.gross} onChange={(e) => setForm({ ...form, gross: e.target.value })} placeholder="10 000,00" />
            <label htmlFor="c-func">Codul funcției (condiții speciale)</label>
            <input id="c-func" value={form.special_function_code} onChange={(e) => setForm({ ...form, special_function_code: e.target.value })} />
          </div>

          <h2>Repartizarea pe granturi</h2>
          <table className="grid edit">
            <thead>
              <tr>
                <th>Grant</th>
                <th>Linia de buget</th>
                <th className="num">%</th>
                <th>De la</th>
                <th>Până la</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {form.funding.map((f, i) => {
                const grant = catalogs.grants.find((g) => g.id === f.grant_id);
                return (
                  <tr key={i}>
                    <td>
                      <select aria-label="Grant" value={f.grant_id} onChange={(e) => setFunding(i, { grant_id: e.target.value, budget_line_id: null })}>
                        <option value="">—</option>
                        {catalogs.grants.map((g) => (
                          <option key={g.id} value={g.id}>
                            {g.code} {g.title}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select aria-label="Linia de buget" value={f.budget_line_id ?? ""} onChange={(e) => setFunding(i, { budget_line_id: e.target.value || null })}>
                        <option value="">—</option>
                        {grant?.budget_lines.map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.code} {l.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input aria-label="Cota" className="num" value={f.share_percent} onChange={(e) => setFunding(i, { share_percent: e.target.value })} />
                    </td>
                    <td>
                      <input aria-label="De la" type="date" value={f.valid_from} onChange={(e) => setFunding(i, { valid_from: e.target.value })} />
                    </td>
                    <td>
                      <input aria-label="Până la" type="date" value={f.valid_to ?? ""} onChange={(e) => setFunding(i, { valid_to: e.target.value || null })} />
                    </td>
                    <td>
                      <button className="x-btn" aria-label="Șterge rândul" onClick={() => setForm({ ...form, funding: form.funding.filter((_, j) => j !== i) })}>
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="bar">
            <button
              className="b"
              onClick={() =>
                setForm({
                  ...form,
                  funding: [...form.funding, { grant_id: "", budget_line_id: null, share_percent: String(Math.max(0, 100 - fundingTotal)), valid_from: form.start_date, valid_to: null }],
                })
              }
            >
              Adaugă grant
            </button>
            <span className={fundingTotal === 100 ? "muted" : "late"}>Total: {fundingTotal}% (calculul cere 100%, fără dublă finanțare)</span>
          </div>

          <h2>Cereri de scutire</h2>
          {!exemptionsAllowed ? (
            <div className="hint">Scutirile (CF art. 33–35) se acordă doar la contractul individual de muncă de bază.</div>
          ) : (
            <>
              <table className="grid edit">
                <thead>
                  <tr>
                    <th>Tipul</th>
                    <th className="num">Persoane întreținute</th>
                    <th>De la</th>
                    <th>Până la</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {form.exemptions.map((e, i) => (
                    <tr key={i}>
                      <td>
                        <select aria-label="Tipul scutirii" value={e.kind} onChange={(ev) => setExemption(i, { kind: ev.target.value })}>
                          {Object.entries(EXEMPTION_LABELS).map(([k, v]) => (
                            <option key={k} value={k}>
                              {v}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          aria-label="Numărul persoanelor"
                          className="num"
                          type="number"
                          min={0}
                          value={e.dependents_count}
                          disabled={e.kind === "personal" || e.kind === "major_personal"}
                          onChange={(ev) => setExemption(i, { dependents_count: Number(ev.target.value) })}
                        />
                      </td>
                      <td>
                        <input aria-label="De la" type="date" value={e.valid_from} onChange={(ev) => setExemption(i, { valid_from: ev.target.value })} />
                      </td>
                      <td>
                        <input aria-label="Până la" type="date" value={e.valid_to ?? ""} onChange={(ev) => setExemption(i, { valid_to: ev.target.value || null })} />
                      </td>
                      <td>
                        <button className="x-btn" aria-label="Șterge rândul" onClick={() => setForm({ ...form, exemptions: form.exemptions.filter((_, j) => j !== i) })}>
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="bar">
                <button
                  className="b"
                  onClick={() => setForm({ ...form, exemptions: [...form.exemptions, { kind: "personal", dependents_count: 0, valid_from: form.start_date, valid_to: null }] })}
                >
                  Adaugă scutire
                </button>
              </div>
            </>
          )}

          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              Salvează
            </button>
            {editId && (
              <button className="b" onClick={() => edit(null)}>
                Contract nou
              </button>
            )}
          </div>
          <div className="hint">Modificările se aplică lunilor necalculate; lunile calculate rămân înghețate în statul de plată.</div>
        </section>
      )}
    </>
  );
}
