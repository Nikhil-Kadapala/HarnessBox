import { useCallback, useEffect, useRef, useState } from "react";
import { fetchCredentials } from "@/lib/api";
import type { CredentialProbe } from "@/types";

// Global cache to persist across component re-mounts
let credentialsCache: CredentialProbe[] | null = null;
let credentialsCachePromise: Promise<CredentialProbe[]> | null = null;

export function useCredentials() {
  const [credentials, setCredentials] = useState<CredentialProbe[]>(credentialsCache ?? []);
  const [loading, setLoading] = useState(credentialsCache === null);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const probes = await fetchCredentials();
      credentialsCache = probes;
      credentialsCachePromise = null;
      if (mountedRef.current) {
        setCredentials(probes);
      }
    } catch {
      credentialsCache = [];
      credentialsCachePromise = null;
      if (mountedRef.current) {
        setCredentials([]);
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    // If we have cached data, use it immediately
    if (credentialsCache !== null) {
      setCredentials(credentialsCache);
      setLoading(false);
      return;
    }

    // If a fetch is already in progress, wait for it
    if (credentialsCachePromise) {
      credentialsCachePromise
        .then((probes) => {
          if (mountedRef.current) {
            setCredentials(probes);
            setLoading(false);
          }
        })
        .catch(() => {
          if (mountedRef.current) {
            setCredentials([]);
            setLoading(false);
          }
        });
      return;
    }

    // Otherwise start a new fetch
    credentialsCachePromise = fetchCredentials();
    credentialsCachePromise
      .then((probes) => {
        credentialsCache = probes;
        if (mountedRef.current) {
          setCredentials(probes);
        }
      })
      .catch(() => {
        credentialsCache = [];
        if (mountedRef.current) {
          setCredentials([]);
        }
      })
      .finally(() => {
        if (mountedRef.current) {
          setLoading(false);
        }
        credentialsCachePromise = null;
      });

    return () => {
      mountedRef.current = false;
    };
  }, []);

  return { credentials, loading, refresh };
}
