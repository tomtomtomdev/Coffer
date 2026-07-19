import type {
  ArusKasResponse,
  BelanjaResponse,
  PortofolioResponse,
  RecategorizeRequest,
  RecategorizeResponse,
  RingkasanResponse,
  TagihanResponse,
} from "./types";

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`Gagal memuat (${res.status})`);
  }
  return (await res.json()) as T;
}

async function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    throw new Error(`Gagal menyimpan (${res.status})`);
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

/** §3.3 Belanja payload. */
export function fetchBelanja(householdId: number, signal?: AbortSignal): Promise<BelanjaResponse> {
  return getJson(`/api/dashboard/belanja/${householdId}`, signal);
}

/** §3.5 Arus Kas payload. */
export function fetchArusKas(householdId: number, signal?: AbortSignal): Promise<ArusKasResponse> {
  return getJson(`/api/dashboard/arus-kas/${householdId}`, signal);
}

/** §3.4 Tagihan (bill due-date) payload for the Ringkasan card. */
export function fetchTagihan(householdId: number, signal?: AbortSignal): Promise<TagihanResponse> {
  return getJson(`/api/dashboard/tagihan/${householdId}`, signal);
}

/** Tag/Ubah — apply a manual category to a transaction (SPEC §3.3). */
export function recategorizeTransaction(
  transactionId: number,
  body: RecategorizeRequest,
): Promise<RecategorizeResponse> {
  return postJson(`/api/transactions/${transactionId}/category`, body);
}
