import { useCallback, useEffect, useRef, useState } from "react";
import { fetchCredentials } from "@/lib/api";
import type { CredentialProbe } from "@/types";

export function useCredentials() {
  const [credentials, setCredentials] = useState<CredentialProbe[]>([]);
  const [loading, setLoading] = useState(true);
  const initialized = useRef(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const probes = await fetchCredentials();
      setCredentials(probes);
    } catch {
      setCredentials([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    let cancelled = false;
    fetchCredentials()
      .then((probes) => {
        if (!cancelled) setCredentials(probes);
      })
      .catch(() => {
        if (!cancelled) setCredentials([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { credentials, loading, refresh };
}
