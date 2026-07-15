import type { RingkasanResponse } from "./types";

/** Fetch the §3.1 Ringkasan payload. LAN/VPN-only API (SPEC §5); dev proxies /api. */
export async function fetchRingkasan(
  householdId: number,
  signal?: AbortSignal,
): Promise<RingkasanResponse> {
  const res = await fetch(`/api/dashboard/ringkasan/${householdId}`, { signal });
  if (!res.ok) {
    throw new Error(`Ringkasan gagal dimuat (${res.status})`);
  }
  return (await res.json()) as RingkasanResponse;
}
