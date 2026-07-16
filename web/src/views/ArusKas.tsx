import { CashFlowChart } from "../components/CashFlowChart";
import { ErrorCard, LoadingCard } from "../components/Status";
import { spendTypeLabel } from "../lib/cashflow";
import { fmtIDR, fmtPct, monthName, num } from "../lib/format";
import { useArusKas } from "../lib/useRingkasan";

function signClass(value: number): string {
  return value >= 0 ? "pl--pos" : "pl--neg";
}

/** §3.5 cash-flow screen: savings-rate + monthly-cash-flow summary cards, the income-vs-
 *  spend bars with the savings-rate line, and the latest month's income-source + spend-type
 *  breakdown lists. All money math is the backend's; this is presentation only. */
export function ArusKas({ householdId }: { householdId: number }) {
  const state = useArusKas(householdId);
  if (state.status === "loading") return <LoadingCard />;
  if (state.status === "error") return <ErrorCard message={state.message} />;

  const data = state.data;
  const monthLabel = data.latest_month ? monthName(data.latest_month) : "";
  const cashFlow = num(data.latest_cash_flow);

  return (
    <div className="view">
      <div className="pcards">
        <div className="card pcard">
          <div className="kpi__eyebrow">Tingkat Menabung</div>
          <div
            className={`pcard__figure pcard__figure--flow ${
              data.headline_savings_rate === null ? "" : signClass(num(data.headline_savings_rate))
            }`}
          >
            {data.headline_savings_rate === null ? "—" : fmtPct(data.headline_savings_rate)}
          </div>
          <div className="pcard__sub">rata-rata {data.window_months} bulan</div>
        </div>
        <div className="card pcard">
          <div className="kpi__eyebrow">Arus Kas{monthLabel && ` · ${monthLabel}`}</div>
          <div
            className={`pcard__figure pcard__figure--flow ${
              data.latest_cash_flow === null ? "" : signClass(cashFlow)
            }`}
          >
            {data.latest_cash_flow === null ? "—" : fmtIDR(data.latest_cash_flow)}
          </div>
          <div className="pcard__sub">pendapatan − belanja</div>
        </div>
      </div>

      <div className="card flowcard">
        <div className="section-title">Pendapatan vs Belanja · tingkat menabung</div>
        <CashFlowChart data={data} />
        <div className="hero__footnote">
          Transfer &amp; pergerakan investasi dikecualikan. Pendapatan/belanja diatribusikan ke
          bulan <em>tanggal transaksi</em>, bukan tanggal unggah.
        </div>
      </div>

      <div className="pcards">
        <div className="card fllist">
          <div className="kpi__eyebrow">
            Sumber Pendapatan{monthLabel && ` · ${monthLabel}`}
          </div>
          {data.income_sources.length === 0 ? (
            <div className="fllist__empty">Belum ada pendapatan tercatat.</div>
          ) : (
            data.income_sources.map((s) => (
              <div className="fllist__row" key={s.category_id}>
                <span>{s.label}</span>
                <span className="fllist__amt fllist__amt--in">{fmtIDR(s.amount)}</span>
              </div>
            ))
          )}
        </div>
        <div className="card fllist">
          <div className="kpi__eyebrow">Belanja per Tipe{monthLabel && ` · ${monthLabel}`}</div>
          {data.spend_by_type.length === 0 ? (
            <div className="fllist__empty">Belum ada belanja tercatat.</div>
          ) : (
            data.spend_by_type.map((s) => (
              <div className="fllist__row" key={s.type}>
                <span>{spendTypeLabel(s.type)}</span>
                <span className="fllist__amt fllist__amt--out">{fmtIDR(s.amount)}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
