import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AccountingPolicy } from "../../api/types";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "./Messages";

const RECOGNITION: Record<string, string> = {
  on_signing: "La semnarea contractului (creanța pe tot grantul)",
  on_receipt: "La primirea tranșei (contract neautentificat)",
};
const STOCKS: Record<string, string> = {
  unused_only: "Doar partea nedistribuită trece la 535",
  all: "Toată suma stocurilor și avansurilor la 535",
};

/** Politica contabilă pe versiuni (docs/11 §6 p.2): o schimbare = o versiune nouă de la o dată. */
export function PolicyScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [versions, setVersions] = useState<AccountingPolicy[] | null>(null);
  const [validFrom, setValidFrom] = useState(today());
  const [account, setAccount] = useState("");
  const [recognition, setRecognition] = useState("on_signing");
  const [stocks, setStocks] = useState("unused_only");
  const [faMethod, setFaMethod] = useState("");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [rateAge, setRateAge] = useState("5");
  const { busy, error, info, run } = useAction();
  const editable = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/accounting-policies`;

  const load = useCallback(
    () =>
      api<AccountingPolicy[]>(base).then((v) => {
        setVersions(v);
        // formularul pornește de la versiunea în vigoare
        const current = v[0];
        if (current) {
          setAccount(current.grant_receivable_account_id ?? "");
          setRecognition(current.grant_recognition ?? "on_signing");
          setStocks(current.stock_to_deferred_income ?? "unused_only");
          setFaMethod(current.fa_valuation_method ?? "");
          setSettings(current.settings ?? {});
          setRateAge(String(current.settings?.max_rate_age_days ?? 5));
        }
      }),
    [base],
  );

  useEffect(() => {
    load();
  }, [load]);

  const accountCode = (id: string | null) => catalogs.accounts.find((a) => a.id === id)?.code ?? "—";

  const save = () =>
    run(async () => {
      await api(base, {
        method: "POST",
        body: {
          valid_from: validFrom,
          grant_receivable_account_id: account || null,
          grant_recognition: recognition,
          stock_to_deferred_income: stocks,
          fa_valuation_method: faMethod.trim() || null,
          settings: { ...settings, max_rate_age_days: Number.isInteger(Number(rateAge)) && rateAge.trim() !== "" ? Number(rateAge) : 5 },
        },
      });
      await load();
      return `Versiunea de la ${day(validFrom)} a fost aprobată; se aplică operațiunilor de la această dată.`;
    });

  return (
    <>
      <h1>Politica contabilă</h1>
      <ReadOnlyNote show={!editable} what="politica o aprobă contabilul-șef" />
      <Messages error={error} info={info} />
      {editable && (
        <section>
          <h2>Versiune nouă</h2>
          <div className="form">
            <label htmlFor="p-from">Se aplică de la</label>
            <input id="p-from" type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
            <label htmlFor="p-acc">Contul creanțelor de grant</label>
            <select id="p-acc" value={account} onChange={(e) => setAccount(e.target.value)}>
              <option value="">— nestabilit —</option>
              {catalogs.accounts
                .filter((a) => !a.is_group)
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.code} {a.name}
                  </option>
                ))}
            </select>
            <label htmlFor="p-age">Vechimea maximă a cursului BNM (zile)</label>
            <input id="p-age" type="number" min={0} max={60} value={rateAge} onChange={(e) => setRateAge(e.target.value)} />
            <label htmlFor="p-rec">Recunoașterea grantului</label>
            <select id="p-rec" className="wide" value={recognition} onChange={(e) => setRecognition(e.target.value)}>
              {Object.entries(RECOGNITION).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <label htmlFor="p-stock">Stocuri și avansuri din grant</label>
            <select id="p-stock" className="wide" value={stocks} onChange={(e) => setStocks(e.target.value)}>
              {Object.entries(STOCKS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <label htmlFor="p-fa">Evaluarea mijloacelor fixe</label>
            <input id="p-fa" className="wide" value={faMethod} placeholder="ex. costul de intrare" onChange={(e) => setFaMethod(e.target.value)} />
          </div>
          <div className="hint">
            Contul creanțelor: 234.4 (subcont, după [SEM]) sau 235 (cont nou, după [ART]). Formulele rămân aceleași — se schimbă doar contul.
            Versiunile vechi rămân pentru operațiunile anterioare.
          </div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              Aprobă versiunea
            </button>
          </div>
        </section>
      )}
      <h2>Versiunile</h2>
      <table className="grid">
        <thead>
          <tr>
            <th>De la</th>
            <th>Creanțe grant</th>
            <th>Recunoașterea grantului</th>
            <th>Stocuri</th>
            <th>Aprobat de</th>
          </tr>
        </thead>
        <tbody>
          {versions?.map((v, i) => (
            <tr key={v.id}>
              <td>
                {day(v.valid_from)}
                {i === 0 && <span className="tag srv"> în vigoare</span>}
              </td>
              <td>{accountCode(v.grant_receivable_account_id)}</td>
              <td>{RECOGNITION[v.grant_recognition ?? ""] ?? v.grant_recognition}</td>
              <td>{STOCKS[v.stock_to_deferred_income ?? ""] ?? v.stock_to_deferred_income}</td>
              <td>{v.approved_by_name}</td>
            </tr>
          ))}
          {versions?.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Politica contabilă nu e stabilită — formulele cu creanța de grant nu se pot aplica.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
