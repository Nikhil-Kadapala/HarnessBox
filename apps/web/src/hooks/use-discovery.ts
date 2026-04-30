import { useEffect, useState } from "react";
import { fetchGuards, fetchHarnesses, fetchProviders } from "@/lib/api";
import type { GuardInfo, HarnessInfo, ProviderInfo } from "@/types";

export function useDiscovery() {
  const [harnesses, setHarnesses] = useState<HarnessInfo[]>([]);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [guards, setGuards] = useState<GuardInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchHarnesses(), fetchProviders(), fetchGuards()])
      .then(([h, p, g]) => {
        if (cancelled) return;
        setHarnesses(h);
        setProviders(p);
        setGuards(g);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load configuration");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { harnesses, providers, guards, loading, error };
}
