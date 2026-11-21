import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { DepreciationPreview, MonthClose } from "../api/types";
import { grantLabel, useCatalogs } from "../catalog/useCatalogs";
import { day, money } from "../lib/format";
import { useShell } from "../shell/tabs";

const STATUS: Record<string, [string, string]> = {
  done: ["✓", "ok"],
  pending: ["○", "muted"],
  reverted: ["↺", "muted"],
};

function previousMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Asistentul „Închiderea lunii”: pași cu previzualizare → executare → anulare (ToR F2b.4). */
export function MonthCloseScreen() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [period, setPeriod] = useState(previousMonth());
  const [state, setState] = useState<MonthClose | null>(null);
  const [preview, setPreview] = useState<DepreciationPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [year, month] = period.split("-").map(Number);
  const base = `/organizations/${orgId}/month-close/${year}/${month}`;

  const load = useCallback(() => {
    setError(null);
    setPreview(null);
    api<MonthClose>(base)
      .then(setState)
      .catch((e: Error) => setError(e.message));
  }, [base]);

  useEffect(load, [load]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const showPreview = () => run(async () => setPreview(await api<DepreciationPreview>(`${base}/depreciation/preview`, { method: "POST" })));
  const execute = () =>
    run(async () => {
      setState(await api<MonthClose>(`${base}/depreciation/run`, { method: "POST" }));
      setPreview(await api<DepreciationPreview>(`${base}/depreciation/preview`, { method: "POST" }));
    });
  const revert = () =>
    run(async () => {
      setState(await api<MonthClose>(`${base}/depreciation/revert`, { method: "POST" }));
      setPreview(null);
    });

  const openDtKt = () =>
    state?.document_id &&
    openTab({
      id: `dtkt-close:${state.document_id}`,
      title: `Dt/Kt: închiderea ${String(month).padStart(2, "0")}.${year}`,
      kind: "dtkt",
      params: { route: "documents", documentId: state.document_id },
    });

  const depreciation = state?.steps.find((s) => s.step === "depreciation");

  return (
    <>
      <h1>Închiderea lunii</h1>
      <div className="bar">
        <label htmlFor="close-period" className="muted">
          Luna
        </label>
        <input id="close-period" className="b" type="month" value={period} onChange={(e) => e.target.value && setPeriod(e.target.value)} />
        <span className="sp" />
        <button className="b" onClick={openDtKt} disabled={!state?.document_id}>
          Dt/Kt al închiderii
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {state && (
        <ul className="steps">
          {state.steps.map((s) => {
            const [icon, cls] = STATUS[s.status] ?? STATUS.pending;
            return (
              <li key={s.step} className={s.implemented ? "" : "muted"}>
                <span className={`ic ${cls}`}>{icon}</span>
                <span>{s.title}</span>
                <span className="muted">
                  {!s.implemented
                    ? "în lucru"
                    : s.status === "done"
                      ? `${s.entries ?? 0} înregistrări · ${money(s.total)}`
                      : s.status === "reverted"
                        ? "anulat"
                        : "de făcut"}
                </span>
                <span className="acts">
                  {s.step === "depreciation" && (
                    <>
                      <button className="b" onClick={showPreview} disabled={busy}>
                        Previzualizare
                      </button>
                      <button className="b primary" onClick={execute} disabled={busy}>
                        {depreciation?.status === "done" ? "Recalculează" : "Execută"}
                      </button>
                      {depreciation?.status === "done" && (
                        <button className="b" onClick={revert} disabled={busy}>
                          Anulează
                        </button>
                      )}
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {preview && (
        <section>
          <h2>
            Amortizarea pentru {String(month).padStart(2, "0")}.{year} (data înregistrării {day(preview.entry_date)})
          </h2>
          {preview.errors.length > 0 && (
            <div className="hint warn">
              Pasul nu se poate executa până nu se corectează: <br />
              {preview.errors.map((e) => (
                <div key={e}>• {e}</div>
              ))}
              Durata se completează în „Fișa mijloacelor fixe”.
            </div>
          )}
          {preview.rows.length === 0 ? (
            <p className="muted">Nu sunt mijloace fixe de amortizat în această lună.</p>
          ) : (
            <table className="grid">
              <thead>
                <tr>
                  <th>Nr. inventar</th>
                  <th>Denumirea</th>
                  <th className="num">Valoarea inițială</th>
                  <th className="num">Amortizat anterior</th>
                  <th className="num">Amortizarea lunii</th>
                  <th>Dt</th>
                  <th>Kt</th>
                  <th>Grant</th>
                  <th>Sursa regulii</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.fixed_asset_id} className={r.error ? "over-row" : ""}>
                    <td>{r.inventory_no}</td>
                    <td>{r.name}</td>
                    <td className="num">{money(r.initial_cost)}</td>
                    <td className="num">{money(r.accumulated_before)}</td>
                    <td className="num">{r.error ? "" : money(r.amount)}</td>
                    <td>{r.debit_account}</td>
                    <td>{r.credit_account}</td>
                    <td>{grantLabel(catalogs.grants, r.grant_id)}</td>
                    <td className={r.error ? "late" : "muted"}>{r.error ?? r.source_ref}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="totals">
            <span>
              Total amortizare: <b>{money(preview.total)}</b>
            </span>
          </div>
        </section>
      )}
    </>
  );
}
