// Tipărirea documentelor: se deschide o fereastră cu formularul și se cheamă dialogul de tipărire
// (de acolo se poate alege și „Salvare ca PDF”).

export interface PrintField {
  label: string;
  value: string;
}

export interface PrintTable {
  head: string[];
  rows: string[][];
  foot?: string[];
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function printDocument(opts: {
  title: string;
  organization?: string;
  fields: PrintField[];
  table?: PrintTable;
  note?: string;
  signatures: string[];
}): boolean {
  const w = window.open("", "_blank", "width=820,height=900");
  if (!w) return false;
  const table = opts.table
    ? `<table><thead><tr>${opts.table.head.map((h, i) => `<th${i >= opts.table!.head.length - 1 ? ' class="n"' : ""}>${esc(h)}</th>`).join("")}</tr></thead><tbody>${opts.table.rows
        .map((r) => `<tr>${r.map((c, i) => `<td${i >= r.length - 1 ? ' class="n"' : ""}>${esc(c)}</td>`).join("")}</tr>`)
        .join("")}</tbody>${opts.table.foot ? `<tfoot><tr>${opts.table.foot.map((c, i) => `<td${i >= opts.table!.head.length - 1 ? ' class="n"' : ""}><b>${esc(c)}</b></td>`).join("")}</tr></tfoot>` : ""}</table>`
    : "";
  w.document.write(`<!doctype html><html lang="ro"><head><meta charset="utf-8"><title>${esc(opts.title)}</title>
<style>
body{font:13px/1.45 Arial,sans-serif;margin:28px 36px;color:#000}
h1{font-size:18px;text-align:center;margin:10px 0 18px}
.org{font-weight:bold}
dl{display:grid;grid-template-columns:190px 1fr;gap:5px 10px;margin:0 0 14px}
dt{color:#444}dd{margin:0;border-bottom:1px dotted #888;min-height:17px}
table{width:100%;border-collapse:collapse;margin:10px 0}
th,td{border:1px solid #444;padding:4px 6px;text-align:left}.n{text-align:right}
.sig{display:flex;gap:40px;margin-top:46px}.sig div{flex:1;border-top:1px solid #000;padding-top:3px;font-size:12px}
@media print{body{margin:12mm}}
</style></head><body>
${opts.organization ? `<div class="org">${esc(opts.organization)}</div>` : ""}
<h1>${esc(opts.title)}</h1>
<dl>${opts.fields.map((f) => `<dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd>`).join("")}</dl>
${table}
${opts.note ? `<p>${esc(opts.note)}</p>` : ""}
<div class="sig">${opts.signatures.map((s) => `<div>${esc(s)}</div>`).join("")}</div>
</body></html>`);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 150);
  return true;
}
