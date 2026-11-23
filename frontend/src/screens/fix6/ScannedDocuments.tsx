import { useCallback, useEffect, useRef, useState } from "react";
import { api, openFile } from "../../api/client";
import type { DocSource, Scan } from "../../api/fix6";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, parseAmount } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const STATUS: Record<Scan["status"], string> = {
  new: "nou",
  ai_processed: "citit de AI",
  to_review: "de verificat",
  validated: "validat",
  rejected: "respins",
};
const TYPES: Record<string, string> = { invoice: "factură", receipt: "bon / chitanță", act: "act", contract: "contract", other: "altele" };
const MIME_BY_EXT: Record<string, string> = { pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg" };

function toBase64(buf: ArrayBuffer): string {
  let s = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

/** Documente scanate: încărcare, citirea câmpurilor de către AI, verificare și validare de contabil. */
export function ScannedDocuments() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<Scan[]>([]);
  const [sources, setSources] = useState<DocSource[]>([]);
  const [filter, setFilter] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [sel, setSel] = useState<Scan | null>(null);
  const [form, setForm] = useState({ type: "other", counterparty_id: "", doc_number: "", doc_date: "", total_amount: "", currency: "MDL" });
  const fileInput = useRef<HTMLInputElement>(null);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/scanned-documents`;

  const load = useCallback(() => {
    api<Scan[]>(`${base}${filter ? `?status_filter=${filter}` : ""}`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [base, filter, setError]);
  useEffect(load, [load]);
  useEffect(() => {
    api<DocSource[]>(`/organizations/${orgId}/document-sources`).then((s) => setSources(s.filter((x) => x.is_active))).catch(() => {});
  }, [orgId]);

  const choose = (s: Scan) => {
    setSel(s);
    setForm({
      type: s.type ?? "other", counterparty_id: s.counterparty_id ?? "", doc_number: s.doc_number ?? "",
      doc_date: s.doc_date ?? "", total_amount: s.total_amount ?? "", currency: s.currency ?? "MDL",
    });
  };
  const refresh = (s: Scan) => {
    setRows((r) => r.map((x) => (x.id === s.id ? s : x)));
    choose(s);
  };

  const upload = (files: FileList | null) =>
    run(async () => {
      const list = Array.from(files ?? []);
      if (list.length === 0) return;
      let ok = 0;
      const problems: string[] = [];
      for (const f of list) {
        const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
        const mime = MIME_BY_EXT[ext];
        if (!mime) {
          problems.push(`${f.name}: se acceptă PDF, PNG sau JPEG`);
          continue;
        }
        if (f.size > 10 * 1024 * 1024) {
          problems.push(`${f.name}: depășește 10 MB`);
          continue;
        }
        try {
          await api(base, { method: "POST", body: { file_name: f.name, mime_type: mime, content_base64: toBase64(await f.arrayBuffer()), source_id: sourceId || null } });
          ok += 1;
        } catch (e) {
          problems.push(`${f.name}: ${(e as Error).message}`);
        }
      }
      if (fileInput.current) fileInput.current.value = "";
      load();
      if (problems.length) throw new Error(`${ok} încărcate. ${problems.join("; ")}`);
      return `${ok} documente încărcate.`;
    });

  const patchBody = () => {
    const sum = form.total_amount.trim() ? parseAmount(form.total_amount) : null;
    if (form.total_amount.trim() && (!sum || Number(sum) <= 0)) throw new Error("Suma trebuie să fie pozitivă, cu cel mult 2 zecimale");
    return {
      type: form.type, counterparty_id: form.counterparty_id || null, doc_number: form.doc_number.trim() || null,
      doc_date: form.doc_date || null, total_amount: sum, currency: form.currency.trim().toUpperCase() || null,
    };
  };
  const save = () =>
    run(async () => {
      refresh(await api<Scan>(`${base}/${sel!.id}`, { method: "PATCH", body: patchBody() }));
      return "Câmpurile au fost salvate.";
    });
  const post = (s: Scan, action: "extract" | "validate" | "reject" | "reopen", done: string, save_first = false) =>
    run(async () => {
      if (save_first) await api(`${base}/${s.id}`, { method: "PATCH", body: patchBody() });
      refresh(await api<Scan>(`${base}/${s.id}/${action}`, { method: "POST" }));
      return done;
    });
  const remove = (s: Scan) =>
    run(async () => {
      if (!window.confirm(`Ștergeți documentul „${s.file_name}”?`)) return;
      await api(`${base}/${s.id}`, { method: "DELETE" });
      setSel(null);
      load();
      return "Documentul a fost șters.";
    });

  const locked = sel?.status === "validated";

  return (
    <>
      <h1>Documente scanate (AI)</h1>
      <ReadOnlyNote show={!editable} what="scanurile le încarcă și le validează contabilul" />
      <div className="bar">
        <label>
          Starea{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Starea">
            <option value="">toate</option>
            {Object.entries(STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        {editable && (
          <>
            <label>
              Sursa{" "}
              <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} aria-label="Sursa">
                <option value="">încărcare manuală</option>
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <input ref={fileInput} type="file" multiple accept=".pdf,.png,.jpg,.jpeg" aria-label="Fișiere de încărcat" onChange={(e) => upload(e.target.files)} disabled={busy} />
          </>
        )}
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Fișierul</th>
            <th>Tipul</th>
            <th>Furnizorul</th>
            <th>Nr.</th>
            <th>Data</th>
            <th className="num">Suma</th>
            <th>Starea</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} className={sel?.id === s.id ? "sel" : ""} onClick={() => choose(s)}>
              <td>{s.file_name}</td>
              <td>{TYPES[s.type ?? "other"]}</td>
              <td>{s.counterparty}</td>
              <td>{s.doc_number}</td>
              <td>{day(s.doc_date)}</td>
              <td className="num">{s.total_amount ? `${money(s.total_amount)} ${s.currency ?? ""}` : ""}</td>
              <td>{STATUS[s.status]}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                Nu sunt documente scanate. Încărcați PDF, PNG sau JPEG (până la 10 MB).
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {sel && (
        <section>
          <h2>{sel.file_name}</h2>
          <div className="bar">
            <button className="b" onClick={() => run(() => openFile(`${base}/${sel.id}/file`))}>
              Vezi scanul
            </button>
            {editable && !locked && (
              <button className="b" onClick={() => post(sel, "extract", "AI a citit documentul; verificați câmpurile.")} disabled={busy}>
                Citește cu AI
              </button>
            )}
          </div>
          {sel.ai_fields && (
            <div className="hint">
              Propus de AI:{" "}
              {Object.entries(sel.ai_fields)
                .map(([k, v]) => `${k} = ${String(v)}`)
                .join("; ")}
            </div>
          )}
          <div className="form">
            <label htmlFor="sc-type">Tipul</label>
            <select id="sc-type" value={form.type} disabled={!editable || locked} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {Object.entries(TYPES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <label htmlFor="sc-cp">Furnizorul</label>
            <select id="sc-cp" value={form.counterparty_id} disabled={!editable || locked} onChange={(e) => setForm({ ...form, counterparty_id: e.target.value })}>
              <option value="">— alegeți —</option>
              {catalogs.counterparties.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.idno ?? ""}
                </option>
              ))}
            </select>
            <label htmlFor="sc-nr">Număr</label>
            <input id="sc-nr" value={form.doc_number} disabled={!editable || locked} onChange={(e) => setForm({ ...form, doc_number: e.target.value })} />
            <label htmlFor="sc-date">Data</label>
            <input id="sc-date" type="date" value={form.doc_date} disabled={!editable || locked} onChange={(e) => setForm({ ...form, doc_date: e.target.value })} />
            <label htmlFor="sc-sum">Suma</label>
            <input id="sc-sum" className="num" value={form.total_amount} disabled={!editable || locked} onChange={(e) => setForm({ ...form, total_amount: e.target.value })} />
            <label htmlFor="sc-cur">Valuta</label>
            <input id="sc-cur" value={form.currency} maxLength={3} disabled={!editable || locked} onChange={(e) => setForm({ ...form, currency: e.target.value })} />
          </div>
          {editable && (
            <div className="bar">
              {!locked && (
                <>
                  <button className="b" onClick={save} disabled={busy}>
                    Salvează
                  </button>
                  <button className="b primary" onClick={() => post(sel, "validate", "Documentul a fost validat.", true)} disabled={busy}>
                    Validează
                  </button>
                  <button className="b" onClick={() => post(sel, "reject", "Documentul a fost respins.")} disabled={busy}>
                    Respinge
                  </button>
                </>
              )}
              {(locked || sel.status === "rejected") && !sel.is_posted && (
                <button className="b" onClick={() => post(sel, "reopen", "Documentul a fost redeschis pentru verificare.")} disabled={busy}>
                  Redeschide
                </button>
              )}
              {!locked && (
                <button className="b" onClick={() => remove(sel)} disabled={busy}>
                  Șterge
                </button>
              )}
            </div>
          )}
        </section>
      )}
    </>
  );
}
