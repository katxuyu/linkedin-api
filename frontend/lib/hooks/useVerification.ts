import { useQuery, useMutation } from '@tanstack/react-query'
import { verification_api } from '@/lib/api/verification'

export const useVerificationRequest = (
  request_id: number | null,
  client_token: string | null
) => {
  return useQuery({
    queryKey: ['verification-request', request_id, client_token],
    queryFn: () => verification_api.get_verification_request(request_id!, client_token!),
    enabled: !!request_id && !!client_token,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'pending') {
        return 5000
      }
      return false
    },
  })
}

export const useSubmitVerification = (client_token: string) => {
  return useMutation({
    mutationFn: (data: {
      request_id: number
      code: string
      source?: string
      submitted_by?: string
    }) =>
      verification_api.submit_verification_code(
        data.request_id,
        data.code,
        client_token,
        data.source,
        data.submitted_by
      ),
  })
}




