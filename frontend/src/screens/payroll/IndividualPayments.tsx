import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { IndividualPayment, PaymentKind, Person } from "../../api/payroll";
import { budgetLineLabel, useCatalogs } from "../../catalog/useCatalogs";
import { notifyDocumentsChanged, onDocumentsChanged } from "../../lib/events";
import { day, money, parseAmount, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";
import { BudgetLineSelect } from "../BudgetLineSelect";
import { StatusIcon } from "../StatusIcon";

const ROUTE = "individual-payments";

/** „Plată către persoană fizică” (docs/05 §2): chirie FOL, arendă PLs, servicii PL, donație DON pf... — intră automat în IPC21. */
export function IndividualPayments() {
  const { orgId, role, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<IndividualPayment[] | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [kinds, setKinds] = useState<PaymentKind[]>([]);
  const [editing, setEditing] = useState<IndividualPayment | null>(null);
  const [form, setForm] = useState({ doc_number: "", person_id: "", payment_kind: "rent", accrual_date: today(), gross: "", budget_line_id: "" });
  const { busy, error, info, run } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/${ROUTE}`;

  const load = useCallback(() => {
    api<IndividualPayment[]>(base).then(setRows, () => setRows([]));
    api<Person[]>(`/organizations/${orgId}/persons`).then(setPersons, () => setPersons([]));
    api<PaymentKind[]>(`${base}/kinds`).then(setKinds, () => setKinds([]));
  }, [base, orgId]);
  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged(ROUTE, load), [load]);

  const edit = (p: IndividualPayment | null) => {
    setEditing(p);
    setForm(
      p
        ? { doc_number: p.doc_number ?? "", person_id: p.person_id, payment_kind: p.payment_kind, accrual_date: p.accrual_date, gross: p.gross, budget_line_id: p.budget_line_id ?? "" }
        : { doc_number: "", person_id: "", payment_kind: "rent", accrual_date: today(), gross: "", budget_line_id: "" },
    );
  };

  const save = (andPost: boolean) =>
    run(async () => {
      const gross = parseAmount(form.gross);
      if (!gross) throw new Error("Indicați suma brută");
      const body = { ...form, gross, version: editing?.version ?? null };
      const saved = await api<IndividualPayment>(editing ? `${base}/${editing.document_id}` : base, { method: editing ? "PUT" : "POST", body });
      if (andPost) await api(`${base}/${saved.document_id}/post`, { method: "POST" });
      notifyDocumentsChanged(ROUTE);
      edit(null);
      return andPost ? "Plata a fost înregistrată." : "Plata a fost salvată.";
    });

  const toggle = (p: IndividualPayment) =>
    run(async () => {
      await api(`${base}/${p.document_id}/${p.is_posted ? "unpost" : "post"}`, { method: "POST" });
      notifyDocumentsChanged(ROUTE);
    });

  const dtkt = (p: IndividualPayment) =>
    openTab({ id: `dtkt:${p.document_id}`, title: `Dt/Kt: plata ${p.doc_number ?? ""}`, kind: "dtkt", params: { route: ROUTE, documentId: p.document_id } });
  const kindTitle = (k: string) => kinds.find((x) => x.kind === k)?.title ?? k;

  return (
    <>
      <h1>Plăți către persoane fizice</h1>
      <ReadOnlyNote show={!editable} what="plățile le introduce contabilul" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 24 }} />
            <th>Nr.</th>
            <th>Data</th>
            <th>Persoana</th>
            <th>Tipul</th>
            <th>Cod IPC21</th>
            <th className="num">Brut</th>
            <th className="num">Impozit</th>
            <th className="num">Net</th>
            <th>Linia de buget</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows?.map((p) => (
            <tr key={p.document_id} className={editing?.document_id === p.document_id ? "sel" : ""} onDoubleClick={() => editable && !p.is_posted && edit(p)}>
              <td>
                <StatusIcon posted={!!p.is_posted} />
              </td>
              <td>{p.doc_number}</td>
              <td>{day(p.accrual_date)}</td>
              <td>{p.person_name}</td>
              <td>{kindTitle(p.payment_kind)}</td>
              <td>{p.income_code}</td>
              <td className="num">{money(p.gross)}</td>
              <td className="num">{money(p.income_tax)}</td>
              <td className="num">{money(p.net)}</td>
              <td>{budgetLineLabel(catalogs.grants, p.budget_line_id)}</td>
              <td>
                <button className="b" onClick={() => dtkt(p)}>
                  Dt/Kt
                </button>{" "}
                {editable && (
                  <button className="b" onClick={() => toggle(p)} disabled={busy}>
                    {p.is_posted ? "Anulează" : "Înregistrează"}
                  </button>
                )}
              </td>
            </tr>
          ))}
          {rows?.length === 0 && (
            <tr>
              <td colSpan={11} className="muted">
                Nu sunt plăți către persoane fizice.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {editable && (
        <section>
          <h2>{editing ? `Plata ${editing.doc_number ?? ""}` : "Plată nouă"}</h2>
          <div className="form">
            <label htmlFor="ip-no">Numărul</label>
            <input id="ip-no" value={form.doc_number} onChange={(e) => setForm({ ...form, doc_number: e.target.value })} />
            <label htmlFor="ip-person">Persoana</label>
            <select id="ip-person" value={form.person_id} onChange={(e) => setForm({ ...form, person_id: e.target.value })}>
              <option value="">— alegeți —</option>
              {persons.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name} ({p.idnp_masked})
                </option>
              ))}
            </select>
            <label htmlFor="ip-kind">Tipul plății</label>
            <select id="ip-kind" value={form.payment_kind} onChange={(e) => setForm({ ...form, payment_kind: e.target.value })}>
              {kinds.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.title} — {k.income_code}
                </option>
              ))}
            </select>
            <label htmlFor="ip-date">Data calculării</label>
            <input id="ip-date" type="date" value={form.accrual_date} onChange={(e) => setForm({ ...form, accrual_date: e.target.value })} />
            <label htmlFor="ip-gross">Suma brută</label>
            <input id="ip-gross" value={form.gross} onChange={(e) => setForm({ ...form, gross: e.target.value })} />
            <label>Linia de buget</label>
            <BudgetLineSelect grants={catalogs.grants} value={form.budget_line_id} onChange={(id) => setForm({ ...form, budget_line_id: id })} label="Linia de buget" />
          </div>
          <div className="hint">Cota de reținere se ia din cotele în vigoare la data calculării; suma și impozitul apar automat în IPC21 la codul tipului.</div>
          <div className="bar">
            <button className="b" onClick={() => save(false)} disabled={busy || !form.person_id || !form.budget_line_id || !form.doc_number}>
              Salvează
            </button>
            <button className="b primary" onClick={() => save(true)} disabled={busy || !form.person_id || !form.budget_line_id || !form.doc_number}>
              Salvează și înregistrează
            </button>
            {editing && (
              <button className="b" onClick={() => edit(null)}>
                Renunță
              </button>
            )}
          </div>
        </section>
      )}
    </>
  );
}
