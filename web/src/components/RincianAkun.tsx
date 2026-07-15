import type { AccountBalance, MemberSeries } from "../api/types";
import { fmtDate, fmtIDR, fmtNegIDR } from "../lib/format";

const ACCOUNT_LABELS: Record<string, string> = {
  bca_savings: "BCA Tabungan",
  bca_credit_card: "BCA Kartu Kredit",
  cimb_credit_card: "CIMB Niaga Kartu Kredit",
  ajaib_portfolio: "Ajaib",
  stockbit_portfolio: "Stockbit",
};

function accountLabel(accountType: string): string {
  return ACCOUNT_LABELS[accountType] ?? accountType;
}

interface Props {
  accounts: AccountBalance[];
  members: MemberSeries[];
}

/** Per-account balances (Rincian Akun): colour dot by bucket, owner + masked id, and the
 * account's own as-of date (liabilities shown negative / rose). */
export function RincianAkun({ accounts, members }: Props) {
  const ownerOf = new Map(members.map((m) => [m.member_id, m.member_name]));

  return (
    <section className="card rincian">
      <div className="section-title">Rincian Akun</div>
      {accounts.length === 0 ? (
        <div className="acctrow" style={{ color: "var(--muted)" }}>
          Belum ada akun.
        </div>
      ) : (
        accounts.map((a) => {
          const owner = ownerOf.get(a.member_id);
          const isLiability = a.bucket === "liability";
          return (
            <div className="acctrow" key={a.account_id}>
              <span className={`acctrow__dot dot--${a.bucket}`} />
              <div>
                <div className="acctrow__name">{accountLabel(a.account_type)}</div>
                <div className="acctrow__sub">
                  {owner ? `${owner} · ` : ""}
                  {a.account_number_masked}
                </div>
              </div>
              <div className="acctrow__right">
                <div className={`acctrow__bal${isLiability ? " acctrow__bal--neg" : ""}`}>
                  {isLiability ? fmtNegIDR(a.balance) : fmtIDR(a.balance)}
                </div>
                {a.as_of && <div className="acctrow__asof">per {fmtDate(a.as_of)}</div>}
              </div>
            </div>
          );
        })
      )}
    </section>
  );
}
