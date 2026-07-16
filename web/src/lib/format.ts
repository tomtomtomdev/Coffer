/*
 * Formatting — the ONLY place money becomes locale text (CLAUDE.md: id-ID formatting
 * lives at the UI edge). Money crosses the wire as an exact Decimal string; we parse to
 * a JS number here purely to render/plot. IDR values stay well under 2^53, so the
 * float is exact for the 0-fraction-digit display and for pixel geometry.
 */

const IDR = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

const NUM0 = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });
const NUM1 = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 });

const MONTHS_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "Mei",
  "Jun",
  "Jul",
  "Agu",
  "Sep",
  "Okt",
  "Nov",
  "Des",
];

const MONTHS_LONG = [
  "Januari",
  "Februari",
  "Maret",
  "April",
  "Mei",
  "Juni",
  "Juli",
  "Agustus",
  "September",
  "Oktober",
  "November",
  "Desember",
];

/**
 * Intl inserts a non-breaking space (U+00A0) after "Rp" (and, in some locales, before
 * "%"); normalise it to a plain space so the UI renders and tests assert consistently.
 */
function sp(s: string): string {
  return s.replace(/\s/g, " ");
}

/** Parse an exact Decimal string to a number for rendering (0 if null/blank). */
export function num(value: string | null | undefined): number {
  if (value == null || value === "") return 0;
  return Number(value);
}

/** Full IDR currency, e.g. "Rp 943.000.000". Accepts a Decimal string or number. */
export function fmtIDR(value: string | number): string {
  const n = typeof value === "string" ? num(value) : value;
  return sp(IDR.format(n));
}

/** A liability (magnitude) shown as a negative amount with the U+2212 minus. */
export function fmtNegIDR(value: string | number): string {
  const n = typeof value === "string" ? num(value) : value;
  return `−${sp(IDR.format(Math.abs(n)))}`;
}

/** Short chart-axis form: ≥1000 jt → "1,1 M"; else "611 jt" (comma decimal, id-ID). */
export function fmtShort(rupiah: number): string {
  const juta = rupiah / 1_000_000;
  if (Math.abs(juta) >= 1000) {
    return `${NUM1.format(juta / 1000)} M`;
  }
  return `${NUM0.format(Math.round(juta))} jt`;
}

/** A "juta" figure for hero/KPI numbers, e.g. "23,8 jt" (default 1 decimal, id-ID). */
export function fmtJuta(rupiah: number, digits = 1): string {
  const nf = new Intl.NumberFormat("id-ID", { maximumFractionDigits: digits });
  return `${nf.format(rupiah / 1_000_000)} jt`;
}

/** A signed juta amount for KPI figures/subs, e.g. "+Rp 32 jt" / "−Rp 5 jt". */
export function fmtShortSigned(rupiah: number): string {
  const sign = rupiah < 0 ? "−" : "+";
  return `${sign}Rp ${fmtJuta(Math.abs(rupiah))}`;
}

/** A fraction (e.g. "0.47") as an id-ID percent, e.g. "47%". */
export function fmtPct(fraction: string | number, digits = 0): string {
  const n = typeof fraction === "string" ? num(fraction) : fraction;
  return sp(
    new Intl.NumberFormat("id-ID", {
      style: "percent",
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    }).format(n),
  );
}

/** ISO date → "Jun" (id-ID short month). */
export function monthShort(iso: string): string {
  return MONTHS_SHORT[monthIndex(iso)] ?? "";
}

/** ISO date → "Juni 2026" (id-ID long month + year) for the header month chip. */
export function monthLong(iso: string): string {
  const [y] = iso.split("-");
  return `${MONTHS_LONG[monthIndex(iso)] ?? ""} ${y}`;
}

/** ISO date → "Juni" (id-ID long month, no year) for the "· <bulan>" card labels. */
export function monthName(iso: string): string {
  return MONTHS_LONG[monthIndex(iso)] ?? "";
}

/** ISO date → "30 Jun 2026" (day + short month + year). */
export function fmtDate(iso: string): string {
  const parts = iso.split("-");
  const day = Number(parts[2]);
  return `${day} ${monthShort(iso)} ${parts[0]}`;
}

function monthIndex(iso: string): number {
  const m = Number(iso.split("-")[1]);
  return m - 1;
}
