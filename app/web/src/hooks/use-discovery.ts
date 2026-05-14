import { useQuery } from "@tanstack/react-query";
import { fetchGuards, fetchHarnesses, fetchProviders } from "@/lib/api";
import { queryKeys } from "@/lib/query-client";

export function useDiscovery() {
  const { data: harnesses = [], isLoading: harnessesLoading } = useQuery({
    queryKey: queryKeys.discovery.harnesses,
    queryFn: fetchHarnesses,
  });

  const { data: providers = [], isLoading: providersLoading } = useQuery({
    queryKey: queryKeys.discovery.providers,
    queryFn: fetchProviders,
  });

  const { data: guards = [], isLoading: guardsLoading } = useQuery({
    queryKey: queryKeys.discovery.guards,
    queryFn: fetchGuards,
  });

  return {
    harnesses,
    providers,
    guards,
    loading: harnessesLoading || providersLoading || guardsLoading,
    error: null,
  };
}
