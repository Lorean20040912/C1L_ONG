// Tipurile modulului „Granturi avansat”.

export interface Donor {
  id: string;
  name: string;
  country: string | null;
  grants_count: number;
}

export interface GrantDonor {
  donor_id: string;
  donor_name: string;
  share_percent: string | null;
  amount: string | null;
}

export interface BudgetVersion {
  id: string;
  version: number;
  valid_from: string;
  is_current: boolean;
  lines_count: number;
  total_planned: string;
}

export interface BudgetLineRow {
  id: string;
  code: string;
  name: string;
  planned_amount: string;
}

export interface Tranche {
  id: string;
  number: number;
  donor_id: string | null;
  planned_date: string | null;
  amount: string;
  currency: string;
  condition: string | null;
  status: "planned" | "recognized" | "received" | "cancelled";
  recognition_document_id: string | null;
  received_document_id: string | null;
}

export const TRANCHE_STATUS: Record<Tranche["status"], string> = {
  planned: "planificată",
  recognized: "recunoscută",
  received: "încasată",
  cancelled: "anulată",
};

export interface Distribution {
  document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  grant_id: string | null;
  amount: string | null;
  description: string | null;
}

export interface PreviewRow {
  debit_account: string;
  credit_account: string;
  amount: string;
  source_ref: string;
}
