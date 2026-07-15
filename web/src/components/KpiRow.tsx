import type { Kpis } from "../api/types";
import { fmtJuta, fmtPct, fmtShortSigned, num } from "../lib/format";
import type { ViewId } from "../nav";

interface Props {
  kpis: Kpis;
  onNavigate: (view: ViewId) => void;
}

/** Three clickable KPI cards deep-linking to Belanja / Arus Kas (SPEC §3.1). */
export function KpiRow({ kpis, onNavigate }: Props) {
  const routine = kpis.routine_spend_monthly;
  const annual = num(kpis.routine_annual_amortized);
  const savings = kpis.savings_rate;
  const flow = kpis.monthly_cash_flow;
  const flowPositive = flow != null && num(flow) >= 0;

  return (
    <div className="kpis">
      <button type="button" className="kpi" onClick={() => onNavigate("spend")}>
        <div className="kpi__eyebrow">Belanja Rutin / bln</div>
        <div className="kpi__figure">{routine != null ? `Rp ${fmtJuta(num(routine))}` : "—"}</div>
        <div className="kpi__sub">
          {routine == null
            ? "Belum cukup data (< 3 bln)"
            : annual > 0
              ? `+ Rp ${fmtJuta(annual)} amortisasi tahunan`
              : "median 6 bulan"}
        </div>
      </button>

      <button type="button" className="kpi" onClick={() => onNavigate("cashflow")}>
        <div className="kpi__eyebrow">Tingkat Menabung</div>
        <div className="kpi__figure kpi__figure--green">
          {savings != null ? fmtPct(savings) : "—"}
        </div>
        <div className="kpi__sub">rata-rata 6 bulan</div>
      </button>

      <button type="button" className="kpi" onClick={() => onNavigate("cashflow")}>
        <div className="kpi__eyebrow">Arus Kas Bulanan</div>
        <div className={`kpi__figure${flowPositive ? " kpi__figure--green" : ""}`}>
          {flow != null ? fmtShortSigned(num(flow)) : "—"}
        </div>
        <div className="kpi__sub">bulan terakhir</div>
      </button>
    </div>
  );
}
