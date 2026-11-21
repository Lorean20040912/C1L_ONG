import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { TRANCHE_STATUS, type BudgetLineRow, type BudgetVersion, type Donor, type GrantDonor, type Tranche } from "../../api/grants";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, parseAmount, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { Messages, ReadOnlyNote } from "../admin/Messages";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";

/** Donatorii, versiunile de buget și tranșele unui grant (docs/02 §9a). */
export function GrantAdvancedScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [grantId, setGrantId] = useState("");
  const [donors, setDonors] = useState<Donor[]>([]);
  const [gDonors, setGDonors] = useState<GrantDonor[]>([]);
  const [versions, setVersions] = useState<BudgetVersion[]>([]);
  const [lines, setLines] = useState<BudgetLineRow[]>([]);
  const [tranches, setTranches] = useState<Tranche[]>([]);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}`;
  const grant = catalogs.grants.find((g) => g.id === grantId);

  // formulare
  const [donorId, setDonorId] = useState("");
  const [share, setShare] = useState("");
  const [validFrom, setValidFrom] = useState(today());
  const [changes, setChanges] = useState<Record<string, string>>({});
  const [tAmount, setTAmount] = useState("");
  const [tDate, setTDate] = useState("");
  const [tDonor, setTDonor] = useState("");
  const [tCondition, setTCondition] = useState("");

  useEffect(() => {
    api<Donor[]>(`${base}/donors`)
      .then(setDonors)
      .catch((e: Error) => setError(e.message));
  }, [base, setError]);

  const load = useCallback(() => {
    if (!grantId) return;
    const g = `${base}/grants/${grantId}`;
    Promise.all([
      api<GrantDonor[]>(`${g}/donors`),
      api<BudgetVersion[]>(`${g}/budget-versions`),
      api<BudgetLineRow[]>(`${g}/budget-lines`),
      api<Tranche[]>(`${g}/tranches`),
    ])
      .then(([gd, v, l, t]) => {
        setGDonors(gd);
        setVersions(v);
        setLines(l);
        setTranches(t);
      })
      .catch((e: Error) => setError(e.message));
  }, [base, grantId, setError]);
  useEffect(() => {
    setChanges({});
    load();
  }, [load]);

  const saveDonors = (next: GrantDonor[]) =>
    run(async () => {
      await api(`${base}/grants/${grantId}/donors`, {
        method: "PUT",
        body: next.map((d) => ({ donor_id: d.donor_id, share_percent: d.share_percent, amount: d.amount })),
      });
      load();
      return "Donatorii grantului au fost salvați.";
    });
  const addDonor = () => {
    if (!donorId || gDonors.some((d) => d.donor_id === donorId)) return;
    const name = donors.find((d) => d.id === donorId)?.name ?? "";
    saveDonors([...gDonors, { donor_id: donorId, donor_name: name, share_percent: share || null, amount: null }]);
    setDonorId("");
    setShare("");
  };

  const newVersion = () =>
    run(async () => {
      const body: Record<string, string> = {};
      for (const [code, value] of Object.entries(changes)) {
        if (value.trim() === "") continue;
        const amount = parseAmount(value);
        if (amount === null) throw new Error(`Suma liniei ${code} nu este validă`);
        body[code] = amount;
      }
      await api(`${base}/grants/${grantId}/budget-versions`, { method: "POST", body: { valid_from: validFrom, changes: body } });
      setChanges({});
      load();
      return "Versiunea nouă a bugetului a fost creată; cea veche rămâne pentru istoric.";
    });

  const addTranche = () =>
    run(async () => {
      const amount = parseAmount(tAmount);
      if (amount === null) throw new Error("Suma tranșei nu este validă");
      await api(`${base}/grants/${grantId}/tranches`, {
        method: "POST",
        body: { amount, planned_date: tDate || null, donor_id: tDonor || null, condition: tCondition.trim() || null },
      });
      setTAmount("");
      setTDate("");
      setTCondition("");
      load();
      return "Tranșa a fost adăugată.";
    });
  const trancheAction = (t: Tranche, action: "recognize" | "unrecognize") =>
    run(async () => {
      await api(`${base}/tranches/${t.id}/${action}`, { method: "POST", body: action === "recognize" ? {} : undefined });
      load();
      return action === "recognize" ? "Tranșa a fost recunoscută (Dt 234.4 — Kt 425 / 537)." : "Recunoașterea a fost anulată.";
    });
  const removeTranche = (t: Tranche) =>
    run(async () => {
      await api(`${base}/tranches/${t.id}`, { method: "DELETE" });
      load();
    });

  const donorName = (id: string | null) => donors.find((d) => d.id === id)?.name ?? "";

  return (
    <>
      <h1>Donatori, versiuni de buget și tranșe</h1>
      <ReadOnlyNote show={!editable} what="modificările le face contabilul" />
      <Messages error={error} info={info} />
      <div className="bar">
        <label htmlFor="ga-grant" className="muted">
          Grantul
        </label>
        <select id="ga-grant" value={grantId} onChange={(e) => setGrantId(e.target.value)}>
          <option value="">— alegeți —</option>
          {catalogs.grants.map((g) => (
            <option key={g.id} value={g.id}>
              {g.code} {g.title}
            </option>
          ))}
        </select>
      </div>
      {grant && (
        <>
          <section>
            <h2>Donatorii grantului</h2>
            <table className="grid">
              <thead>
                <tr>
                  <th>Donator</th>
                  <th className="num">Cota, %</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {gDonors.map((d) => (
                  <tr key={d.donor_id}>
                    <td>{d.donor_name}</td>
                    <td className="num">{d.share_percent ?? ""}</td>
                    <td>
                      {editable && (
                        <button className="b" disabled={busy} onClick={() => saveDonors(gDonors.filter((x) => x.donor_id !== d.donor_id))}>
                          Scoate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {gDonors.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted">
                      Grantul nu are donatori.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {editable && (
              <div className="bar">
                <select aria-label="Donator" value={donorId} onChange={(e) => setDonorId(e.target.value)}>
                  <option value="">— donator —</option>
                  {donors.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
                <input aria-label="Cota, %" placeholder="Cota, %" value={share} onChange={(e) => setShare(e.target.value)} size={6} />
                <button className="b" onClick={addDonor} disabled={busy || !donorId}>
                  Adaugă donatorul
                </button>
              </div>
            )}
          </section>

          <section>
            <h2>Versiunile bugetului</h2>
            <table className="grid">
              <thead>
                <tr>
                  <th>Versiunea</th>
                  <th>În vigoare din</th>
                  <th className="num">Linii</th>
                  <th className="num">Total planificat</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.id}>
                    <td>{v.version}</td>
                    <td>{day(v.valid_from)}</td>
                    <td className="num">{v.lines_count}</td>
                    <td className="num">{money(v.total_planned)}</td>
                    <td className="muted">{v.is_current ? "curentă" : ""}</td>
                  </tr>
                ))}
                {versions.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      Bugetul nu are încă versiuni; prima modificare aprobată o creează (liniile actuale devin versiunea 1).
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {editable && lines.length > 0 && (
              <>
                <h3>Modificare aprobată de donator</h3>
                <div className="hint">Completați doar liniile care își schimbă suma; restul se copiază neschimbate.</div>
                <table className="grid">
                  <thead>
                    <tr>
                      <th>Linia</th>
                      <th className="num">Planificat acum</th>
                      <th className="num">Suma nouă</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l) => (
                      <tr key={l.id}>
                        <td>
                          {l.code} {l.name}
                        </td>
                        <td className="num">{money(l.planned_amount)}</td>
                        <td className="num">
                          <input
                            aria-label={`Suma nouă ${l.code}`}
                            value={changes[l.code] ?? ""}
                            onChange={(e) => setChanges({ ...changes, [l.code]: e.target.value })}
                            size={10}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="bar">
                  <label htmlFor="ga-from" className="muted">
                    În vigoare din
                  </label>
                  <input id="ga-from" type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
                  <button className="b primary" onClick={newVersion} disabled={busy || !validFrom}>
                    Creează versiunea nouă
                  </button>
                </div>
              </>
            )}
          </section>

          <section>
            <h2>Tranșe</h2>
            <table className="grid">
              <thead>
                <tr>
                  <th>Nr.</th>
                  <th>Data planificată</th>
                  <th>Donator</th>
                  <th className="num">Suma ({grant.currency ?? ""})</th>
                  <th>Condiția</th>
                  <th>Starea</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {tranches.map((t) => (
                  <tr key={t.id}>
                    <td>{t.number}</td>
                    <td>{day(t.planned_date)}</td>
                    <td>{donorName(t.donor_id)}</td>
                    <td className="num">{money(t.amount)}</td>
                    <td className="muted">{t.condition}</td>
                    <td>{TRANCHE_STATUS[t.status]}</td>
                    <td className="acts">
                      {editable && t.status === "planned" && (
                        <>
                          <button className="b" onClick={() => trancheAction(t, "recognize")} disabled={busy}>
                            Recunoaște
                          </button>
                          <button className="b" onClick={() => removeTranche(t)} disabled={busy}>
                            Șterge
                          </button>
                        </>
                      )}
                      {editable && t.status === "recognized" && (
                        <button className="b" onClick={() => trancheAction(t, "unrecognize")} disabled={busy}>
                          Anulează recunoașterea
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {tranches.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">
                      Nu sunt tranșe.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="hint">Încasarea unei tranșe se înregistrează prin ordinul de plată de intrare pe grant.</div>
            {editable && (
              <div className="bar">
                <input aria-label="Suma tranșei" placeholder="Suma" value={tAmount} onChange={(e) => setTAmount(e.target.value)} size={10} />
                <input aria-label="Data planificată" type="date" value={tDate} onChange={(e) => setTDate(e.target.value)} />
                <select aria-label="Donatorul tranșei" value={tDonor} onChange={(e) => setTDonor(e.target.value)}>
                  <option value="">— donator —</option>
                  {donors.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
                <input aria-label="Condiția" placeholder="Condiția (ex. după raportul intermediar)" value={tCondition} onChange={(e) => setTCondition(e.target.value)} />
                <button className="b primary" onClick={addTranche} disabled={busy || !tAmount.trim()}>
                  Adaugă tranșa
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
