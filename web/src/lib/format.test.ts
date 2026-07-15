import { describe, expect, it } from "vitest";

import {
  fmtDate,
  fmtIDR,
  fmtJuta,
  fmtNegIDR,
  fmtPct,
  fmtShort,
  fmtShortSigned,
  monthLong,
  monthShort,
  num,
} from "./format";

const MINUS = "−"; // U+2212, the typographic minus used for negatives

describe("money", () => {
  it("formats full IDR with id-ID dot-thousands and a plain space", () => {
    expect(fmtIDR("943000000")).toBe("Rp 943.000.000");
  });

  it("parses exact decimal strings without float drift in display", () => {
    // 838303.83 rounds to whole rupiah for display (maximumFractionDigits: 0).
    expect(fmtIDR("838303.83")).toBe("Rp 838.304");
  });

  it("shows liabilities as a negative with the U+2212 minus", () => {
    expect(fmtNegIDR("2177067")).toBe(`${MINUS}Rp 2.177.067`);
  });

  it("num() parses strings and treats null/blank as 0", () => {
    expect(num("175")).toBe(175);
    expect(num(null)).toBe(0);
    expect(num("")).toBe(0);
  });
});

describe("short axis form", () => {
  it("uses jt below 1000 juta", () => {
    expect(fmtShort(611_000_000)).toBe("611 jt");
  });

  it("uses M (miliar) with a comma decimal at/above 1000 juta", () => {
    expect(fmtShort(1_100_000_000)).toBe("1,1 M");
  });

  it("signs a jt amount for KPI subs", () => {
    expect(fmtShortSigned(32_000_000)).toBe("+Rp 32 jt");
    expect(fmtShortSigned(-5_000_000)).toBe(`${MINUS}Rp 5 jt`);
  });

  it("juta figure keeps one decimal", () => {
    expect(fmtJuta(23_800_000)).toBe("23,8 jt");
    expect(fmtJuta(32_000_000)).toBe("32 jt");
  });
});

describe("percent", () => {
  it("formats a fraction as an id-ID percent", () => {
    expect(fmtPct("0.47")).toBe("47%");
    expect(fmtPct("0.039", 1)).toBe("3,9%");
  });
});

describe("dates", () => {
  it("short month uses Mei/Jun", () => {
    expect(monthShort("2026-05-31")).toBe("Mei");
    expect(monthShort("2026-06-30")).toBe("Jun");
  });

  it("long month + year for the header chip", () => {
    expect(monthLong("2026-06-30")).toBe("Juni 2026");
  });

  it("day + short month + year", () => {
    expect(fmtDate("2026-06-30")).toBe("30 Jun 2026");
  });
});
