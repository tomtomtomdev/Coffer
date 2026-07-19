import { billLabel, billTone, daysLabel } from "../lib/bill";
import { fmtDate, fmtIDR } from "../lib/format";
import { useTagihan } from "../lib/useRingkasan";

interface Props {
  householdId: number;
}

/** §3.4 Bill due-date aggregator card — sits on Ringkasan below the hero (placement locked
 * 2026-07-18). Each credit card's latest bill: holder, due date, days remaining, minimum
 * payment, full balance; soonest-first with a red flag under 3 days (SPEC §3.4). Self-fetches
 * and renders nothing while loading, on error, or when there are no bills — so it never
 * disturbs the overview when there is nothing due. */
export function Tagihan({ householdId }: Props) {
  const state = useTagihan(householdId);
  if (state.status !== "ready" || state.data.bills.length === 0) return null;

  return (
    <section className="card tagihan">
      <div className="section-title">Tagihan Jatuh Tempo</div>
      {state.data.bills.map((b) => {
        const tone = billTone(b.days_remaining);
        return (
          <div className="billrow" key={b.account_id}>
            <span className={`billrow__flag flag--${tone}`} />
            <div>
              <div className="billrow__name">{billLabel(b.account_type)}</div>
              <div className="billrow__sub">
                {b.member_name} · Jatuh tempo {fmtDate(b.due_date)}
              </div>
            </div>
            <div className="billrow__right">
              <div className="billrow__bal">{fmtIDR(b.statement_balance)}</div>
              <div className={`billrow__days days--${tone}`}>{daysLabel(b.days_remaining)}</div>
              {b.minimum_payment !== null && (
                <div className="billrow__min">Min. {fmtIDR(b.minimum_payment)}</div>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
