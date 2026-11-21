import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { DESIGNATION_LABELS, type CostItem } from "../../api/types";
import { refreshCatalogs, useCatalogs } from "../../catalog/useCatalogs";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

interface Draft {
  id?: string;
  name: string;
  con5_article: string;
  designation_category: string;
}

const EMPTY: Draft = { name: "", con5_article: "", designation_category: "" };

/** Articolele de cheltuieli: rândul din 5-CON și categoria din anexa 1D a ONG17. */
export function CostItemsScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [articles, setArticles] = useState<{ code: string; label: string }[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const { busy, error, info, run } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/cost-items`;

  useEffect(() => {
    api<{ code: string; label: string }[]>(`/organizations/${orgId}/con5-articles`).then(setArticles).catch(() => setArticles([]));
  }, [orgId]);

  const article = (code: string | null) => {
    const a = articles.find((x) => x.code === code);
    return code ? `${code}${a ? ` ${a.label}` : ""}` : "";
  };

  const save = () =>
    run(async () => {
      if (!draft.name.trim()) throw new Error("Completați denumirea");
      const body = { name: draft.name.trim(), con5_article: draft.con5_article || null, designation_category: draft.designation_category || null };
      await api(draft.id ? `${base}/${draft.id}` : base, { method: draft.id ? "PUT" : "POST", body });
      refreshCatalogs(orgId);
      setDraft(EMPTY);
      return draft.id ? "Articolul a fost modificat." : "Articolul a fost adăugat.";
    });

  const remove = (item: CostItem) =>
    window.confirm(`Ștergeți articolul „${item.name}”?`) &&
    run(async () => {
      await api(`${base}/${item.id}`, { method: "DELETE" });
      refreshCatalogs(orgId);
      return "Articolul a fost șters.";
    });

  return (
    <>
      <h1>Articole de cheltuieli</h1>
      <p className="muted">
        Articolul se alege pe rândul facturii sau pe linia de buget; rândul 5-CON și categoria desemnării procentuale (ONG17, anexa 1D) se
        completează automat din el.
      </p>
      <ReadOnlyNote show={!editable} what="articolele le adaugă contabilul" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Denumire</th>
            <th>Rândul 5-CON</th>
            <th>Categoria (anexa 1D)</th>
            {editable && <th />}
          </tr>
        </thead>
        <tbody>
          {catalogs.costItems.map((c) => (
            <tr key={c.id} className={draft.id === c.id ? "sel" : ""}>
              <td>{c.name}</td>
              <td>{article(c.con5_article)}</td>
              <td>{c.designation_category ? DESIGNATION_LABELS[c.designation_category] : ""}</td>
              {editable && (
                <td>
                  <button
                    className="link"
                    onClick={() => setDraft({ id: c.id, name: c.name, con5_article: c.con5_article ?? "", designation_category: c.designation_category ?? "" })}
                  >
                    modifică
                  </button>{" "}
                  <button className="link" onClick={() => remove(c)}>
                    șterge
                  </button>
                </td>
              )}
            </tr>
          ))}
          {catalogs.costItems.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                Nu sunt articole de cheltuieli.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>{draft.id ? "Modificarea articolului" : "Articol nou"}</h2>
          <div className="form">
            <label htmlFor="ci-name">Denumire</label>
            <input id="ci-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <label htmlFor="ci-con5">Rândul 5-CON</label>
            <select id="ci-con5" value={draft.con5_article} onChange={(e) => setDraft({ ...draft, con5_article: e.target.value })}>
              <option value="">— fără (rândul 230) —</option>
              {articles.map((a) => (
                <option key={a.code} value={a.code}>
                  {a.code} {a.label}
                </option>
              ))}
            </select>
            <label htmlFor="ci-cat">Categoria desemnării</label>
            <select id="ci-cat" value={draft.designation_category} onChange={(e) => setDraft({ ...draft, designation_category: e.target.value })}>
              <option value="">—</option>
              {Object.entries(DESIGNATION_LABELS).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              {draft.id ? "Salvează" : "Adaugă"}
            </button>
            {draft.id && (
              <button className="b" onClick={() => setDraft(EMPTY)}>
                Renunță
              </button>
            )}
          </div>
        </section>
      )}
    </>
  );
}
