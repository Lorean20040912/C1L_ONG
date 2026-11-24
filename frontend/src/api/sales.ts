// Tipurile modulului de vânzări: facturi emise, stornări, încasări legate, sold clienți, jurnalul vânzărilor.

export interface SalesLine {
  description: string;
  unit: string | null;
  quantity: string | null;
  unit_price: string | null;
  amount: string;
  vat_rate: string;
  vat_amount?: string;
  total?: string;
  revenue_type: string;
  account_id: string | null;
  grant_id: string | null;
}

export interface SalesListItem {
  document_id: string;
  id: string;
  kind: "invoice" | "credit_note";
  kind_label: string;
  series: string;
  number: string;
  doc_date: string | null;
  due_date: string | null;
  counterparty_id: string | null;
  counterparty_name: string | null;
  currency: string | null;
  net: string;
  vat: string;
  gross: string;
  paid: string;
  balance: string;
  status: "active" | "cancelled";
  is_posted: boolean | null;
  storno_of_id: string | null;
}

export interface Party {
  name: string | null;
  idno: string | null;
  vat_code: string | null;
  address: string | null;
  director: string | null;
  accountant: string | null;
  banks: string[];
}

export interface SalesInvoice extends SalesListItem {
  exchange_rate: string | null;
  notes: string | null;
  cancel_reason: string | null;
  version: number | null;
  lines: SalesLine[];
  seller: Party;
  client: Party;
  credited: string;
  storno_number: string | null;
}

export interface SalesMeta {
  revenue_types: Record<string, string>;
  vat_rates: string[];
  vat_payer: boolean;
  next_number: string;
  base_currency: string;
}

export interface SettlementItem {
  invoice_id: string;
  amount: string;
}
export interface Settlements {
  receipt_document_id: string;
  receipt_amount: string;
  receipt_posted: boolean;
  counterparty_id: string | null;
  allocated: string;
  unallocated: string;
  items: (SettlementItem & { number: string; series: string; doc_date: string | null; open_balance: string })[];
}

export interface InvoiceReceipt {
  receipt_document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  amount: string;
  is_posted: boolean;
}

export interface OpenInvoice {
  document_id: string;
  number: string;
  doc_date: string;
  due_date: string;
  currency: string;
  gross_mdl: string;
  open_mdl: string;
  age_days: number;
  overdue_days: number;
}

export interface CustomerRow {
  counterparty_id: string;
  name: string;
  idno: string | null;
  invoiced: string;
  credited: string;
  received: string;
  balance: string;
  unallocated_receipts: string;
  not_due: string;
  age_0_30: string;
  age_31_60: string;
  age_61_90: string;
  age_over_90: string;
  overdue: string;
  invoices: OpenInvoice[];
}

export interface CustomerBalances {
  as_of: string;
  rows: CustomerRow[];
  total_balance: string;
  total_overdue: string;
  buckets: Record<string, string>;
  ledger_balance: string;
}
