import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { BankFormat, BankImport } from "../../api/types";
import { useCatalogs } from "../../catalog/useCatalogs";
import { useAction } from "../../lib/useAction";
import { day, money } from "../../lib/format";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

const MATCH: Record<string, string> = {
  exported_order: "ordin exportat",
  new_draft: "ciornă nouă",
};

function toBase64(buf: ArrayBuffer): string {
  let s = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

/** Importul extrasului bancar: previzualizare (dry_run), apoi import propriu-zis. */
export function BankImportScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [formats, setFormats] = useState<BankFormat[]>([]);
  const [history, setHistory] = useState<BankImport[]>([]);
  const [accountId, setAccountId] = useState("");
  const [formatId, setFormatId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<BankImport | null>(null);
  const { busy, error, info, run } = useAction();
  const allowed = can(role, POSTING_ROLES);

  const loadHistory = () => api<BankImport[]>(`/organizations/${orgId}/bank-imports`).then(setHistory).catch(() => {});
  useEffect(() => {
    api<BankFormat[]>(`/organizations/${orgId}/bank-formats?direction=import`).then(setFormats).catch(() => {});
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  const send = (dryRun: boolean) =>
    run(async () => {
      if (!accountId || !formatId || !file) throw new Error("Alegeți contul, formatul băncii și fișierul");
      const res = await api<BankImport>(`/organizations/${orgId}/bank-imports`, {
        method: "POST",
        body: {
          bank_account_id: accountId,
          format_id: formatId,
          file_name: file.name,
          content_base64: toBase64(await file.arrayBuffer()),
          dry_run: dryRun,
        },
      });
      setResult(res);
      if (!dryRun) loadHistory();
      return dryRun
        ? `Previzualizare: ${res.rows_created} rânduri noi, ${res.rows_skipped} duplicate.`
        : `Importat: ${res.rows_created} rânduri noi, ${res.rows_skipped} sărite (duplicate), ${res.rows_failed} cu erori.`;
    });

  return (
    <>
      <h1>Import extras bancar</h1>
      <Messages error={error} info={info} />
      {allowed && (
        <div className="form">
          <label htmlFor="i-acc">Cont bancar</label>
          <select id="i-acc" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="" />
            {catalogs.bankAccounts.map((b) => (
              <option key={b.id} value={b.id}>
                {b.iban} {b.bank_name ?? ""}
              </option>
            ))}
          </select>
          <label htmlFor="i-fmt">Format</label>
          <select id="i-fmt" value={formatId} onChange={(e) => setFormatId(e.target.value)}>
            <option value="" />
            {formats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.bank_name} ({f.file_type})
              </option>
            ))}
          </select>
          <label htmlFor="i-file">Fișier</label>
          <input id="i-file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="bar">
            <button className="b" disabled={busy} onClick={() => send(true)}>
              Previzualizare
            </button>
            <button className="b primary" disabled={busy} onClick={() => send(false)}>
              Importă
            </button>
          </div>
        </div>
      )}
      {result && (
        <section>
          <h2>{result.dry_run ? "Previzualizare" : "Rezultat"}</h2>
          {result.errors.length > 0 && (
            <div className="error">{result.errors.map((e) => (typeof e === "string" ? e : JSON.stringify(e))).join("; ")}</div>
          )}
          <table className="grid">
            <thead>
              <tr>
                <th>Data</th>
                <th>Nr.</th>
                <th>D/C</th>
                <th>Contrapartidă</th>
                <th className="num">Suma</th>
                <th>Valuta</th>
                <th>Destinația</th>
                <th>Potrivire</th>
              </tr>
            </thead>
            <tbody>
              {result.transactions.map((t) => (
                <tr key={t.id}>
                  <td>{day(t.tx_date)}</td>
                  <td>{t.doc_number}</td>
                  <td>{t.direction === "outgoing" ? "Plată" : "Încasare"}</td>
                  <td>{t.counterparty_name}</td>
                  <td className="num">{money(t.amount)}</td>
                  <td>{t.currency}</td>
                  <td>{t.purpose}</td>
                  <td>{t.match ? (MATCH[t.match] ?? t.match) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <section>
        <h2>Importuri anterioare</h2>
        <table className="grid">
          <thead>
            <tr>
              <th>Data</th>
              <th>Fișier</th>
              <th className="num">Total</th>
              <th className="num">Create</th>
              <th className="num">Duplicate</th>
              <th className="num">Erori</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.id}>
                <td>{day(h.imported_at)}</td>
                <td>{h.file_name}</td>
                <td className="num">{h.rows_total}</td>
                <td className="num">{h.rows_created}</td>
                <td className="num">{h.rows_skipped}</td>
                <td className="num">{h.rows_failed}</td>
              </tr>
            ))}
            {history.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Nu sunt importuri.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
