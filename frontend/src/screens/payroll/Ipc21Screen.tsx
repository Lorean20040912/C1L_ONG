import { useCallback, useEffect, useState } from "react";
import { api, apiDownload } from "../../api/client";
import { monthPeriod, type Ipc21 } from "../../api/payroll";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** Declarația IPC21 (docs/05): Tabelul 1 pe coduri, descifrarea, anexa pe subdiviziuni, Tabelul 2 nominal, verificări și XML. */
export function Ipc21Screen() {
  const { orgId, role } = useShell();
  const [period, setPeriod] = useState(monthPeriod());
  const [report, setReport] = useState<Ipc21 | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const { busy, error, info, run } = useAction();
  const [year, month] = period.split("-").map(Number);
  const base = `/organizations/${orgId}/reports/ipc21/${year}/${month}`;

  const load = useCallback(() => {
    setReport(null);
    run(async () => setReport(await api<Ipc21>(base)));
  }, [base, run]);
  useEffect(load, [load]);

  const download = () => run(() => apiDownload(`${base}/xml`, `IPC21_${year}_${String(month).padStart(2, "0")}.xml`));
  const downloadIrm19 = () =>
    run(() =>
      apiDownload(`/organizations/${orgId}/reports/irm19/${year}/${month}/xml`, `IRM19_${year}_${String(month).padStart(2, "0")}.xml`),
    );
  const rows = report?.table1.filter((r) => showAll || Number(r.c4) || Number(r.c5) || Number(r.c6)) ?? [];

  return (
    <>
      <h1>IPC21 — reținerea impozitului pe venit, CNAM și CNAS</h1>
      <div className="bar">
        <label htmlFor="ipc-period" className="muted">
          Luna
        </label>
        <input id="ipc-period" className="b" type="month" value={period} onChange={(e) => e.target.value && setPeriod(e.target.value)} />
        <button className="b" onClick={load} disabled={busy}>
          Actualizează
        </button>
        <label className="muted">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> toate rândurile
        </label>
        <span className="sp" />
        {can(role, POSTING_ROLES) && (
          <button className="b primary" onClick={download} disabled={busy || !report || report.errors.length > 0}>
            Export XML (e-Cabinet SFS)
          </button>
        )}
        {can(role, POSTING_ROLES) && (
          <button className="b" onClick={downloadIrm19} disabled={busy}>
            IRM19 — angajările lunii (XML)
          </button>
        )}
      </div>
      <Messages error={error} info={info} />
      {report && report.errors.length > 0 && (
        <div className="hint warn">
          Verificări (docs/05 §5) — de corectat înainte de export:
          {report.errors.map((e) => (
            <div key={e}>• {e}</div>
          ))}
        </div>
      )}
      {report && (
        <>
          <section>
            <h2>Tabelul 1</h2>
            <table className="grid">
              <thead>
                <tr>
                  <th>Rând</th>
                  <th>Cod</th>
                  <th>Sursa venitului</th>
                  <th className="num">4. Venit achitat</th>
                  <th className="num">5. Impozit reținut</th>
                  <th className="num">6. CNAM reținut</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.row} className={detail === r.code ? "sel" : ""} onClick={() => setDetail(detail === r.code ? null : r.code)}>
                    <td>{r.row}</td>
                    <td>{r.code}</td>
                    <td>{r.title}</td>
                    <td className="num">{money(r.c4)}</td>
                    <td className="num">{money(r.c5)}</td>
                    <td className="num">{r.row === "11" || r.row === "12" ? money(r.c6) : ""}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>61</th>
                  <th />
                  <th>TOTAL</th>
                  <th className="num">{money(report.total.c4)}</th>
                  <th className="num">{money(report.total.c5)}</th>
                  <th className="num">{money(report.total.c6)}</th>
                </tr>
              </tfoot>
            </table>
            <div className="totals">
              <span>
                Suma de control: <b>{money(report.control_sum)}</b>
              </span>
            </div>
          </section>

          <section>
            <h2>Descifrarea {detail ? `codului ${detail}` : "(clic pe un rând pentru filtrare)"}</h2>
            <table className="grid">
              <thead>
                <tr>
                  <th>Cod</th>
                  <th>Persoana</th>
                  <th>Contract / document</th>
                  <th>Sursa</th>
                  <th className="num">Col. 4</th>
                  <th className="num">Col. 5</th>
                  <th className="num">Col. 6</th>
                </tr>
              </thead>
              <tbody>
                {report.breakdown
                  .filter((b) => !detail || b.code === detail)
                  .map((b, i) => (
                    <tr key={i}>
                      <td>{b.code}</td>
                      <td>{b.person}</td>
                      <td>{b.contract}</td>
                      <td className="muted">{b.source === "payroll" ? "calculul salariului" : "plată către persoană fizică"}</td>
                      <td className="num">{money(b.c4)}</td>
                      <td className="num">{money(b.c5)}</td>
                      <td className="num">{Number(b.c6) ? money(b.c6) : ""}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Anexa la Tabelul 1 — impozitul din salarii pe subdiviziuni</h2>
            <table className="grid">
              <thead>
                <tr>
                  <th>Nr.</th>
                  <th>Cod CUATM</th>
                  <th className="num">3. Total</th>
                  <th className="num">4. SAL</th>
                  <th className="num">5. SAL a)</th>
                </tr>
              </thead>
              <tbody>
                {report.annex.map((a) => (
                  <tr key={a.no}>
                    <td>{a.no}</td>
                    <td>{a.cuatm}</td>
                    <td className="num">{money(a.c3)}</td>
                    <td className="num">{money(a.c4)}</td>
                    <td className="num">{money(a.c5)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Tabelul 2 — evidența nominală CNAS</h2>
            <table className="grid">
              <thead>
                <tr>
                  <th>Nr.</th>
                  <th>Numele, prenumele</th>
                  <th>IDNP</th>
                  <th>CPAS</th>
                  <th>Perioada</th>
                  <th>Categoria</th>
                  <th className="num">Tarif %</th>
                  <th className="num">9. Baza</th>
                  <th className="num">11. Contribuția</th>
                </tr>
              </thead>
              <tbody>
                {report.nominal.map((n) => (
                  <tr key={n.no}>
                    <td>{n.no}</td>
                    <td>{n.full_name}</td>
                    <td>{n.idnp_masked}</td>
                    <td className={n.cpas ? "" : "late"}>{n.cpas ?? "lipsește"}</td>
                    <td>
                      {day(n.period_start)} – {day(n.period_end)}
                    </td>
                    <td>{n.insured_category}</td>
                    <td className="num">{Number(n.tariff)}</td>
                    <td className="num">{money(n.base)}</td>
                    <td className="num">{money(n.contribution)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table className="grid">
              <thead>
                <tr>
                  <th>Rândul totalurilor</th>
                  <th className="num">Tarif %</th>
                  <th className="num">Col. 9</th>
                  <th className="num">Col. 11</th>
                </tr>
              </thead>
              <tbody>
                {report.tariffs.map((t) => (
                  <tr key={t.row}>
                    <td>{t.row}</td>
                    <td className="num">{Number(t.tariff)}</td>
                    <td className="num">{money(t.c9)}</td>
                    <td className="num">{money(t.c11)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </>
  );
}
