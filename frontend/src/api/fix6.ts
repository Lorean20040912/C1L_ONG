// Tipurile ecranelor din lotul „ecrane complete” (mijloace fixe, ajustări, cataloage, scanuri, pachet donator).

export interface AssetInvoiceLine {
  invoice_line_id: string;
  document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  counterparty: string | null;
  is_posted: boolean;
  description: string;
  amount: string;
  put_into_use: boolean | null;
  fixed_asset_id: string | null;
  inventory_no: string | null;
  asset_status: string | null;
}

export interface AssetEvent {
  id: string;
  fixed_asset_id: string;
  inventory_no: string;
  asset_name: string;
  kind: "commissioning" | "writeoff";
  event_date: string;
  status: "posted" | "cancelled";
  reason: string | null;
  amount: string | null;
  document_id: string | null;
}

export interface Adjustment {
  id: string;
  adjustment_date: string;
  description: string;
  debit_account: string;
  credit_account: string;
  amount: string;
  grant_id: string | null;
  status: "posted" | "cancelled";
  reversal_date: string | null;
  document_id: string | null;
}

export interface CalcType {
  id: string;
  code: string;
  name: string;
  kind: "accrual" | "deduction";
  taxable: boolean;
  social_base: boolean;
  is_active: boolean;
}

export interface DocSource {
  id: string;
  kind: "google_drive" | "local_agent" | "server_folder";
  name: string;
  location: string;
  note: string | null;
  is_active: boolean;
  documents: number;
}

export interface Department {
  id: string;
  name: string;
  parent_id: string | null;
  cuatm: string | null;
}

export interface CounterpartyFull {
  id: string;
  name: string;
  idno: string | null;
  vat_code: string | null;
  bank_code: string | null;
  address: string | null;
}

export interface TrancheRow {
  id: string;
  grant_id: string;
  grant_code: string;
  donor_id: string | null;
  donor_name: string | null;
  number: number;
  planned_date: string | null;
  amount: string;
  currency: string;
  status: "planned" | "recognized" | "received" | "cancelled";
  received_document_id: string | null;
  received_date: string | null;
}

export interface GrantPurchase {
  grant_id: string;
  grant_code: string;
  budget_line: string;
  document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  counterparty: string | null;
  description: string;
  line_kind: string;
  amount: string;
}

export interface Scan {
  id: string;
  file_name: string | null;
  mime_type: string | null;
  status: "new" | "ai_processed" | "to_review" | "validated" | "rejected";
  type: string | null;
  counterparty_id: string | null;
  counterparty: string | null;
  doc_number: string | null;
  doc_date: string | null;
  total_amount: string | null;
  currency: string | null;
  source_id: string | null;
  ai_fields: Record<string, unknown> | null;
  ai_at: string | null;
  is_posted: boolean;
}

export interface PackageDoc {
  document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  counterparty: string | null;
  amount: string;
  has_file: boolean;
}

export interface PackageLine {
  budget_line_id: string;
  code: string;
  name: string;
  planned: string;
  spent: string;
  remaining: string;
  documents: PackageDoc[];
  missing_files: number;
}

export interface DonorPackage {
  grant_id: string;
  grant_code: string;
  title: string;
  currency: string;
  total_planned: string;
  total_spent: string;
  missing_files: number;
  lines: PackageLine[];
}
