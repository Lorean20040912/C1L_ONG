import { useState } from "react";
import { api } from "../../api/client";
import { refreshCatalogs, useCatalogs } from "../../catalog/useCatalogs";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "./Messages";

/** Conturile bancare ale organizației, legate de conturile contabile 242 / 243 (și, opțional, de un grant). */
export function BankAccountsScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [iban, setIban] = useState("");
  const [bankName, setBankName] = useState("");
  const [currency, setCurrency] = useState("MDL");
  const [accountId, setAccountId] = useState("");
  const [grantId, setGrantId] = useState("");
  const { busy, error, info, run } = useAction();
  const editable = can(role, ADMIN_ROLES);

  const code = (id: string | null) => catalogs.accounts.find((a) => a.id === id)?.code ?? "";
  const grant = (id: string | null) => catalogs.grants.find((g) => g.id === id)?.code ?? "";

  const save = () =>
    run(async () => {
      if (!accountId) throw new Error("Alegeți contul contabil (242 pentru lei, 243 pentru valută)");
      await api(`/organizations/${orgId}/bank-accounts`, {
        method: "POST",
        body: { iban: iban.trim(), bank_name: bankName.trim() || null, currency, account_id: accountId, grant_id: grantId || null },
      });
      refreshCatalogs(orgId);
      setIban("");
      setBankName("");
      setGrantId("");
      return "Contul bancar a fost adăugat.";
    });

  return (
    <>
      <h1>Conturi bancare</h1>
      <ReadOnlyNote show={!editable} what="conturile le adaugă administratorul sau contabilul-șef" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>IBAN</th>
            <th>Banca</th>
            <th>Valuta</th>
            <th>Cont contabil</th>
            <th>Grant dedicat</th>
          </tr>
        </thead>
        <tbody>
          {catalogs.bankAccounts.map((b) => (
            <tr key={b.id}>
              <td>{b.iban}</td>
              <td>{b.bank_name}</td>
              <td>{b.currency}</td>
              <td>{code(b.account_id)}</td>
              <td>{grant(b.grant_id)}</td>
            </tr>
          ))}
          {catalogs.bankAccounts.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Nu sunt conturi bancare.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>Cont nou</h2>
          <div className="form">
            <label htmlFor="b-iban">IBAN</label>
            <input id="b-iban" value={iban} onChange={(e) => setIban(e.target.value)} placeholder="MD24AG000000022512345678" />
            <label htmlFor="b-bank">Banca</label>
            <input id="b-bank" value={bankName} onChange={(e) => setBankName(e.target.value)} />
            <label htmlFor="b-cur">Valuta</label>
            <select id="b-cur" value={currency} onChange={(e) => setCurrency(e.target.value)}>
              {["MDL", "EUR", "USD", "RON"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <label htmlFor="b-acc">Cont contabil</label>
            <select id="b-acc" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">— alegeți —</option>
              {catalogs.accounts
                .filter((a) => a.code.startsWith("24") && !a.is_group)
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.code} {a.name}
                  </option>
                ))}
            </select>
            <label htmlFor="b-grant">Grant dedicat</label>
            <select id="b-grant" value={grantId} onChange={(e) => setGrantId(e.target.value)}>
              <option value="">— nu —</option>
              {catalogs.grants.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.code} {g.title}
                </option>
              ))}
            </select>
          </div>
          <div className="hint">Contul dedicat unui grant: încasările pe el se înregistrează ca tranșe ale grantului.</div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy || !iban.trim()}>
              Adaugă contul
            </button>
          </div>
        </section>
      )}
    </>
  );
}
