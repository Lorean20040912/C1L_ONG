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

export function refreshCatalogs(orgId: string): void {
  cache.delete(orgId);
}

export function useCatalogs(orgId: string): { catalogs: Catalogs; error: string | null } {
  const [catalogs, setCatalogs] = useState<Catalogs>(EMPTY);
  const [error, setError] = useState<string | null>(null);
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
  }, [orgId]);
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
