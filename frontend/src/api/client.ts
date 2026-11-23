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

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
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
