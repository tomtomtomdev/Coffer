import { fetchBelanja, fetchPortofolio, fetchRingkasan } from "../api/client";
import type { BelanjaResponse, PortofolioResponse, RingkasanResponse } from "../api/types";
import { type AsyncState, useApi } from "./useApi";

/** Fetch the §3.1 Ringkasan payload for a household. */
export function useRingkasan(householdId: number): AsyncState<RingkasanResponse> {
  return useApi((signal) => fetchRingkasan(householdId, signal), householdId);
}

/** Fetch the §3.2 Portofolio payload for a household. */
export function usePortofolio(householdId: number): AsyncState<PortofolioResponse> {
  return useApi((signal) => fetchPortofolio(householdId, signal), householdId);
}

/** Fetch the §3.3 Belanja payload; bump `reloadKey` to re-fetch after a Tag/Ubah. */
export function useBelanja(householdId: number, reloadKey = 0): AsyncState<BelanjaResponse> {
  return useApi((signal) => fetchBelanja(householdId, signal), `${householdId}:${reloadKey}`);
}
