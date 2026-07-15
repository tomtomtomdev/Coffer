/** The four frozen dashboard tabs (SPEC §5). Bill due-dates (§3.4) will live as a card
 * on Ringkasan rather than a fifth tab (pending Tommy's confirmation). */
export const TABS = [
  { id: "overview", label: "Ringkasan" },
  { id: "portfolio", label: "Portofolio" },
  { id: "spend", label: "Belanja" },
  { id: "cashflow", label: "Arus Kas" },
] as const;

export type ViewId = (typeof TABS)[number]["id"];
