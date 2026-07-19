import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { recategorizeTransaction } from "./api/client";
import type {
  ArusKasResponse,
  BelanjaResponse,
  PortofolioResponse,
  RingkasanResponse,
  TagihanResponse,
} from "./api/types";

const { SAMPLE, PORTFOLIO, BELANJA, ARUSKAS, TAGIHAN } = vi.hoisted(() => {
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
  const portfolio: PortofolioResponse = {
    total_market_value: "4750000",
    total_unrealized_pl: "190000",
    total_cost_basis: "4560000",
    holdings: [
      {
        ticker: "BBCA",
        name: "BBCA Tbk",
        lots: "5",
        avg_price: "9120",
        market_value: "4750000",
        unrealized_pl: "190000",
        cost_basis: "4560000",
        brokers: [
          {
            institution: "ajaib",
            account_id: 10,
            lots: "2",
            avg_price: "9000",
            market_price: "9500",
            market_value: "1900000",
            unrealized_pl: "100000",
            as_of: "2026-06-30",
          },
          {
            institution: "stockbit",
            account_id: 11,
            lots: "3",
            avg_price: "9200",
            market_price: "9500",
            market_value: "2850000",
            unrealized_pl: "90000",
            as_of: "2026-06-30",
          },
        ],
      },
    ],
    as_of_dates: ["2026-06-30"],
    mixed_as_of: false,
  };
  const belanja: BelanjaResponse = {
    estimate: "25670000",
    insufficient_data: false,
    months_observed: 6,
    window_months: 6,
    base_median_monthly: "23800000",
    annual_amortized_monthly: "1870000",
    monthly_series: [
      { month: "2026-01-01", total: "22000000" },
      { month: "2026-05-01", total: "30000000" },
      { month: "2026-06-01", total: "24000000" },
    ],
    category_breakdown: [
      {
        category_id: 1,
        label: "Cicilan KPR",
        median_monthly: "8500000",
        observation_count: 6,
        cadence: "monthly",
      },
    ],
    anomalies: [],
    review_queue: [
      {
        transaction_id: 77,
        date: "2026-06-09",
        description: "TOKO XYZ",
        debit: "250000",
        credit: "0",
        counterparty_name: null,
        counterparty_acct: "123456",
        account_id: 2,
        institution: "bca",
        account_number_masked: "****5678",
        category_id: null,
        category_label: null,
        category_source: null,
        is_anomaly: false,
      },
    ],
    categories: [{ id: 1, label: "Cicilan KPR", type: "routine", cadence: "monthly" }],
  };
  const arusKas: ArusKasResponse = {
    months: [
      { month: "2026-05-01", income: "60000000", spend: "34000000", cash_flow: "26000000", savings_rate: "0.4333333" },
      { month: "2026-06-01", income: "66000000", spend: "34000000", cash_flow: "32000000", savings_rate: "0.4848484" },
    ],
    headline_savings_rate: "0.46",
    window_months: 6,
    latest_month: "2026-06-01",
    latest_cash_flow: "32000000",
    income_sources: [
      { category_id: 1, label: "Gaji · Tommy", amount: "38000000" },
      { category_id: 2, label: "Gaji · Priskila", amount: "22000000" },
    ],
    spend_by_type: [
      { type: "routine", amount: "23800000" },
      { type: "one_off", amount: "2300000" },
    ],
  };
  const tagihan: TagihanResponse = {
    as_of: "2026-07-19",
    bills: [
      {
        account_id: 3,
        member_id: 2,
        member_name: "Priskila",
        institution: "cimb",
        account_type: "cimb_credit_card",
        account_number_masked: "****0003",
        due_date: "2026-07-22",
        days_remaining: 3,
        minimum_payment: "50000",
        statement_balance: "838303",
      },
      {
        account_id: 2,
        member_id: 1,
        member_name: "Tommy",
        institution: "bca",
        account_type: "bca_credit_card",
        account_number_masked: "****0002",
        due_date: "2026-07-28",
        days_remaining: 9,
        minimum_payment: null,
        statement_balance: "2177067",
      },
    ],
  };
  return {
    SAMPLE: sample,
    PORTFOLIO: portfolio,
    BELANJA: belanja,
    ARUSKAS: arusKas,
    TAGIHAN: tagihan,
  };
});

