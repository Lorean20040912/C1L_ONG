import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { ROLE_LABELS, type Member, type UserRole } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { day } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";
import { Messages } from "./Messages";

const ROLE_RIGHTS: Record<UserRole, string> = {
  admin: "utilizatori, organizații, setări",
  chief_accountant: "tot ce face contabilul + închiderea perioadei, politica, regulile",
  accountant: "documente, înregistrări, salarii, rapoarte",
  project_manager: "vizualizează execuția bugetului",
  auditor: "doar citire",
};

/** Utilizatorii organizației și rolurile lor (ToR §3) — doar pentru administrator. */
export function MembersScreen() {
  const { orgId, role } = useShell();
  const { user } = useAuth();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("accountant");
  const { busy, error, info, run } = useAction();
  const base = `/organizations/${orgId}/members`;

  const load = useCallback(() => api<Member[]>(base).then(setMembers), [base]);

  useEffect(() => {
    if (role === "admin") load();
  }, [role, load]);

  if (role !== "admin") {
    return (
      <>
        <h1>Utilizatori și drepturi</h1>
        <div className="hint">Utilizatorii și drepturile le gestionează administratorul organizației.</div>
      </>
    );
  }

  const add = () =>
    run(async () => {
      await api(base, {
        method: "POST",
        body: { email: email.trim(), full_name: fullName.trim() || null, password: password || null, role: newRole },
      });
      setEmail("");
      setFullName("");
      setPassword("");
      await load();
      return "Utilizatorul are acum acces la organizație.";
    });

  const changeRole = (m: Member, r: UserRole) =>
    run(async () => {
      await api(`${base}/${m.id}`, { method: "PATCH", body: { role: r } });
      await load();
      return `${m.full_name}: rolul este acum „${ROLE_LABELS[r]}”.`;
    });

  const remove = (m: Member) =>
    run(async () => {
      if (!window.confirm(`Retrageți accesul lui ${m.full_name} la organizație?`)) return;
      await api(`${base}/${m.id}`, { method: "DELETE" });
      await load();
      return `${m.full_name} nu mai are acces la organizație.`;
    });

  return (
    <>
      <h1>Utilizatori și drepturi</h1>
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Nume</th>
            <th>E-mail</th>
            <th>Rol</th>
            <th>Ultima intrare</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {members?.map((m) => (
            <tr key={m.id}>
              <td>
                {m.full_name}
                {m.email === user?.email && <span className="muted"> (dvs.)</span>}
              </td>
              <td>{m.email}</td>
              <td>
                <select aria-label={`Rolul lui ${m.full_name}`} value={m.role} disabled={busy} onChange={(e) => changeRole(m, e.target.value as UserRole)}>
                  {Object.entries(ROLE_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </td>
              <td>{day(m.last_login_at)}</td>
              <td>
                <button className="link" onClick={() => remove(m)} disabled={busy}>
                  retrage accesul
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <section>
        <h2>Adaugă un utilizator</h2>
        <div className="form">
          <label htmlFor="m-email">E-mail</label>
          <input id="m-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <label htmlFor="m-role">Rol</label>
          <select id="m-role" value={newRole} onChange={(e) => setNewRole(e.target.value as UserRole)}>
            {Object.entries(ROLE_LABELS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <label htmlFor="m-name">Nume (utilizator nou)</label>
          <input id="m-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          <label htmlFor="m-pass">Parola inițială</label>
          <input id="m-pass" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="min. 8 caractere" />
        </div>
        <div className="hint">
          Dacă e-mailul există deja (utilizatorul lucrează și în altă bază), primește doar rolul aici — numele și parola nu sunt necesare.
          <br />
          Rolul „{ROLE_LABELS[newRole]}”: {ROLE_RIGHTS[newRole]}.
        </div>
        <div className="bar">
          <button className="b primary" onClick={add} disabled={busy || !email.trim()}>
            Adaugă
          </button>
        </div>
      </section>
    </>
  );
}
