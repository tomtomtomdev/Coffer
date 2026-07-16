import { fetchArusKas, fetchBelanja, fetchPortofolio, fetchRingkasan } from "../api/client";
import type {
  ArusKasResponse,
  BelanjaResponse,
  PortofolioResponse,
  RingkasanResponse,
} from "../api/types";
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

/** Fetch the §3.5 Arus Kas payload for a household. */
export function useArusKas(householdId: number): AsyncState<ArusKasResponse> {
  return useApi((signal) => fetchArusKas(householdId, signal), householdId);
}
