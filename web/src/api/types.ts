/*
 * Wire types for the dashboard read API. Money arrives as **strings** (exact Decimal
 * from the backend — never floats). Parse to a number only at the render/chart edge.
 * Mirrors coffer/api/dashboard_schemas.py.
 */

export type Bucket = "cash" | "liability" | "portfolio";

export interface GridPoint {
  grid_date: string; // ISO date
  cash: string;
  portfolio: string;
  liability: string;
  net_worth: string;
}

export interface MemberPoint {
  grid_date: string;
  net_worth: string;
}

export interface MemberSeries {
  member_id: number;
  member_name: string;
  points: MemberPoint[];
}

export interface AccountBalance {
  account_id: number;
  member_id: number;
  institution: string;
  account_type: string;
  account_number_masked: string;
  bucket: Bucket;
  balance: string;
  as_of: string | null;
}

export interface Delta {
  amount: string;
  pct: string | null;
}

export interface Kpis {
  routine_spend_monthly: string | null;
  routine_annual_amortized: string;
  savings_rate: string | null;
  monthly_cash_flow: string | null;
}

export interface RingkasanResponse {
  as_of: string | null;
  net_worth: string;
  delta: Delta | null;
  household_series: GridPoint[];
  member_series: MemberSeries[];
  accounts: AccountBalance[];
  kpis: Kpis;
}
