import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { fetchCredentials } from "@/lib/api";
import { queryKeys } from "@/lib/query-client";

export function useCredentials() {
  const queryClient = useQueryClient();

  const { data: credentials = [], isLoading: loading } = useQuery({
    queryKey: queryKeys.credentials,
    queryFn: fetchCredentials,
  });

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.credentials });
  }, [queryClient]);

  return { credentials, loading, refresh };
}
