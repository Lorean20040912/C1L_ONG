// Clientul HTTP: adaugă jetonul de acces și îl reînnoiește o dată la 401.

const BASE = "/api";
const ACCESS = "contahub.access";
const REFRESH = "contahub.refresh";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function saveTokens(tokens: TokenPair | null): void {
  try {
    if (tokens) {
      localStorage.setItem(ACCESS, tokens.access_token);
      localStorage.setItem(REFRESH, tokens.refresh_token);
    } else {
      localStorage.removeItem(ACCESS);
      localStorage.removeItem(REFRESH);
    }
  } catch {
    // stocare indisponibilă (mod privat) — sesiunea ține până la reîncărcare
  }
}

export function hasTokens(): boolean {
  return read(REFRESH) !== null;
}

interface ValidationItem {
  type?: string;
  loc?: (string | number)[];
  msg: string;
  ctx?: Record<string, unknown>;
}

/** Mesaj de validare FastAPI/pydantic în română, cu numele câmpului (fără prefixul „body”). */
function validationMessage(d: ValidationItem): string {
  const where = (d.loc ?? []).filter((x) => x !== "body" && x !== "query").map((x) => (typeof x === "number" ? `rândul ${x + 1}` : x)).join(" · ");
  const c = d.ctx ?? {};
  const t = d.type ?? "";
  let what: string;
  if (t === "missing") what = "este obligatoriu";
  else if (t === "greater_than") what = `trebuie să fie mai mare ca ${c.gt}`;
  else if (t === "greater_than_equal") what = `trebuie să fie cel puțin ${c.ge}`;
  else if (t === "less_than") what = `trebuie să fie mai mic ca ${c.lt}`;
  else if (t === "less_than_equal") what = `trebuie să fie cel mult ${c.le}`;
  else if (t === "string_too_short") what = Number(c.min_length) <= 1 ? "nu poate fi gol" : `trebuie să aibă cel puțin ${c.min_length} caractere`;
  else if (t === "string_too_long") what = `trebuie să aibă cel mult ${c.max_length} caractere`;
  else if (t === "too_short") what = "trebuie să conțină cel puțin un element";
  else if (t === "uuid_parsing") what = "are o valoare nevalidă (alegeți din listă)";
  else if (t.startsWith("date") || t.includes("datetime")) what = "nu este o dată validă";
  else if (t === "enum" || t === "literal_error") what = "are o valoare nepermisă";
  else if (t.startsWith("int") || t.startsWith("float") || t.startsWith("decimal") || t.includes("number")) what = "nu este un număr valid";
  else if (t === "string_pattern_mismatch") what = "are un format nevalid";
  else what = "este nevalid";
  return where ? `${where}: ${what}` : what[0].toUpperCase() + what.slice(1);
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map(validationMessage).join("; ");
  } catch {
    // răspuns fără JSON
  }
  return `Eroare ${res.status}`;
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const refresh_token = read(REFRESH);
  if (!refresh_token) return false;
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
  if (!res.ok) {
    saveTokens(null);
    return false;
  }
  saveTokens(await res.json());
  return true;
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const send = () => {
    const headers: Record<string, string> = {};
    const token = read(ACCESS);
    if (token) headers.Authorization = `Bearer ${token}`;
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    return fetch(`${BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  };

  let res = await send();
  if (res.status === 401 && !path.startsWith("/auth/")) {
    refreshing ??= refreshTokens().finally(() => (refreshing = null));
    if (await refreshing) res = await send();
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Descarcă un fișier generat de API (ex. XML-ul IPC21), cu jetonul de acces. */
export async function apiDownload(path: string, fileName: string): Promise<void> {
  const send = () => {
    const token = read(ACCESS);
    return fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  };
  let res = await send();
  if (res.status === 401) {
    refreshing ??= refreshTokens().finally(() => (refreshing = null));
    if (await refreshing) res = await send();
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a); // Firefox descarcă doar din linkuri aflate în pagină
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const download = apiDownload;

/** Descarcă un fișier (cu jetonul de acces); numele vine din Content-Disposition. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const send = () => {
    const token = read(ACCESS);
    return fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  };
  let res = await send();
  if (res.status === 401) {
    refreshing ??= refreshTokens().finally(() => (refreshing = null));
    if (await refreshing) res = await send();
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  const match = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Deschide un fișier protejat (ex. un scan) într-o filă nouă a browserului, cu jetonul de acces. */
export async function openFile(path: string): Promise<void> {
  const send = () => {
    const token = read(ACCESS);
    return fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  };
  let res = await send();
  if (res.status === 401) {
    refreshing ??= refreshTokens().finally(() => (refreshing = null));
    if (await refreshing) res = await send();
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
