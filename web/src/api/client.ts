import type { PortofolioResponse, RingkasanResponse } from "./types";

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`Gagal memuat (${res.status})`);
  }
  return (await res.json()) as T;
}

/** §3.1 Ringkasan payload. LAN/VPN-only API (SPEC §5); dev proxies /api. */
export function fetchRingkasan(
  householdId: number,
  signal?: AbortSignal,
): Promise<RingkasanResponse> {
  return getJson(`/api/dashboard/ringkasan/${householdId}`, signal);
}

/** §3.2 Portofolio payload. */
export function fetchPortofolio(
  householdId: number,
  signal?: AbortSignal,
): Promise<PortofolioResponse> {
  return getJson(`/api/dashboard/portofolio/${householdId}`, signal);
}
