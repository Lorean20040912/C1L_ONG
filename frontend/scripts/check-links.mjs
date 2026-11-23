// Parcurge sections.ts și SCREEN_LINKS (tabs.ts): fiecare legătură din meniu trebuie să ducă
// la un ecran real (un `case` în AppShell.tsx), nu la placeholder. Ieșire ≠ 0 dacă nu.
import { readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`../src/shell/${f}`, import.meta.url), "utf8");
const sections = read("sections.ts");
const tabs = read("tabs.ts");
const shell = read("AppShell.tsx");

const links = [];
for (const m of sections.matchAll(/^\s+(?:"[^"]+"|[^\s:"]+):\s*\[((?:\s*"[^"]*",?)+)\s*\]/gm))
  for (const t of m[1].matchAll(/"([^"]*)"/g)) links.push(t[1]);

const body = tabs.slice(tabs.indexOf("SCREEN_LINKS"));
const map = {};
for (const m of body.slice(0, body.indexOf("};")).matchAll(/^\s+(?:"([^"]+)"|([^\s:"]+)):\s*"([\w-]+)"/gm)) map[m[1] ?? m[2]] = m[3];

const cases = new Set([...shell.matchAll(/case "([\w-]+)":/g)].map((m) => m[1]));
const kinds = new Set([...tabs.slice(0, tabs.indexOf("export interface Tab")).matchAll(/\| "([\w-]+)"/g)].map((m) => m[1]));

// legăturile încă în lucru în sesiunea paralelă (încasări/plăți, decont de avans, servicii și facturi primite,
// datorii față de furnizori); se șterg de aici când își primesc ecranul
const PENDING_OTHER_SESSION = new Set([
  "Încasări pe cont", "Plăți din cont", "Încasări numerar", "Plăți numerar", "Decont de avans",
  "Servicii primite (acte)", "Facturi fiscale primite", "Datorii față de furnizori",
]);

const problems = [];
const pending = [];
for (const t of links) {
  const kind = map[t];
  if (!kind && PENDING_OTHER_SESSION.has(t)) {
    pending.push(t);
    continue;
  }
  if (!kind) problems.push(`„${t}”: fără intrare în SCREEN_LINKS (placeholder „în lucru”)`);
  else if (kind === "placeholder" || !kinds.has(kind)) problems.push(`„${t}”: tip necunoscut „${kind}”`);
  else if (!cases.has(kind) && kind !== "manual") problems.push(`„${t}”: AppShell nu are ecran pentru „${kind}”`);
}
const total = links.length;
console.log(`${total} legături în meniu, ${total - problems.length - pending.length} deschid ecrane reale, ${pending.length} în lucru în altă sesiune.`);
for (const t of pending) console.log(" …", t);
for (const p of problems) console.error(" ✖", p);
process.exit(problems.length ? 1 : 0);
