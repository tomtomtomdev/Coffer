import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RingkasanResponse } from "./api/types";

const { SAMPLE } = vi.hoisted(() => {
  const sample: RingkasanResponse = {
    as_of: "2026-06-30",
    net_worth: "943000000",
    delta: { amount: "35000000", pct: "0.039" },
    household_series: [
      { grid_date: "2026-05-31", cash: "600000000", portfolio: "300000000", liability: "8000000", net_worth: "892000000" },
      { grid_date: "2026-06-30", cash: "611000000", portfolio: "340000000", liability: "8000000", net_worth: "943000000" },
    ],
    member_series: [
      {
        member_id: 1,
        member_name: "Tommy",
        points: [
          { grid_date: "2026-05-31", net_worth: "500000000" },
          { grid_date: "2026-06-30", net_worth: "520000000" },
        ],
      },
      {
        member_id: 2,
        member_name: "Priskila",
        points: [
          { grid_date: "2026-05-31", net_worth: "392000000" },
          { grid_date: "2026-06-30", net_worth: "423000000" },
        ],
      },
    ],
    accounts: [
      {
        account_id: 1,
        member_id: 1,
        institution: "bca",
        account_type: "bca_savings",
        account_number_masked: "****1234",
        bucket: "cash",
        balance: "611000000",
        as_of: "2026-06-30",
      },
      {
        account_id: 2,
        member_id: 1,
        institution: "bca",
        account_type: "bca_credit_card",
        account_number_masked: "****5678",
        bucket: "liability",
        balance: "8000000",
        as_of: "2026-06-30",
      },
    ],
    kpis: {
      routine_spend_monthly: "23800000",
      routine_annual_amortized: "1870000",
      savings_rate: "0.47",
      monthly_cash_flow: "32000000",
    },
  };
  return { SAMPLE: sample };
});

vi.mock("./api/client", () => ({
  fetchRingkasan: vi.fn(async () => SAMPLE),
}));

import { App } from "./App";

describe("App / Ringkasan", () => {
  it("renders the net-worth headline, KPIs, and account rows", async () => {
    render(<App />);

    // Hero figure (net worth) once the fetch resolves.
    const hero = await screen.findByRole("heading", { level: 1 });
    expect(hero).toHaveTextContent("Rp 943.000.000");

    // Delta pill + KPI figures.
    expect(screen.getByText(/3,9%/)).toBeInTheDocument();
    expect(screen.getByText("Rp 23,8 jt")).toBeInTheDocument();
    expect(screen.getByText("47%")).toBeInTheDocument();
    expect(screen.getByText("+Rp 32 jt")).toBeInTheDocument();

    // Rincian Akun: a cash account and a liability shown negative.
    expect(screen.getByText("BCA Tabungan")).toBeInTheDocument();
    expect(screen.getByText("BCA Kartu Kredit")).toBeInTheDocument();
    expect(screen.getByText("−Rp 8.000.000")).toBeInTheDocument();

    // Month chip reflects the latest data month.
    expect(screen.getByText("Juni 2026")).toBeInTheDocument();
  });

  it("switches to a placeholder tab and back", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(screen.getAllByRole("button", { name: "Belanja" })[0]!);
    expect(screen.getByText(/slice berikutnya/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Ringkasan" })[0]!);
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Rp 943.000.000"),
    );
  });

  it("toggles the net-worth mode to Per Anggota", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    const perMember = screen.getByRole("button", { name: "Per Anggota" });
    fireEvent.click(perMember);
    expect(perMember).toHaveAttribute("aria-pressed", "true");
  });
});
