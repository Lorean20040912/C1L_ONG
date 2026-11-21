import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Account, BankAccount, Counterparty, Grant } from "../api/types";

export interface Catalogs {
  accounts: Account[];
  counterparties: Counterparty[];
  grants: Grant[];
  bankAccounts: BankAccount[];
}

const EMPTY: Catalogs = { accounts: [], counterparties: [], grants: [], bankAccounts: [] };

// cataloagele organizației, încărcate o dată pe organizație și partajate între file
const cache = new Map<string, Promise<Catalogs>>();

function load(orgId: string): Promise<Catalogs> {
  const base = `/organizations/${orgId}`;
  return Promise.all([
    api<Account[]>(`${base}/accounts`),
    api<Counterparty[]>(`${base}/counterparties`),
    api<Grant[]>(`${base}/grants`),
    api<BankAccount[]>(`${base}/bank-accounts`),
  ]).then(([accounts, counterparties, grants, bankAccounts]) => ({ accounts, counterparties, grants, bankAccounts }));
}

const CHANGED = "contahub:catalogs-changed";

/** După o modificare în Administrare (grant, cont bancar, cont nou...): toate ecranele reîncarcă cataloagele. */
export function refreshCatalogs(orgId: string): void {
  cache.delete(orgId);
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: orgId }));
}

export function useCatalogs(orgId: string): { catalogs: Catalogs; error: string | null } {
  const [catalogs, setCatalogs] = useState<Catalogs>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const listener = (e: Event) => (e as CustomEvent<string>).detail === orgId && setVersion((v) => v + 1);
    window.addEventListener(CHANGED, listener);
    return () => window.removeEventListener(CHANGED, listener);
  }, [orgId]);
  useEffect(() => {
    let alive = true;
    if (!cache.has(orgId)) cache.set(orgId, load(orgId));
    cache
      .get(orgId)!
      .then((c) => alive && setCatalogs(c))
      .catch((e: Error) => {
        cache.delete(orgId);
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [orgId, version]);
  return { catalogs, error };
}

export function budgetLineLabel(grants: Grant[], id: string | null): string {
  if (!id) return "";
  for (const g of grants) {
    const line = g.budget_lines.find((l) => l.id === id);
    if (line) return `${g.code} / ${line.code} ${line.name}`;
  }
  return "";
}

export function grantLabel(grants: Grant[], id: string | null): string {
  const g = grants.find((x) => x.id === id);
  return g ? `${g.code} ${g.title}` : "";
}
