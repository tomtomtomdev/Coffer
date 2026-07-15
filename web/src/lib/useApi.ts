import { useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

/** Generic fetch-into-state hook, re-run when `key` changes; aborts in flight on cleanup. */
export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  key: unknown,
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    fetcher(controller.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "Gagal memuat data",
        });
      });
    return () => controller.abort();
    // Keyed by `key`; `fetcher` is recreated each render so it is intentionally excluded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
