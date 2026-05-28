import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-client";
import { fetchGitHubProfile } from "@/lib/api";

export type { GitHubProfile } from "@/lib/api";

export function useGitHubProfile() {
  const { data: profile, isLoading, isError } = useQuery({
    queryKey: queryKeys.githubProfile,
    queryFn: fetchGitHubProfile,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  return { profile: profile ?? null, loading: isLoading, unavailable: isError };
}
