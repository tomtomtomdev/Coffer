import { useState } from "react";

import type { RingkasanResponse } from "../api/types";
import { HeroCard } from "../components/HeroCard";
import { KpiRow } from "../components/KpiRow";
import { RincianAkun } from "../components/RincianAkun";
import { Tagihan } from "../components/Tagihan";
import type { ViewId } from "../nav";

interface Props {
  data: RingkasanResponse;
  householdId: number;
  onNavigate: (view: ViewId) => void;
}

/** §3.1 overview: net-worth hero + tide chart, §3.4 bill card, KPI row, Rincian Akun.
 * The Tagihan card sits below the hero and above the KPI row (placement locked 2026-07-18);
 * it self-fetches and renders nothing when there is nothing due. */
export function Ringkasan({ data, householdId, onNavigate }: Props) {
  const [mode, setMode] = useState<"household" | "member">("household");

  return (
    <div className="view">
      <HeroCard data={data} mode={mode} onMode={setMode} />
      <Tagihan householdId={householdId} />
      <KpiRow kpis={data.kpis} onNavigate={onNavigate} />
      <RincianAkun accounts={data.accounts} members={data.member_series} />
    </div>
  );
}
