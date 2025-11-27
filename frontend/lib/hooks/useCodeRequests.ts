import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { codeRequestsApi } from '@/lib/api/codeRequests'

const QUERY_KEY = ['code-requests']

export const useCodeRequests = () => {
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => {
      try {
        return await codeRequestsApi.list()
      } catch (error) {
        // Silently fail for polling - don't spam console with errors
        // The UI will show stale data which is fine for polling
        if (typeof window !== 'undefined') {
          // Only log once per minute max to avoid spam
          const lastLogKey = 'code-requests-last-error-log'
          const lastLog = sessionStorage.getItem(lastLogKey)
          const now = Date.now()
          if (!lastLog || now - parseInt(lastLog) > 60000) {
            console.warn('[useCodeRequests] Polling failed, will retry:', 
              error instanceof Error ? error.message : 'Unknown error')
            sessionStorage.setItem(lastLogKey, now.toString())
          }
        }
        throw error // Re-throw so react-query knows it failed
      }
    },
    refetchInterval: 8000,
    staleTime: 4000,
    retry: 2, // Retry twice before giving up
    retryDelay: 1000, // Wait 1 second between retries
    refetchOnWindowFocus: false, // Don't refetch on window focus to reduce load
  })

  return {
    ...query,
    pending: query.data?.pending ?? [],
    succeeded: query.data?.succeeded ?? [],
    errored: query.data?.errored ?? [],
    lastUpdated: query.dataUpdatedAt,
  }
}

export const useSubmitCodeRequest = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ request_id, code, operator_name }: { request_id: number; code: string; operator_name?: string }) =>
      codeRequestsApi.submit(request_id, code, operator_name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY })
    },
  })
}

