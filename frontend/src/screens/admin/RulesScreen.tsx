import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { PostingRule } from "../../api/types";
import { day, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "./Messages";

const DOC_LABELS: Record<string, string> = {
  invoice: "Factură primită",
  payment_order: "Ordin de plată",
  grant_income: "Venituri din granturi",
  stock_distribution: "Distribuirea stocurilor",
  grant_close: "Închiderea grantului",
  fx_difference: "Diferențe de curs",
  membership_fee: "Cotizații",
  "month_close.depreciation": "Închiderea lunii: amortizarea",
};

/** „funding=special_purpose; term=long” ↔ {funding: "special_purpose", term: "long"} */
function conditionsText(c: Record<string, unknown> | null): string {
  return Object.entries(c ?? {})
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("|") : String(v)}`)
    .join("; ");
}

function parseConditions(text: string): Record<string, string | string[]> {
  const result: Record<string, string | string[]> = {};
  for (const part of text.split(";").map((p) => p.trim()).filter(Boolean)) {
    const [key, value] = part.split("=").map((x) => x?.trim());
    if (!key || !value) throw new Error(`Condiția „${part}” trebuie scrisă ca cheie=valoare`);
    result[key] = value.includes("|") ? value.split("|").map((v) => v.trim()) : value;
  }
  return result;
}

interface Draft {
  document_type: string;
  operation: string;
  conditions: string;
  debit_account: string;
  credit_account: string;
  source_ref: string;
  valid_from: string;
  change_reason: string;
}

/** Regulile de înregistrare: cele standard și corecțiile organizației (docs/11 §6 p.3). */
export function RulesScreen() {
  const { orgId, role } = useShell();
  const [rules, setRules] = useState<PostingRule[] | null>(null);
  const [onDate, setOnDate] = useState(today());
  const [filter, setFilter] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const { busy, error, info, run } = useAction();
  const editable = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/posting-rules`;

  const load = useCallback(() => {
    api<PostingRule[]>(`${base}${onDate ? `?on_date=${onDate}` : ""}`).then(setRules);
  }, [base, onDate]);

  useEffect(load, [load]);

  const startCorrection = (r: PostingRule) =>
    setDraft({
      document_type: r.document_type,
      operation: r.operation,
      conditions: conditionsText(r.conditions),
      debit_account: r.debit_account,
      credit_account: r.credit_account,
      source_ref: r.source_ref,
      valid_from: today(),
      change_reason: "",
    });

  const save = () =>
    run(async () => {
      if (!draft) return;
      await api(base, {
        method: "POST",
        body: {
          document_type: draft.document_type.trim(),
          operation: draft.operation.trim(),
          conditions: parseConditions(draft.conditions),
          debit_account: draft.debit_account.trim(),
          credit_account: draft.credit_account.trim(),
          source_ref: draft.source_ref.trim(),
          valid_from: draft.valid_from,
          change_reason: draft.change_reason.trim(),
        },
      });
      setDraft(null);
      load();
      return "Corecția a fost salvată; se aplică documentelor de la data ei (cele vechi, doar dacă se reînregistrează).";
    });

  const q = filter.trim().toLowerCase();
  const visible = (rules ?? []).filter(
    (r) => !q || `${r.document_type} ${DOC_LABELS[r.document_type] ?? ""} ${r.operation} ${r.debit_account} ${r.credit_account}`.toLowerCase().includes(q),
  );
  const setD = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  return (
    <>
      <h1>Reguli de înregistrare</h1>
      <ReadOnlyNote show={!editable} what="formulele le corectează contabilul-șef" />
      <Messages error={error} info={info} />
      {draft && (
        <section className="card">
          <h2>Corecția organizației</h2>
          <div className="form">
            <label htmlFor="r-doc">Tip document</label>
            <input id="r-doc" value={draft.document_type} onChange={(e) => setD({ document_type: e.target.value })} />
            <label htmlFor="r-op">Operațiune</label>
            <input id="r-op" value={draft.operation} onChange={(e) => setD({ operation: e.target.value })} />
            <label htmlFor="r-cond">Condiții</label>
            <input id="r-cond" className="wide" value={draft.conditions} placeholder="ex. funding=unrestricted" onChange={(e) => setD({ conditions: e.target.value })} />
            <label htmlFor="r-dt">Dt</label>
            <input id="r-dt" value={draft.debit_account} onChange={(e) => setD({ debit_account: e.target.value })} />
            <label htmlFor="r-kt">Kt</label>
            <input id="r-kt" value={draft.credit_account} onChange={(e) => setD({ credit_account: e.target.value })} />
            <label htmlFor="r-src">Sursa (obligatoriu)</label>
            <input id="r-src" value={draft.source_ref} placeholder="ex. IM188; SEM" onChange={(e) => setD({ source_ref: e.target.value })} />
            <label htmlFor="r-from">Se aplică de la</label>
            <input id="r-from" type="date" value={draft.valid_from} onChange={(e) => setD({ valid_from: e.target.value })} />
            <label htmlFor="r-why">Motivul</label>
            <input id="r-why" className="wide" value={draft.change_reason} onChange={(e) => setD({ change_reason: e.target.value })} />
          </div>
          <div className="hint">
            Contul se scrie prin cod (ex. 713) sau prin trimitere la politica contabilă: <code>{"{grant_receivable}"}</code>. Corecția are prioritate față
            de regula standard pentru aceeași operațiune și aceleași condiții; versiunea anterioară a corecției se închide automat.
          </div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              Salvează corecția
            </button>
            <button className="b" onClick={() => setDraft(null)}>
              Renunță
            </button>
          </div>
        </section>
      )}
      <div className="bar">
        <label className="muted" htmlFor="r-date">
          Valabile la
        </label>
        <input id="r-date" className="b" type="date" value={onDate} onChange={(e) => setOnDate(e.target.value)} />
        <input className="b" placeholder="Căutare: tip, operațiune, cont" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Căutare în reguli" />
        <span className="sp" />
        {editable && !draft && (
          <button
            className="b"
            onClick={() =>
              setDraft({ document_type: "", operation: "", conditions: "", debit_account: "", credit_account: "", source_ref: "", valid_from: today(), change_reason: "" })
            }
          >
            Regulă nouă
          </button>
        )}
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th>Document</th>
            <th>Operațiune</th>
            <th>Condiții</th>
            <th>Dt</th>
            <th>Kt</th>
            <th>Sursa</th>
            <th>Valabilă</th>
            <th />
            <th />
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => (
            <tr key={r.id} className={r.organization_id ? "own-row" : ""}>
              <td>{DOC_LABELS[r.document_type] ?? r.document_type}</td>
              <td>{r.operation}</td>
              <td className="muted">{conditionsText(r.conditions)}</td>
              <td>{r.debit_account}</td>
              <td>{r.credit_account}</td>
              <td>{r.source_ref}</td>
              <td>
                {day(r.valid_from)}
                {r.valid_to ? ` – ${day(r.valid_to)}` : ""}
              </td>
              <td>{r.organization_id ? <span className="tag omv" title={r.change_reason ?? ""}>corecție v{r.version}</span> : <span className="tag">standard</span>}</td>
              <td>
                {editable && (
                  <button className="link" onClick={() => startCorrection(r)}>
                    corectează
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
