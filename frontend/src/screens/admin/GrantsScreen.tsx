import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { FUNDING_LABELS, type BudgetLineDetail, type GrantDetail } from "../../api/types";
import { refreshCatalogs, useCatalogs } from "../../catalog/useCatalogs";
import { money, parseAmount } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "./Messages";

const EMPTY_GRANT = {
  code: "",
  title: "",
  funding_type: "grant",
  currency: "MDL",
  total_amount: "",
  start_date: "",
  end_date: "",
  is_closed: false,
};

type GrantForm = typeof EMPTY_GRANT;

/** Proiectele / granturile cu liniile lor de buget (ToR F6.1). */
export function GrantsScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [selected, setSelected] = useState<string | "new" | null>(null);
  // cheia editorului se schimbă doar când utilizatorul alege alt grant; un grant nou salvat
  // rămâne în același editor (altfel confirmarea „salvat” s-ar pierde la remontare)
  const [editorKey, setEditorKey] = useState("");
  const choose = (id: string | "new") => {
    setSelected(id);
    setEditorKey(id === "new" ? `new-${Date.now()}` : id);
  };
  const editable = can(role, POSTING_ROLES);

  return (
    <>
      <h1>Proiecte / granturi</h1>
      <ReadOnlyNote show={!editable} what="granturile le configurează contabilul" />
      <div className="master-detail">
        <div>
          <div className="bar">
            {editable && (
              <button className="b primary" onClick={() => choose("new")}>
                Grant nou
              </button>
            )}
          </div>
          <table className="grid">
            <thead>
              <tr>
                <th>Cod</th>
                <th>Denumire</th>
                <th>Linii</th>
              </tr>
            </thead>
            <tbody>
              {catalogs.grants.map((g) => (
                <tr key={g.id} className={selected === g.id ? "sel" : ""} onClick={() => choose(g.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && choose(g.id)}>
                  <td>{g.code}</td>
                  <td>{g.title}</td>
                  <td className="num">{g.budget_lines.length}</td>
                </tr>
              ))}
              {catalogs.grants.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    Nu sunt granturi.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div>
          {selected && (
            <GrantEditor key={editorKey} grantId={selected === "new" ? null : selected} editable={editable} onSaved={(id) => setSelected(id)} />
          )}
          {!selected && <p className="muted">Alegeți un grant din listă sau creați unul nou.</p>}
        </div>
      </div>
    </>
  );
}

function GrantEditor({ grantId, editable, onSaved }: { grantId: string | null; editable: boolean; onSaved: (id: string) => void }) {
  const { orgId } = useShell();
  const [form, setForm] = useState<GrantForm>(EMPTY_GRANT);
  const { busy, error, info, run } = useAction();
  const base = `/organizations/${orgId}`;

  useEffect(() => {
    if (!grantId) return;
    api<GrantDetail>(`${base}/grants/${grantId}`).then((g) =>
      setForm({
        code: g.code,
        title: g.title,
        funding_type: g.funding_type ?? "grant",
        currency: g.currency,
        total_amount: money(g.total_amount),
        start_date: g.start_date,
        end_date: g.end_date,
        is_closed: Boolean(g.is_closed),
      }),
    );
  }, [base, grantId]);

  const set = (patch: Partial<GrantForm>) => setForm((f) => ({ ...f, ...patch }));

  const save = () =>
    run(async () => {
      const total = parseAmount(form.total_amount);
      if (total === null) throw new Error("Suma totală nu e un număr");
      const body = { ...form, total_amount: total };
      const g = grantId
        ? await api<GrantDetail>(`${base}/grants/${grantId}`, { method: "PUT", body })
        : await api<GrantDetail>(`${base}/grants`, { method: "POST", body });
      refreshCatalogs(orgId);
      if (!grantId) onSaved(g.id);
      return "Grantul a fost salvat.";
    });

  return (
    <section>
      <h2>{grantId ? `${form.code} ${form.title}` : "Grant nou"}</h2>
      <Messages error={error} info={info} />
      <div className="form">
        <label htmlFor="g-code">Cod</label>
        <input id="g-code" value={form.code} disabled={!editable} onChange={(e) => set({ code: e.target.value })} />
        <label htmlFor="g-funding">Sursa de finanțare</label>
        <select id="g-funding" value={form.funding_type} disabled={!editable} onChange={(e) => set({ funding_type: e.target.value })}>
          {Object.entries(FUNDING_LABELS).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <label htmlFor="g-title">Denumire</label>
        <input id="g-title" className="wide" value={form.title} disabled={!editable} onChange={(e) => set({ title: e.target.value })} />
        <label htmlFor="g-total">Suma totală</label>
        <input id="g-total" className="num" value={form.total_amount} disabled={!editable} onChange={(e) => set({ total_amount: e.target.value })} />
        <label htmlFor="g-cur">Valuta</label>
        <input id="g-cur" value={form.currency} maxLength={3} disabled={!editable} onChange={(e) => set({ currency: e.target.value.toUpperCase() })} />
        <label htmlFor="g-start">Începutul</label>
        <input id="g-start" type="date" value={form.start_date} disabled={!editable} onChange={(e) => set({ start_date: e.target.value })} />
        <label htmlFor="g-end">Sfârșitul</label>
        <input id="g-end" type="date" value={form.end_date} disabled={!editable} onChange={(e) => set({ end_date: e.target.value })} />
        <label htmlFor="g-closed">Închis</label>
        <span>
          <input id="g-closed" type="checkbox" checked={form.is_closed} disabled={!editable} onChange={(e) => set({ is_closed: e.target.checked })} />
        </span>
      </div>
      <p className="footer-note">
        Sursa de finanțare decide formulele: grant → 716 + 537/616, cotizații → 717, activitate economică → 718.
      </p>
      {editable && (
        <div className="bar">
          <button className="b primary" onClick={save} disabled={busy}>
            Salvează grantul
          </button>
        </div>
      )}
      {grantId && <BudgetLines grantId={grantId} editable={editable} />}
    </section>
  );
}

interface LineRow {
  id: string | null;
  code: string;
  name: string;
  planned_amount: string;
  cofinancing_amount: string;
  in_use: boolean;
  dirty: boolean;
}

function BudgetLines({ grantId, editable }: { grantId: string; editable: boolean }) {
  const { orgId } = useShell();
  const [rows, setRows] = useState<LineRow[]>([]);
  const { busy, error, info, run } = useAction();
  const base = `/organizations/${orgId}`;

  const load = useCallback(
    () =>
      api<BudgetLineDetail[]>(`${base}/grants/${grantId}/budget-lines`).then((lines) =>
        setRows(
          lines.map((l) => ({
            id: l.id,
            code: l.code,
            name: l.name,
            planned_amount: money(l.planned_amount),
            cofinancing_amount: l.cofinancing_amount ? money(l.cofinancing_amount) : "",
            in_use: l.in_use,
            dirty: false,
          })),
        ),
      ),
    [base, grantId],
  );

  useEffect(() => {
    load();
  }, [load]);

  const set = (i: number, patch: Partial<LineRow>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch, dirty: true } : r)));

  const save = (r: LineRow) =>
    run(async () => {
      const planned = parseAmount(r.planned_amount);
      if (planned === null) throw new Error(`Linia ${r.code}: suma planificată nu e un număr`);
      const body = {
        code: r.code.trim(),
        name: r.name.trim(),
        planned_amount: planned,
        cofinancing_amount: r.cofinancing_amount ? parseAmount(r.cofinancing_amount) : null,
      };
      if (r.id) await api(`${base}/budget-lines/${r.id}`, { method: "PUT", body });
      else await api(`${base}/grants/${grantId}/budget-lines`, { method: "POST", body });
      await load();
      refreshCatalogs(orgId);
      return `Linia ${body.code} a fost salvată.`;
    });

  const remove = (r: LineRow, i: number) =>
    run(async () => {
      if (r.id) {
        await api(`${base}/budget-lines/${r.id}`, { method: "DELETE" });
        refreshCatalogs(orgId);
      }
      setRows((rs) => rs.filter((_, j) => j !== i));
      return r.id ? `Linia ${r.code} a fost ștearsă.` : undefined;
    });

  const total = rows.reduce((s, r) => s + Number(parseAmount(r.planned_amount) ?? 0), 0);

  return (
    <>
      <h2>Linii de buget</h2>
      <Messages error={error} info={info} />
      <table className="grid edit">
        <thead>
          <tr>
            <th style={{ width: 80 }}>Cod</th>
            <th>Denumire</th>
            <th className="num">Planificat</th>
            <th className="num">din care cofinanțare</th>
            <th style={{ width: 170 }} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id ?? `new-${i}`}>
              <td>
                <input aria-label={`Cod linie ${i + 1}`} value={r.code} disabled={!editable} onChange={(e) => set(i, { code: e.target.value })} />
              </td>
              <td>
                <input aria-label={`Denumire linie ${i + 1}`} value={r.name} disabled={!editable} onChange={(e) => set(i, { name: e.target.value })} />
              </td>
              <td className="num">
                <input aria-label={`Planificat linie ${i + 1}`} className="num" value={r.planned_amount} disabled={!editable} onChange={(e) => set(i, { planned_amount: e.target.value })} />
              </td>
              <td className="num">
                <input aria-label={`Cofinanțare linie ${i + 1}`} className="num" value={r.cofinancing_amount} disabled={!editable} onChange={(e) => set(i, { cofinancing_amount: e.target.value })} />
              </td>
              <td>
                {editable && (
                  <span className="pair">
                    <button className="b" disabled={busy || !r.dirty} onClick={() => save(r)}>
                      Salvează
                    </button>
                    <button className="b" disabled={busy || r.in_use} title={r.in_use ? "Folosită în documente" : "Șterge"} onClick={() => remove(r, i)}>
                      Șterge
                    </button>
                  </span>
                )}
              </td>
            </tr>
          ))}
          <tr className="total-row">
            <td colSpan={2}>Total linii</td>
            <td className="num">{money(total)}</td>
            <td colSpan={2} />
          </tr>
        </tbody>
      </table>
      {editable && (
        <div className="bar" style={{ marginTop: 8 }}>
          <button
            className="b"
            onClick={() => setRows((rs) => [...rs, { id: null, code: "", name: "", planned_amount: "", cofinancing_amount: "", in_use: false, dirty: true }])}
          >
            Adaugă linie
          </button>
        </div>
      )}
      <p className="footer-note">O linie folosită în facturi sau înregistrări nu se șterge; i se poate schimba denumirea sau suma.</p>
    </>
  );
}
