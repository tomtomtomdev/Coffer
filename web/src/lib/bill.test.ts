import { describe, expect, it } from "vitest";

import { billLabel, billTone, daysLabel } from "./bill";

describe("billLabel", () => {
  it("maps known card types and falls back to the raw type", () => {
    expect(billLabel("cimb_credit_card")).toBe("Kartu CIMB Niaga");
    expect(billLabel("bca_credit_card")).toBe("Kartu BCA");
    expect(billLabel("mystery_card")).toBe("mystery_card");
  });
});

describe("daysLabel", () => {
  it("renders the countdown in Bahasa, including overdue and today/tomorrow", () => {
    expect(daysLabel(6)).toBe("6 hari lagi");
    expect(daysLabel(1)).toBe("Jatuh tempo besok");
    expect(daysLabel(0)).toBe("Jatuh tempo hari ini");
    expect(daysLabel(-4)).toBe("Terlambat 4 hari");
  });
});

describe("billTone", () => {
  it("red-flags under 3 days (and overdue), amber within a week, else ok", () => {
    expect(billTone(-1)).toBe("urgent");
    expect(billTone(0)).toBe("urgent");
    expect(billTone(2)).toBe("urgent");
    expect(billTone(3)).toBe("soon");
    expect(billTone(6)).toBe("soon");
    expect(billTone(7)).toBe("ok");
    expect(billTone(30)).toBe("ok");
  });
});
