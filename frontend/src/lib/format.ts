// Formatul din 1C: „1 234,56” și „03.11.2026”.

export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  const [int, frac] = n.toFixed(2).split(".");
  return `${int.replace(/\B(?=(\d{3})+(?!\d))/g, " ")},${frac}`;
}

export function day(value: string | null | undefined): string {
  if (!value) return "";
  const [y, m, d] = value.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

export function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Suma introdusă de utilizator („1 234,5”) → „1234.50” pentru API; null dacă nu e număr. */
export function parseAmount(text: string): string | null {
  const clean = text.replace(/[\s ]/g, "").replace(",", ".");
  if (clean === "" || !/^-?\d+(\.\d{0,2})?$/.test(clean)) return null;
  return Number(clean).toFixed(2);
}
