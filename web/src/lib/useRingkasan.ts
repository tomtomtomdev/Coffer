import { useEffect, useState } from "react";

import { fetchRingkasan } from "../api/client";
import type { RingkasanResponse } from "../api/types";

export type RingkasanState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: RingkasanResponse };

/** Fetch the Ringkasan payload for a household, aborting on unmount / id change. */
export function useRingkasan(householdId: number): RingkasanState {
  const [state, setState] = useState<RingkasanState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    fetchRingkasan(householdId, controller.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "Gagal memuat data",
        });
      });
    return () => controller.abort();
  }, [householdId]);

  return state;
}
