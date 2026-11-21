export type UserRole = "admin" | "chief_accountant" | "accountant" | "project_manager" | "auditor";

export type EntityType = "srl" | "sa" | "ii" | "gt" | "ngo_association" | "ngo_foundation" | "ngo_other" | "other";

export interface User {
  id: string;
  email: string;
  full_name: string;
}

export interface OrganizationBrief {
  id: string;
  name: string;
  idno: string;
  entity_type: EntityType;
  accounting_method: "double_entry" | "single_entry";
  role: UserRole;
}

export interface Workspace {
  id: string;
  name: string;
  source: string | null;
  created_at: string | null;
  organizations: OrganizationBrief[];
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Administrator",
  chief_accountant: "Contabil-șef",
  accountant: "Contabil",
  project_manager: "Manager de proiect",
  auditor: "Auditor",
};

export const ENTITY_LABELS: Record<EntityType, string> = {
  srl: "SRL",
  sa: "SA",
  ii: "Întreprindere individuală",
  gt: "Gospodărie țărănească",
  ngo_association: "Asociație obștească",
  ngo_foundation: "Fundație",
  ngo_other: "ONG (altă formă)",
  other: "Altă formă",
};
