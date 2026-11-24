import { useCallback, useState } from "react";

/** Starea unei acțiuni a ecranului: în lucru, eroarea și mesajul de confirmare. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const run = useCallback(async (action: () => Promise<void | string>) => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const message = await action();
      if (message) setInfo(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  return { busy, error, info, run, setError };
}
