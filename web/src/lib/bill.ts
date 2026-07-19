/*
 * §3.4 bill-card presentation logic — pure, so it is unit-tested without the DOM.
 * (Formatting money still goes through lib/format's id-ID helpers at render time.)
 */

/** Urgency tone from days remaining: SPEC §3.4 red-flags "under 3 days" (and overdue). */
export type BillTone = "urgent" | "soon" | "ok";

const CARD_LABELS: Record<string, string> = {
  bca_credit_card: "Kartu BCA",
  cimb_credit_card: "Kartu CIMB Niaga",
};

/** Card name for the bill row (falls back to the raw account_type if unmapped). */
export function billLabel(accountType: string): string {
  return CARD_LABELS[accountType] ?? accountType;
}

/** Bahasa countdown copy for the due date (days_remaining is signed). */
export function daysLabel(days: number): string {
  if (days < 0) return `Terlambat ${Math.abs(days)} hari`;
  if (days === 0) return "Jatuh tempo hari ini";
  if (days === 1) return "Jatuh tempo besok";
  return `${days} hari lagi`;
}

/** SPEC §3.4: red-flag under 3 days (and once overdue); amber within a week. */
export function billTone(days: number): BillTone {
  if (days < 3) return "urgent";
  if (days < 7) return "soon";
  return "ok";
}
