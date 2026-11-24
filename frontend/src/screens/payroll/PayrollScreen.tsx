import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { TAX_KIND_LABELS, monthPeriod, type GroupedPayment, type PayrollPeriod } from "../../api/payroll";
import type { MonthClose, StepPreview } from "../../api/types";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";
import { TimesheetPanel } from "./TimesheetPanel";

/** „Calcul salariu”: pasul din închiderea lunii, statul de plată și plata cumulată a impozitelor (docs/09 §3). */
export function PayrollScreen() {
  const { orgId, role, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [period, setPeriod] = useState(monthPeriod());
  const [sheet, setSheet] = useState<PayrollPeriod | null>(null);
  const [close, setClose] = useState<MonthClose | null>(null);
  const [preview, setPreview] = useState<StepPreview | null>(null);
  const [grouped, setGrouped] = useState<GroupedPayment[]>([]);
  const [gp, setGp] = useState({ tax_kind: "income_tax", grant_id: "", bank_account_id: "", doc_number: "", doc_date: today(), purpose_limit: "210" });
  const { busy, error, info, run } = useAction();
  const editable = can(role, POSTING_ROLES);

  const [year, month] = period.split("-").map(Number);
  const base = `/organizations/${orgId}`;
  const step = `${base}/month-close/${year}/${month}/steps/payroll`;

  const load = useCallback(() => {
    setPreview(null);
    api<PayrollPeriod>(`${base}/payroll/${year}/${month}`).then(setSheet, () => setSheet(null));
    api<MonthClose>(`${base}/month-close/${year}/${month}`).then(setClose, () => setClose(null));
    api<GroupedPayment[]>(`${base}/payroll/${year}/${month}/grouped-payments`).then(setGrouped, () => setGrouped([]));
  }, [base, year, month]);
  useEffect(load, [load]);

  const status = close?.steps.find((s) => s.step === "payroll");
  const calculated = status?.status === "done";

  const action = (what: "preview" | "run" | "revert") =>
    run(async () => {
      if (what === "preview") {
        setPreview(await api<StepPreview>(`${step}/preview`, { method: "POST" }));
        return;
      }
      await api(`${step}/${what}`, { method: "POST" });
      load();
      return what === "run" ? "Salariul a fost calculat și înregistrat." : "Calculul a fost anulat.";
    });

  const createGrouped = () =>
    run(async () => {
      if (!gp.bank_account_id) throw new Error("Alegeți contul bancar");
      await api(`${base}/payroll/${year}/${month}/grouped-payments`, {
        method: "POST",
        body: { ...gp, grant_id: gp.grant_id || null, purpose_limit: Number(gp.purpose_limit) },
      });
      setGp({ ...gp, doc_number: "" });
      load();
      return "Plata cumulată a fost creată.";
    });

  const paymentAction = (g: GroupedPayment, what: "post" | "unpost" | "delete") =>
    run(async () => {
      if (what === "delete") await api(`${base}/grouped-payments/${g.document_id}`, { method: "DELETE" });
      else await api(`${base}/payment-orders/${g.document_id}/${what}`, { method: "POST" });
      load();
    });

  const dtkt = (documentId: string, title: string, route = "payment-orders") =>
    openTab({ id: `dtkt:${documentId}`, title: `Dt/Kt: ${title}`, kind: "dtkt", params: { route, documentId } });
  const stepDoc = status?.document_id;

  return (
    <>
      <h1>Calcul salariu</h1>
      <div className="bar">
        <label htmlFor="pay-period" className="muted">
          Luna
        </label>
        <input id="pay-period" className="b" type="month" value={period} onChange={(e) => e.target.value && setPeriod(e.target.value)} />
        <button className="b" onClick={() => action("preview")} disabled={busy}>
          Previzualizare
        </button>
        {editable && (
          <button className="b primary" onClick={() => action("run")} disabled={busy || sheet?.is_closed}>
            {calculated ? "Recalculează" : "Calculează"}
          </button>
        )}
        {editable && calculated && (
          <button className="b" onClick={() => action("revert")} disabled={busy}>
            Anulează calculul
          </button>
        )}
        <span className="sp" />
        {stepDoc && (
          <button className="b" onClick={() => dtkt(stepDoc, `salarii ${String(month).padStart(2, "0")}.${year}`, "documents")}>
            Dt/Kt
          </button>
        )}
      </div>
      <TimesheetPanel orgId={orgId} year={year} month={month} editable={editable && !sheet?.is_closed} />
      <div className="hint">
        Calculul e pasul „Calculul salariului” din închiderea lunii: CIM — CNAS, CNAM, impozit cu scutiri doar la locul de bază (cod SAL); contract
        civil — reținere fără scutiri (cod PL). Cheltuielile se repartizează pe granturi după contract.
      </div>
      <Messages error={error} info={info} />

      {preview && (
        <section>
          <h2>Previzualizare</h2>
          {preview.errors.length > 0 && (
            <div className="hint warn">
              {preview.errors.map((e) => (
                <div key={e}>• {e}</div>
              ))}
            </div>
          )}
          <table className="grid">
            <tbody>
              {preview.rows.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td className="num">{money(r.amount)}</td>
                  <td className="muted">{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h2>Statul de plată {sheet?.calculated ? "" : "— luna nu este calculată"}</h2>
        {sheet?.calculated && (
          <table className="grid">
            <thead>
              <tr>
                <th>Persoana</th>
                <th>Contract</th>
                <th>Cod</th>
                <th>Perioada</th>
                <th className="num">Brut</th>
                <th className="num">Scutiri</th>
                <th className="num">CNAM</th>
                <th className="num">Impozit</th>
                <th className="num">Net</th>
                <th className="num">CNAS angajator</th>
                <th>Granturi</th>
              </tr>
            </thead>
            <tbody>
              {sheet.entries.map((e) => (
                <tr key={e.id}>
                  <td>{e.person_name}</td>
                  <td>
                    {e.contract_type === "cim" ? "CIM" : "civil"} {e.contract_number}
                  </td>
                  <td>{e.income_code}</td>
                  <td>
                    {day(e.period_start)} – {day(e.period_end)}
                  </td>
                  <td className="num">{money(e.gross)}</td>
                  <td className="num">{money(Number(e.personal_exemption ?? 0) + Number(e.dependents_exemption ?? 0))}</td>
                  <td className="num">{money(e.cnam_employee)}</td>
                  <td className="num">{money(e.income_tax)}</td>
                  <td className="num">{money(e.net)}</td>
                  <td className="num">{money(e.cnas_employer)}</td>
                  <td className="muted">{e.calc_details?.funding?.map((f) => `${f.grant_code} ${Number(f.share)}%`).join(", ")}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>Total</th>
                <th className="num">{money(sheet.totals.gross)}</th>
                <th />
                <th className="num">{money(sheet.totals.cnam_employee)}</th>
                <th className="num">{money(sheet.totals.income_tax)}</th>
                <th className="num">{money(sheet.totals.net)}</th>
                <th className="num">{money(sheet.totals.cnas_employer)}</th>
                <th />
              </tr>
            </tfoot>
          </table>
        )}
      </section>

      {sheet?.calculated && (
        <section>
          <h2>Plata cumulată a impozitelor și contribuțiilor</h2>
          <table className="grid">
            <thead>
              <tr>
                <th>Nr.</th>
                <th>Data</th>
                <th>Tipul</th>
                <th className="num">Suma</th>
                <th>Destinația</th>
                <th>Stare</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {grouped.map((g) => (
                <tr key={g.document_id}>
                  <td>{g.doc_number}</td>
                  <td>{day(g.doc_date)}</td>
                  <td>{TAX_KIND_LABELS[g.tax_kind ?? ""] ?? g.tax_kind}</td>
                  <td className="num">{money(g.amount)}</td>
                  <td className="muted">{g.purpose}</td>
                  <td>{g.is_posted ? "înregistrat" : "ciornă"}</td>
                  <td>
                    <button className="b" onClick={() => dtkt(g.document_id, `plata ${g.doc_number ?? ""}`)}>
                      Dt/Kt
                    </button>{" "}
                    {editable && (
                      <>
                        <button className="b" onClick={() => paymentAction(g, g.is_posted ? "unpost" : "post")} disabled={busy}>
                          {g.is_posted ? "Anulează" : "Înregistrează"}
                        </button>{" "}
                        {!g.is_posted && (
                          <button className="b" onClick={() => paymentAction(g, "delete")} disabled={busy}>
                            Șterge
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {grouped.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">
                    Nu sunt plăți cumulate pe această lună.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {editable && (
            <>
              <div className="form">
                <label htmlFor="gp-kind">Obligația</label>
                <select id="gp-kind" value={gp.tax_kind} onChange={(e) => setGp({ ...gp, tax_kind: e.target.value })}>
                  {Object.entries(TAX_KIND_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
                <label htmlFor="gp-grant">Proiectul</label>
                <select id="gp-grant" value={gp.grant_id} onChange={(e) => setGp({ ...gp, grant_id: e.target.value })}>
                  <option value="">toate</option>
                  {catalogs.grants.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.code} {g.title}
                    </option>
                  ))}
                </select>
                <label htmlFor="gp-bank">Contul bancar</label>
                <select id="gp-bank" value={gp.bank_account_id} onChange={(e) => setGp({ ...gp, bank_account_id: e.target.value })}>
                  <option value="">— alegeți —</option>
                  {catalogs.bankAccounts
                    .filter((b) => b.currency === "MDL")
                    .map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.iban} {b.bank_name}
                      </option>
                    ))}
                </select>
                <label htmlFor="gp-no">Nr. ordinului</label>
                <input id="gp-no" value={gp.doc_number} onChange={(e) => setGp({ ...gp, doc_number: e.target.value })} />
                <label htmlFor="gp-date">Data</label>
                <input id="gp-date" type="date" value={gp.doc_date} onChange={(e) => setGp({ ...gp, doc_date: e.target.value })} />
                <label htmlFor="gp-limit">Lungimea destinației</label>
                <select id="gp-limit" value={gp.purpose_limit} onChange={(e) => setGp({ ...gp, purpose_limit: e.target.value })}>
                  <option value="210">210 caractere (OTP)</option>
                  <option value="440">440 caractere (MAIB, DE1 + DE2)</option>
                </select>
              </div>
              <div className="hint">
                Un singur ordin (un comision) cu rândurile pe persoane; dacă lista nu încape, destinația păstrează doar numele de familie, iar dacă nici
                așa nu încape — împărțiți plata pe proiecte.
              </div>
              <div className="bar">
                <button className="b primary" onClick={createGrouped} disabled={busy || !gp.doc_number.trim()}>
                  Creează plata cumulată
                </button>
              </div>
            </>
          )}
        </section>
      )}
    </>
  );
}
