import { useState } from "react";
import { api } from "../../api/client";
import type { AccountKind } from "../../api/types";
import { refreshCatalogs, useCatalogs } from "../../catalog/useCatalogs";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "./Messages";

const KIND: Record<AccountKind, string> = { active: "activ", passive: "pasiv", active_passive: "activ-pasiv" };

/** Planul de conturi al organizației, cu adăugarea unui cont sau subcont. */
export function AccountsScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [filter, setFilter] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<AccountKind>("active");
  const [parentId, setParentId] = useState("");
  const { busy, error, info, run } = useAction();
  const editable = can(role, ADMIN_ROLES);

  const add = () =>
    run(async () => {
      await api(`/organizations/${orgId}/accounts`, {
        method: "POST",
        body: { code: code.trim(), name: name.trim(), account_kind: kind, parent_id: parentId || null },
      });
      refreshCatalogs(orgId);
      const added = code.trim();
      setCode("");
      setName("");
      setParentId("");
      return `Contul ${added} a fost adăugat.`;
    });

  const q = filter.trim().toLowerCase();
  const visible = catalogs.accounts.filter((a) => !q || `${a.code} ${a.name}`.toLowerCase().includes(q));

  return (
    <>
      <h1>Planul de conturi</h1>
      <Messages error={error} info={info} />
      <div className="bar">
        <input className="b" placeholder="Căutare: cod sau denumire" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Căutare în planul de conturi" />
      </div>
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 90 }}>Cod</th>
            <th>Denumire</th>
            <th>Tip</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((a) => (
            <tr key={a.id}>
              <td style={{ paddingLeft: a.parent_id ? 22 : 8 }}>{a.is_group ? <b>{a.code}</b> : a.code}</td>
              <td>{a.name}</td>
              <td className="muted">{a.account_kind ? KIND[a.account_kind] : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>Cont sau subcont nou</h2>
          <div className="form">
            <label htmlFor="a-code">Cod</label>
            <input id="a-code" value={code} placeholder="ex. 217 sau 242.1" onChange={(e) => setCode(e.target.value)} />
            <label htmlFor="a-kind">Tip</label>
            <select id="a-kind" value={kind} onChange={(e) => setKind(e.target.value as AccountKind)}>
              {Object.entries(KIND).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <label htmlFor="a-name">Denumire</label>
            <input id="a-name" className="wide" value={name} onChange={(e) => setName(e.target.value)} />
            <label htmlFor="a-parent">Subcont al</label>
            <select id="a-parent" value={parentId} onChange={(e) => setParentId(e.target.value)}>
              <option value="">—</option>
              {catalogs.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </select>
          </div>
          <div className="bar">
            <button className="b primary" onClick={add} disabled={busy || !code.trim() || !name.trim()}>
              Adaugă contul
            </button>
          </div>
        </section>
      )}
    </>
  );
}
