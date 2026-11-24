import type { SalesInvoice } from "../../api/sales";
import { day, money } from "../../lib/format";

const esc = (s: string | null | undefined) => (s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Factura fiscală pentru tipărire din browser („Salvare ca PDF”): furnizor, cumpărător, rânduri cu cote TVA, totaluri. */
export function printSalesInvoice(inv: SalesInvoice): boolean {
  const w = window.open("", "_blank", "width=860,height=1000");
  if (!w) return false;
  const credit = inv.kind === "credit_note";
  const title = `${credit ? "NOTĂ DE STORNARE" : "FACTURĂ FISCALĂ"} ${inv.series} ${inv.number}`.trim();
  const sign = credit ? "-" : "";
  const byRate = new Map<string, { base: number; vat: number }>();
  for (const l of inv.lines) {
    const k = String(Number(l.vat_rate));
    const t = byRate.get(k) ?? { base: 0, vat: 0 };
    t.base += Number(l.amount);
    t.vat += Number(l.vat_amount ?? 0);
    byRate.set(k, t);
  }
  const party = (label: string, p: SalesInvoice["seller"]) =>
    `<div class="party"><h3>${label}</h3><b>${esc(p.name)}</b><br>IDNO: ${esc(p.idno)}${p.vat_code ? `<br>Cod TVA: ${esc(p.vat_code)}` : ""}${p.address ? `<br>Adresa: ${esc(p.address)}` : ""}${(p.banks ?? []).map((b) => `<br>IBAN: ${esc(b)}`).join("")}</div>`;
  const rows = inv.lines
    .map(
      (l, i) =>
        `<tr><td>${i + 1}</td><td>${esc(l.description)}</td><td>${esc(l.unit)}</td><td class="n">${l.quantity ? Number(l.quantity) : ""}</td><td class="n">${l.unit_price ? money(l.unit_price) : ""}</td><td class="n">${sign}${money(l.amount)}</td><td class="n">${Number(l.vat_rate)}%</td><td class="n">${sign}${money(l.vat_amount)}</td><td class="n">${sign}${money(l.total)}</td></tr>`,
    )
    .join("");
  const rates = [...byRate.entries()].map(([r, t]) => `<tr><td>TVA ${r}%</td><td class="n">${sign}${money(t.base)}</td><td class="n">${sign}${money(t.vat)}</td></tr>`).join("");
  w.document.write(`<!doctype html><html lang="ro"><head><meta charset="utf-8"><title>${esc(title)}</title>
<style>
body{font:12.5px/1.45 Arial,sans-serif;margin:26px 34px;color:#000}
h1{font-size:18px;text-align:center;margin:6px 0 4px}.sub{text-align:center;margin-bottom:14px}
.parties{display:flex;gap:24px}.party{flex:1;border:1px solid #444;padding:8px 10px}.party h3{margin:0 0 4px;font-size:12px;text-transform:uppercase;color:#444}
table{width:100%;border-collapse:collapse;margin:12px 0}th,td{border:1px solid #444;padding:4px 6px;text-align:left}.n{text-align:right}
.tot{width:55%;margin-left:auto}.sig{display:flex;gap:40px;margin-top:46px}.sig div{flex:1;border-top:1px solid #000;padding-top:3px;font-size:12px}
@media print{body{margin:12mm}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="sub">din ${day(inv.doc_date)}${inv.due_date ? ` · scadența ${day(inv.due_date)}` : ""}${inv.currency && inv.currency !== "MDL" ? ` · valuta ${esc(inv.currency)}, curs BNM ${esc(inv.exchange_rate)}` : ""}${credit && inv.storno_number ? `<br>Stornează factura ${esc(inv.storno_number)}` : ""}</div>
<div class="parties">${party("Furnizor", inv.seller)}${party("Cumpărător", inv.client)}</div>
<table><thead><tr><th>Nr.</th><th>Denumirea</th><th>U.M.</th><th class="n">Cant.</th><th class="n">Preț</th><th class="n">Suma fără TVA</th><th class="n">Cota</th><th class="n">TVA</th><th class="n">Total</th></tr></thead><tbody>${rows}</tbody></table>
<table class="tot"><thead><tr><th>Cota</th><th class="n">Baza</th><th class="n">TVA</th></tr></thead><tbody>${rates}
<tr><td><b>Total fără TVA</b></td><td class="n" colspan="2"><b>${sign}${money(inv.net.replace("-", ""))}</b></td></tr>
<tr><td><b>Total TVA</b></td><td class="n" colspan="2"><b>${sign}${money(inv.vat.replace("-", ""))}</b></td></tr>
<tr><td><b>Total de plată (${esc(inv.currency)})</b></td><td class="n" colspan="2"><b>${sign}${money(inv.gross.replace("-", ""))}</b></td></tr></tbody></table>
${inv.notes ? `<p>${esc(inv.notes)}</p>` : ""}
<div class="sig"><div>Conducător${inv.seller.director ? `: ${esc(inv.seller.director)}` : ""}</div><div>Contabil-șef${inv.seller.accountant ? `: ${esc(inv.seller.accountant)}` : ""}</div><div>Primit de (cumpărător)</div></div>
</body></html>`);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 150);
  return true;
}
