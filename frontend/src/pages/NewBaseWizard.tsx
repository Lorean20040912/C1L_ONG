import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ENTITY_LABELS, type EntityType, type Workspace } from "../api/types";
import { today } from "../lib/format";

interface Preview {
  accounting_method: "double_entry" | "single_entry";
  tax_regime: string;
  coa_template: string;
  features: { code: string; name: string }[];
}

const ACTIVITIES: Record<string, string> = {
  retail: "Comerț cu amănuntul",
  wholesale: "Comerț cu ridicata",
  catering: "Alimentație publică / fast-food",
  production: "Producție",
  services: "Prestări servicii",
  accommodation: "Cazare / turism",
  agriculture: "Agricultură",
  grants: "Granturi / activitate necomercială",
};
const REGIMES: Record<string, string> = {
  general: "Regim general",
  ivao_sme: "Impozit pe venitul din activitatea operațională (IMM)",
  gt: "Regimul GȚ",
  ngo: "Regimul ONG",
  independent_activity: "Activitate independentă",
};
const SOURCES: Record<string, string> = { empty: "Bază goală", excel_import: "Import din fișiere Excel" };

/** Expertul „Bază nouă” (docs/13 §2): răspunsurile hotărăsc ce funcționalități pornesc. */
export function NewBaseWizard({ onCreated }: { onCreated: (ws: Workspace) => void }) {
  const [step, setStep] = useState(1);
  const [idno, setIdno] = useState("");
  const [name, setName] = useState("");
  const [entityType, setEntityType] = useState<EntityType>("srl");
  const [method, setMethod] = useState<"" | "double_entry">("");
  const [vat, setVat] = useState(false);
  const [vatFrom, setVatFrom] = useState(today());
  const [activities, setActivities] = useState<string[]>([]);
  const [employees, setEmployees] = useState(false);
  const [source, setSource] = useState("empty");
  const [regime, setRegime] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canChooseMethod = entityType === "gt";
  const answers = {
    entity_type: entityType,
    accounting_method: canChooseMethod && method ? method : null,
    vat_payer: vat,
    vat_payer_from: vat ? vatFrom : null,
    activities,
    has_employees: employees,
  };

  useEffect(() => {
    if (step !== 4) return;
    setError(null);
    api<Preview>("/workspaces/wizard/preview", { method: "POST", body: answers })
      .then((p) => {
        setPreview(p);
        setSelected(p.features.map((f) => f.code));
        setRegime(p.tax_regime);
      })
      .catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ workspace: Workspace }>("/workspaces/wizard", {
        method: "POST",
        body: { ...answers, name, organization_name: name, idno, source, tax_regime: regime, features: selected },
      });
      onCreated(r.workspace);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const step1Ok = /^\d{13}$/.test(idno) && name.trim() !== "";

  return (
    <div className="card">
      <h3>Bază nouă — pasul {step} din 4</h3>
      {error && <div className="error">{error}</div>}
      {step === 1 && (
        <>
          <div className="field">
            <label htmlFor="nb-name">Denumirea organizației</label>
            <input id="nb-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="nb-idno">IDNO (13 cifre)</label>
            <input id="nb-idno" value={idno} onChange={(e) => setIdno(e.target.value)} inputMode="numeric" />
          </div>
          <div className="field">
            <label htmlFor="nb-type">Forma juridică</label>
            <select id="nb-type" value={entityType} onChange={(e) => setEntityType(e.target.value as EntityType)}>
              {Object.entries(ENTITY_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          {canChooseMethod && (
            <div className="field">
              <label htmlFor="nb-method">Evidența</label>
              <select id="nb-method" value={method} onChange={(e) => setMethod(e.target.value as "" | "double_entry")}>
                <option value="">Partidă simplă</option>
                <option value="double_entry">Partidă dublă</option>
              </select>
            </div>
          )}
        </>
      )}
      {step === 2 && (
        <>
          <div className="field">
            <label>
              <input type="checkbox" checked={vat} onChange={(e) => setVat(e.target.checked)} /> Plătitor de TVA
            </label>
            {vat && <input type="date" aria-label="De la data" value={vatFrom} onChange={(e) => setVatFrom(e.target.value)} />}
          </div>
          <div className="field">
            <label>Genuri de activitate</label>
            {Object.entries(ACTIVITIES).map(([v, l]) => (
              <label key={v} style={{ display: "block" }}>
                <input type="checkbox" checked={activities.includes(v)} onChange={() => setActivities(toggle(activities, v))} /> {l}
              </label>
            ))}
          </div>
        </>
      )}
      {step === 3 && (
        <>
          <div className="field">
            <label>
              <input type="checkbox" checked={employees} onChange={(e) => setEmployees(e.target.checked)} /> Are salariați
            </label>
          </div>
          <div className="field">
            <label htmlFor="nb-src">Sursa datelor</label>
            <select id="nb-src" value={source} onChange={(e) => setSource(e.target.value)}>
              {Object.entries(SOURCES).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <span className="muted"> Importul din 1C se face din „Importă din 1C”.</span>
          </div>
        </>
      )}
      {step === 4 && (
        <>
          {!preview && !error && <p className="muted">Se calculează…</p>}
          {preview && (
            <>
              <p>
                Evidență: <b>{preview.accounting_method === "single_entry" ? "partidă simplă" : "partidă dublă"}</b>. Plan de conturi:{" "}
                <b>{preview.coa_template === "ii_single_entry" ? "fără (registru-jurnal)" : preview.coa_template}</b>.
              </p>
              <div className="field">
                <label htmlFor="nb-reg">Regim fiscal</label>
                <select id="nb-reg" value={regime} onChange={(e) => setRegime(e.target.value)}>
                  {Object.entries(REGIMES).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Vor fi pornite:</label>
                {preview.features.map((f) => (
                  <label key={f.code} style={{ display: "block" }}>
                    <input
                      type="checkbox"
                      checked={selected.includes(f.code)}
                      disabled={f.code === "double_entry" || f.code === "single_entry"}
                      onChange={() => setSelected(toggle(selected, f.code))}
                    />{" "}
                    {f.name}
                  </label>
                ))}
              </div>
            </>
          )}
        </>
      )}
      <div className="bar">
        {step > 1 && (
          <button className="b" type="button" onClick={() => setStep(step - 1)}>
            Înapoi
          </button>
        )}
        {step < 4 && (
          <button className="b primary" type="button" disabled={step === 1 && !step1Ok} onClick={() => setStep(step + 1)}>
            Înainte
          </button>
        )}
        {step === 4 && (
          <button className="b primary" type="button" disabled={busy || !preview} onClick={create}>
            Creează
          </button>
        )}
      </div>
    </div>
  );
}
