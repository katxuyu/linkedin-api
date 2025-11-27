import { apiClient } from './client'
import { VerificationRequest } from '@/types'

export const verification_api = {
  get_verification_request: async (
    request_id: number,
    client_token: string
  ): Promise<VerificationRequest> => {
    const response = await apiClient.get<VerificationRequest>(
      `/internal/verification/requests/${request_id}`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  submit_verification_code: async (
    request_id: number,
    code: string,
    client_token: string,
    source: string = 'manual',
    submitted_by: string = 'admin'
  ): Promise<{ status: string; message?: string }> => {
    const response = await apiClient.post<{ status: string; message?: string }>(
      `/internal/verification/requests/${request_id}/attempts`,
      {
        code_value: code,
        source,
        submitted_by,
      },
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },
}




