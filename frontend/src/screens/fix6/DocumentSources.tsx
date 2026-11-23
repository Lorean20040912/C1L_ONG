import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { DocSource } from "../../api/fix6";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const KINDS: Record<DocSource["kind"], { label: string; hint: string }> = {
  google_drive: { label: "Google Drive", hint: "https://drive.google.com/drive/folders/…" },
  local_agent: { label: "Folder local (prin agent)", hint: "C:\\Scanări\\Facturi" },
  server_folder: { label: "Folder pe server", hint: "/srv/scanari/organizatia" },
};
const EMPTY = { kind: "google_drive" as DocSource["kind"], name: "", location: "", note: "", is_active: true };

/** Surse de documente: de unde se preiau scanurile — Google Drive, folder local prin agent sau folder pe server. */
export function DocumentSources() {
  const { orgId, role } = useShell();
  const [rows, setRows] = useState<DocSource[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState<string | null>(null);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/document-sources`;

  const load = useCallback(() => {
    api<DocSource[]>(base).then(setRows).catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const body = () => ({ ...form, name: form.name.trim(), location: form.location.trim(), note: form.note.trim() || null });
  const save = () =>
    run(async () => {
      if (form.name.trim().length < 2) throw new Error("Completați denumirea sursei");
      if (!form.location.trim()) throw new Error("Indicați linkul sau calea folderului");
      await api(editId ? `${base}/${editId}` : base, { method: editId ? "PUT" : "POST", body: body() });
      setForm(EMPTY);
      setEditId(null);
      load();
      return "Sursa a fost salvată.";
    });
  const toggle = (s: DocSource) =>
    run(async () => {
      await api(`${base}/${s.id}`, { method: "PUT", body: { kind: s.kind, name: s.name, location: s.location, note: s.note, is_active: !s.is_active } });
      load();
      return s.is_active ? "Sursa a fost dezactivată." : "Sursa a fost activată.";
    });
  const remove = (s: DocSource) =>
    run(async () => {
      if (!window.confirm(`Ștergeți sursa „${s.name}”?`)) return;
      await api(`${base}/${s.id}`, { method: "DELETE" });
      load();
      return "Sursa a fost ștearsă.";
    });

  return (
    <>
      <h1>Surse de documente (Drive / folder)</h1>
      <ReadOnlyNote show={!editable} what="sursele le configurează administratorul sau contabilul-șef" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Denumirea</th>
            <th>Tipul</th>
            <th>Locația</th>
            <th className="num">Documente</th>
            <th>Activă</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              <td>{s.name}</td>
              <td>{KINDS[s.kind].label}</td>
              <td>{s.location}</td>
              <td className="num">{s.documents}</td>
              <td>{s.is_active ? "da" : "nu"}</td>
              <td>
                {editable && (
                  <>
                    <button className="b" onClick={() => { setEditId(s.id); setForm({ kind: s.kind, name: s.name, location: s.location, note: s.note ?? "", is_active: s.is_active }); }}>
                      Modifică
                    </button>{" "}
                    <button className="b" onClick={() => toggle(s)} disabled={busy}>
                      {s.is_active ? "Dezactivează" : "Activează"}
                    </button>{" "}
                    <button className="b" onClick={() => remove(s)} disabled={busy}>
                      Șterge
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                Nu sunt surse de documente.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>{editId ? "Modificare" : "Sursă nouă"}</h2>
          <div className="form">
            <label htmlFor="ds-kind">Tipul</label>
            <select id="ds-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as DocSource["kind"] })}>
              {Object.entries(KINDS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
            <label htmlFor="ds-name">Denumirea</label>
            <input id="ds-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label htmlFor="ds-loc">Linkul / calea</label>
            <input id="ds-loc" value={form.location} placeholder={KINDS[form.kind].hint} onChange={(e) => setForm({ ...form, location: e.target.value })} />
            <label htmlFor="ds-note">Observații</label>
            <input id="ds-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              Salvează
            </button>
            {editId && (
              <button className="b" onClick={() => { setEditId(null); setForm(EMPTY); }}>
                Renunță
              </button>
            )}
          </div>
        </section>
      )}
    </>
  );
}
