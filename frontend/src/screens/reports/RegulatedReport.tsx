import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, download } from "../../api/client";
import {
  DESIGNATION_LABELS,
  REPORT_STATUS_LABELS,
  type CellDrilldown,
  type ReportRow,
  type TaxReport,
  type TaxReportListItem,
} from "../../api/types";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, POSTING_ROLES, can, useShell } from "../../shell/tabs";

export type RegulatedCode = "ONG17" | "5-CON";

function decimalsOf(report: TaxReport, row: ReportRow): number {
  if (row.unit === "pers.") return 0;
  return report.unit === "mii lei" ? 1 : 2;
}

function fmt(value: string, decimals: number): string {
  const n = Number(value);
  if (decimals === 2) return money(n);
  return n.toFixed(decimals).replace(".", ",").replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function startOf(code: RegulatedCode, year: number, quarter: number): string {
  return code === "ONG17" ? `${year}-01-01` : `${year}-${String((quarter - 1) * 3 + 1).padStart(2, "0")}-01`;
}

/** Raportul reglementat: completare automată → corecții pe celule → verificare → depunere; descifrarea fiecărei cifre. */
export function RegulatedReport({ code, periodFrom }: { code: RegulatedCode; periodFrom?: string }) {
  const { orgId, role } = useShell();
  const now = new Date();
  const initial = periodFrom ? new Date(periodFrom) : new Date(now.getFullYear(), now.getMonth() - 3, 1);
  const [year, setYear] = useState(code === "ONG17" && !periodFrom ? now.getFullYear() - 1 : initial.getFullYear());
  const [quarter, setQuarter] = useState(Math.floor(initial.getMonth() / 3) + 1);
  const [report, setReport] = useState<TaxReport | null>(null);
  const [saved, setSaved] = useState<TaxReportListItem[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [drill, setDrill] = useState<CellDrilldown | null>(null);
  const { busy, error, info, run } = useAction();
  const base = `/organizations/${orgId}/reports/tax-reports`;
  const start = startOf(code, year, quarter);
  const editable = report !== null && report.status !== "submitted" && can(role, POSTING_ROLES);

  const show = (r: TaxReport) => {
    setReport(r);
    setEdits({});
  };

  const loadSaved = useCallback(async () => {
    const list = await api<TaxReportListItem[]>(`${base}?code=${encodeURIComponent(code)}`);
    setSaved(list);
    return list;
  }, [base, code]);

  // la schimbarea perioadei se deschide ciorna perioadei sau, dacă nu e, ultimul raport depus
  useEffect(() => {
    setDrill(null);
    loadSaved()
      .then((list) => {
        const forPeriod = list.filter((r) => r.period_from === start);
        const pick = forPeriod.find((r) => r.status !== "submitted") ?? forPeriod[0];
        if (pick) return api<TaxReport>(`${base}/${pick.id}`).then(show);
        setReport(null);
      })
      .catch(() => setReport(null));
  }, [base, start, loadSaved]);

  const generate = () =>
    run(async () => {
      show(await api<TaxReport>(base, { method: "POST", body: { code, period_from: start } }));
      setDrill(null);
      await loadSaved();
      return "Raportul a fost completat din contabilitate";
    });

  const saveCell = (rowCode: string) => {
    if (!report || !(rowCode in edits)) return;
    const value = edits[rowCode].replace(/\s/g, "").replace(",", ".");
    run(async () => {
      show(await api<TaxReport>(`${base}/${report.id}/overrides`, { method: "PUT", body: { cells: { [rowCode]: value || null } } }));
    });
  };

  const setStatus = (status: "checked" | "submitted" | "draft") =>
    report &&
    run(async () => {
      if (status === "submitted" && !window.confirm("După depunere raportul nu se mai modifică. Depuneți?")) return;
      show(await api<TaxReport>(`${base}/${report.id}/status`, { method: "POST", body: { status } }));
      await loadSaved();
      return status === "submitted" ? "Raportul a fost marcat ca depus" : undefined;
    });

  const openDrill = (rowCode: string) =>
    report && run(async () => setDrill(await api<CellDrilldown>(`${base}/${report.id}/cells/${encodeURIComponent(rowCode)}`)));

  const fileName = report ? `${code}_${report.period_from}` : code;
  const years = Array.from({ length: 6 }, (_, i) => now.getFullYear() - 4 + i);
  const errors = report?.checks.filter((c) => c.severity === "error") ?? [];
  const warnings = report?.checks.filter((c) => c.severity === "warning") ?? [];

  return (
    <>
      <h1>{code === "ONG17" ? "ONG17 — declarația organizației necomerciale" : "5-CON — consumurile și cheltuielile ONG"}</h1>
      <div className="bar">
        <select className="b" aria-label="Anul" value={year} onChange={(e) => setYear(Number(e.target.value))}>
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        {code === "5-CON" && (
          <select className="b" aria-label="Trimestrul" value={quarter} onChange={(e) => setQuarter(Number(e.target.value))}>
            {[1, 2, 3, 4].map((q) => (
              <option key={q} value={q}>
                Trimestrul {q}
              </option>
            ))}
          </select>
        )}
        {can(role, POSTING_ROLES) && (
          <button className="b primary" onClick={generate} disabled={busy}>
            {report && report.status !== "submitted" ? "Recalculează" : "Generează"}
          </button>
        )}
        {report && editable && report.status === "draft" && (
          <button className="b" onClick={() => setStatus("checked")} disabled={busy}>
            Verificat
          </button>
        )}
        {report && report.status !== "submitted" && can(role, ADMIN_ROLES) && (
          <button className="b" onClick={() => setStatus("submitted")} disabled={busy || errors.length > 0} title={errors.length ? "Corectați erorile" : ""}>
            Marchează depus
          </button>
        )}
        {report && (
          <button className="b" onClick={() => run(() => download(`${base}/${report.id}/export.xlsx`, `${fileName}.xlsx`))}>
            Excel
          </button>
        )}
        {report?.xml_export && (
          <button className="b" onClick={() => run(() => download(`${base}/${report.id}/export.xml`, `${fileName}.xml`))}>
            XML (BNS)
          </button>
        )}
        <span className="sp" />
        {report && (
          <span className="muted">
            {REPORT_STATUS_LABELS[report.status]}
            {report.submitted_at ? ` ${day(report.submitted_at)}` : ""} · forma {report.form_version} · {report.unit}
          </span>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      {info && <div className="hint">{info}</div>}
      {saved.filter((r) => r.period_from === start).length > 1 && (
        <div className="muted small">
          Versiuni pe perioadă:{" "}
          {saved
            .filter((r) => r.period_from === start)
            .map((r) => (
              <button key={r.id} className="link" onClick={() => api<TaxReport>(`${base}/${r.id}`).then(show)}>
                {REPORT_STATUS_LABELS[r.status]}
                {r.submitted_at ? ` ${day(r.submitted_at)}` : ""}
              </button>
            ))
            .reduce<ReactNode[]>((acc, el, i) => (i ? [...acc, " · ", el] : [el]), [])}
        </div>
      )}
      {!report && <p className="muted">Raportul pe perioadă nu este întocmit. Apăsați „Generează” — se completează din înregistrările contabile.</p>}
      {report && (
        <>
          {errors.map((c, i) => (
            <div key={`e${i}`} className="error">
              {c.message}
            </div>
          ))}
          {warnings.length > 0 && (
            <div className="hint">
              {warnings.map((c, i) => (
                <div key={i}>{c.message}</div>
              ))}
            </div>
          )}
          <div className="muted small">
            {Object.entries(report.header)
              .filter(([, v]) => v)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ")}
          </div>
          <table className="grid">
            <thead>
              <tr>
                <th>Cod</th>
                <th>Indicator</th>
                <th className="num">Valoare</th>
                <th className="num">Calculat</th>
                {editable && <th className="num">Corecție</th>}
              </tr>
            </thead>
            <tbody>
              {report.rows.map((r) => {
                const d = decimalsOf(report, r);
                return (
                  <tr key={r.code} className={r.has_formula ? "total-row" : drill?.code === r.code ? "sel" : ""}>
                    <td>{r.code}</td>
                    <td style={{ paddingLeft: 8 + r.indent * 14 }}>
                      {r.label}
                      {r.informative && <span className="muted"> (informativ)</span>}
                    </td>
                    <td className="num">
                      <button className="link" title="Descifrare: înregistrările din care provine" onClick={() => openDrill(r.code)}>
                        {fmt(r.value, d)}
                      </button>
                      {r.unit && r.unit !== "lei" ? ` ${r.unit}` : ""}
                    </td>
                    <td className="num muted">{r.overridden ? fmt(r.calculated, d) : ""}</td>
                    {editable && (
                      <td className="num">
                        <input
                          className="short"
                          aria-label={`Corecție rândul ${r.code}`}
                          placeholder={r.overridden ? "" : "—"}
                          value={edits[r.code] ?? (r.overridden ? String(Number(r.value)) : "")}
                          onChange={(e) => setEdits((x) => ({ ...x, [r.code]: e.target.value }))}
                          onBlur={() => saveCell(r.code)}
                          onKeyDown={(e) => e.key === "Enter" && saveCell(r.code)}
                          style={{ width: 90 }}
                        />
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {drill && <Drilldown drill={drill} onClose={() => setDrill(null)} />}
          {report.annex_1d.length > 0 && <Annex rows={report.annex_1d} />}
        </>
      )}
    </>
  );
}

function Drilldown({ drill, onClose }: { drill: CellDrilldown; onClose: () => void }) {
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="bar">
        <b>
          Descifrarea rândului {drill.code} — {drill.label}
        </b>
        <span className="sp" />
        <button className="b" onClick={onClose}>
          Închide
        </button>
      </div>
      {drill.overridden && <div className="hint">Valoarea rândului e corectată manual.</div>}
      {drill.changed_since_report && <div className="hint warn">Înregistrările s-au schimbat după completarea raportului — recalculați.</div>}
      {drill.items.length === 0 ? (
        <p className="muted">Rândul nu are înregistrări-sursă (valoare din formulă, corecție sau zero).</p>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>Data</th>
              <th>Document</th>
              <th>Dt</th>
              <th>Kt</th>
              <th>Grant</th>
              <th>Articol</th>
              <th>Conținut</th>
              <th className="num">Suma, lei</th>
            </tr>
          </thead>
          <tbody>
            {drill.items.map((i, n) => (
              <tr key={n}>
                <td>{day(i.entry_date)}</td>
                <td>{i.doc_number}</td>
                <td>{i.debit_account}</td>
                <td>{i.credit_account}</td>
                <td>{i.grant_code}</td>
                <td>{i.cost_item}</td>
                <td>
                  {i.kind === "budget_excess" ? `${i.label} (planificat ${money(i.planned)}, cheltuit ${money(i.spent)})` : i.kind === "entry" ? i.description : i.label}
                </td>
                <td className="num">{i.kind === "rate" || i.kind === "stats" ? i.amount : money(i.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Annex({ rows }: { rows: TaxReport["annex_1d"] }) {
  const cats = ["public_utility", "social_charity", "administrative"] as const;
  const cell = (v: string | undefined) => (v === undefined ? "X" : money(v));
  return (
    <>
      <h2>Anexa 1D — utilizarea sumelor din desemnarea procentuală</h2>
      {rows.map((a) => (
        <table className="grid" key={a.grant_id} style={{ marginBottom: 12 }}>
          <thead>
            <tr>
              <th>
                {a.grant_code} — desemnarea {a.designation_year}
              </th>
              <th className="num">Perioada desemnării</th>
              <th className="num">Prima perioadă după</th>
              <th className="num">A doua perioadă după</th>
              <th className="num">Rămase (de restituit)</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Sumele desemnate procentual</td>
              <td className="num">{money(a.received)}</td>
              <td className="num">X</td>
              <td className="num">X</td>
              <td className="num">X</td>
            </tr>
            <tr className="total-row">
              <td>Suma cheltuielilor TOTAL</td>
              {a.columns.map((c, i) => (
                <td key={i} className="num">
                  {cell(c?.total)}
                </td>
              ))}
              <td className="num">X</td>
            </tr>
            {cats.map((k) => (
              <tr key={k}>
                <td>– {DESIGNATION_LABELS[k]}</td>
                {a.columns.map((c, i) => (
                  <td key={i} className="num">
                    {cell(c?.[k])}
                  </td>
                ))}
                <td className="num">X</td>
              </tr>
            ))}
            <tr className={a.to_refund ? "over-row" : ""}>
              <td>Sume rămase la sfârșitul perioadei</td>
              <td className="num">X</td>
              <td className="num">X</td>
              <td className="num">X</td>
              <td className="num">
                {money(a.remaining)}
                {a.to_refund && <span className="late"> — de restituit</span>}
              </td>
            </tr>
          </tbody>
        </table>
      ))}
    </>
  );
}