vi.mock("./api/client", () => ({
  fetchRingkasan: vi.fn(async () => SAMPLE),
  fetchPortofolio: vi.fn(async () => PORTFOLIO),
  fetchBelanja: vi.fn(async () => BELANJA),
  fetchArusKas: vi.fn(async () => ARUSKAS),
  fetchTagihan: vi.fn(async () => TAGIHAN),
  recategorizeTransaction: vi.fn(async () => ({
    transaction_id: 77,
    category_id: 1,
    category_source: "manual",
    deactivated_rule_id: null,
    created_rule_id: null,
  })),
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

  it("shows the §3.4 bill due-date card below the hero", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    // The card title + soonest bill (holder, countdown, minimum) all render.
    expect(await screen.findByText("Tagihan Jatuh Tempo")).toBeInTheDocument();
    expect(screen.getByText("Kartu CIMB Niaga")).toBeInTheDocument();
    expect(screen.getByText(/Priskila · Jatuh tempo 22 Jul 2026/)).toBeInTheDocument();
    expect(screen.getByText("3 hari lagi")).toBeInTheDocument();
    expect(screen.getByText("Min. Rp 50.000")).toBeInTheDocument();
    // The second card (no minimum reported) still renders its balance.
    expect(screen.getByText("Kartu BCA")).toBeInTheDocument();
    expect(screen.getByText("9 hari lagi")).toBeInTheDocument();
  });

  it("switches to the Arus Kas tab and back", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(screen.getAllByRole("button", { name: "Arus Kas" })[0]!);
    expect(await screen.findByText("Tingkat Menabung")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Ringkasan" })[0]!);
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Rp 943.000.000"),
    );
  });

  it("shows the savings rate, cash flow, and breakdown lists on Arus Kas", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(screen.getAllByRole("button", { name: "Arus Kas" })[0]!);

    // Summary cards: savings rate (window average) + latest-month cash flow.
    expect(await screen.findByText("46%")).toBeInTheDocument();
    expect(screen.getByText("Rp 32.000.000")).toBeInTheDocument();
    expect(screen.getByText("Arus Kas · Juni")).toBeInTheDocument();

    // Breakdown lists: an income source and a spend type (frozen-design copy).
    expect(screen.getByText("Gaji · Tommy")).toBeInTheDocument();
    expect(screen.getByText("Rp 38.000.000")).toBeInTheDocument();
    expect(screen.getByText("Rutin")).toBeInTheDocument();
  });

  it("toggles the net-worth mode to Per Anggota", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    const perMember = screen.getByRole("button", { name: "Per Anggota" });
    fireEvent.click(perMember);
    expect(perMember).toHaveAttribute("aria-pressed", "true");
  });

  it("shows consolidated holdings on the Portofolio tab", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(screen.getAllByRole("button", { name: "Portofolio" })[0]!);

    expect(await screen.findByText("BBCA")).toBeInTheDocument();
    expect(screen.getByText("Nilai Pasar Gabungan")).toBeInTheDocument();
    expect(screen.getByText("Total Rumah Tangga")).toBeInTheDocument();
  });

  it("shows the routine-spend hero, category medians, and review queue on Belanja", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(screen.getAllByRole("button", { name: "Belanja" })[0]!);

    // Hero big figure = base median; explainer shows the amortized total.
    expect(await screen.findByText("Rp 23,8 jt")).toBeInTheDocument();
    expect(screen.getByText("Estimasi Belanja Rutin")).toBeInTheDocument();
    expect(screen.getByText("Cicilan KPR")).toBeInTheDocument();
    expect(screen.getByText("TOKO XYZ")).toBeInTheDocument();
    expect(screen.getByText("Perlu tag")).toBeInTheDocument();
  });

  it("tags a review-queue transaction via the categorize endpoint", async () => {
    render(<App />);
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(screen.getAllByRole("button", { name: "Belanja" })[0]!);
    await screen.findByText("TOKO XYZ");

    fireEvent.click(screen.getByRole("button", { name: "Tag →" }));
    expect(screen.getByLabelText("Pilih kategori")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Simpan" }));
    await waitFor(() =>
      expect(vi.mocked(recategorizeTransaction)).toHaveBeenCalledWith(77, {
        category_id: 1,
        generalize: null,
      }),
    );
  });
});
