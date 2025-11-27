import { apiClient } from './client'
import { OutreachProfile } from '@/types'

interface RegisterProfileData {
  linkedin_email: string
  linkedin_password: string
  linkedin_url: string
  account_name?: string | null
  gohighlevel_location_id?: string | null
}

export interface ProfileStats {
  total_campaigns: number
  active_campaigns: number
  total_connections: number
  total_messages: number
  total_actions: number
  last_active?: string
}

export interface ProfileStatus {
  id: number
  is_connected: boolean
  is_verified: boolean
  last_verified_at?: string
  session_status: string
  needs_attention: boolean
  issues: string[]
  requires_manual_action?: boolean
  checkpoint_context?: Record<string, unknown> | null
}

export interface UpdateProfileData {
  linkedin_email?: string
  linkedin_password?: string
  linkedin_url?: string
  account_name?: string
  gohighlevel_location_id?: string
}

type VerifyConnectionResponse = {
  status?: string
  message?: string
  detail?: string
  requires_2fa?: boolean
}

export interface TwoFactorPayload {
  requires_2fa: true
  profile_id: number
  verification_request_id: number
  session_key: string
  expires_at: string
  error_type?: string
}

export interface AppApprovalPayload {
  status: '2fa_app_approval'
  requires_2fa: false
  requires_app_approval: true
  message: string
  error_type: '2fa_app_approval'
  expires_at?: string
}

export interface CheckpointActionPayload {
  status: 'checkpoint_action_required' | 'checkpoint_unknown'
  requires_manual_action: true
  message: string
  checkpoint_context?: Record<string, unknown> | null
}

// Type for 2FA response data from backend
interface TwoFactorResponseData {
  id?: number
  profile_id?: number
  verification_request_id?: number
  session_key?: string
  expires_at?: string
  detail?: {
    profile_id?: number
    verification_request_id?: number
    session_key?: string
    expires_at?: string
  }
}

// Type for error response with potential 2FA data
interface ErrorResponseData {
  status?: number
  data?: TwoFactorResponseData
}

export const profiles_api = {
  list_outreach_profiles: async (client_token: string): Promise<OutreachProfile[]> => {
    const response = await apiClient.get<OutreachProfile[]>('/profiles/outreach/list', {
      headers: {
        Authorization: `Bearer ${client_token}`
      }
    })
    return response.data
  },

  register_outreach_profile: async (
    data: RegisterProfileData,
    client_token: string
  ): Promise<OutreachProfile | TwoFactorPayload> => {
    try {
      const response = await apiClient.post<OutreachProfile>(
        '/profiles/outreach/register',
        data,
        {
          timeout: 120000,
          headers: {
            Authorization: `Bearer ${client_token}`
          },
          validateStatus: (status) => {
            return (status >= 200 && status < 300) || status === 428
          }
        }
      )
      
      if (response.status === 428) {
        const response_data = response.data as TwoFactorResponseData
        return {
          requires_2fa: true,
          profile_id: response_data.profile_id || response_data.id,
          verification_request_id: response_data.verification_request_id,
          session_key: response_data.session_key,
          expires_at: response_data.expires_at
        } as TwoFactorPayload
      }
      
      return response.data
    } catch (error: unknown) {
      if (error && typeof error === 'object' && 'response' in error) {
        const errResponse = (error as { response?: ErrorResponseData }).response
        if (errResponse?.status === 428) {
          const response_data = errResponse.data
          return {
            requires_2fa: true,
            profile_id: response_data?.profile_id || response_data?.id,
            verification_request_id: response_data?.verification_request_id,
            session_key: response_data?.session_key,
            expires_at: response_data?.expires_at
          } as TwoFactorPayload
        }
      }
      throw error
    }
  },

  update_profile_email: async (
    profile_id: number,
    old_email: string,
    new_email: string,
    client_token: string
  ): Promise<OutreachProfile> => {
    const response = await apiClient.put<OutreachProfile>(
      `/profiles/outreach/update/email/${profile_id}`,
      {
        old_linkedin_email: old_email,
        new_linkedin_email: new_email,
      },
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  update_profile_password: async (
    profile_id: number,
    old_password: string,
    new_password: string,
    client_token: string
  ): Promise<OutreachProfile> => {
    const response = await apiClient.put<OutreachProfile>(
      `/profiles/outreach/update/password/${profile_id}`,
      {
        old_linkedin_password: old_password,
        new_linkedin_password: new_password,
      },
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  verify_profile_connection: async (
    profile_id: number,
    client_token: string
  ): Promise<
    { status: string; message?: string; requires_2fa: boolean } |
    TwoFactorPayload |
    AppApprovalPayload |
    CheckpointActionPayload
  > => {
    const POLL_INTERVAL = 2000  // Poll every 2 seconds
    const MAX_POLLS = 90       // Max 3 minutes of polling
    
    console.log('[API] Starting verify_profile_connection for profile:', profile_id)
    
    // Step 1: Start verification (returns immediately)
    try {
      await apiClient.post(
        `/profiles/outreach/${profile_id}/verify-connection`,
        {},
        {
          timeout: 30000,  // 30 second timeout for starting
          headers: { Authorization: `Bearer ${client_token}` }
        }
      )
      console.log('[API] Verification started, now polling for result...')
    } catch (startError) {
      console.error('[API] Failed to start verification:', startError)
      throw new Error('Failed to start LinkedIn verification')
    }
    
    // Step 2: Poll for result
    for (let poll = 0; poll < MAX_POLLS; poll++) {
      await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL))
      
      try {
        const statusResponse = await apiClient.get<{ status: string; message?: string; requires_2fa?: boolean; profile_id?: number; verification_request_id?: number; session_key?: string; expires_at?: string }>(
          `/profiles/outreach/${profile_id}/verify-connection-status`,
          {
            timeout: 10000,
            headers: { Authorization: `Bearer ${client_token}` },
            validateStatus: (status) => (status >= 200 && status < 300) || status === 428
          }
        )
        
        console.log(`[API] Poll ${poll + 1}: status=${statusResponse.status}, data=`, statusResponse.data)
        
        // Handle 428 (2FA required)
        if (statusResponse.status === 428) {
          console.log('[API] 2FA required!')
          const data = statusResponse.data as TwoFactorResponseData
          if (data?.detail && typeof data.detail === 'object') {
            return {
              requires_2fa: true,
              profile_id: data.detail.profile_id || profile_id,
              verification_request_id: data.detail.verification_request_id,
              session_key: data.detail.session_key,
              expires_at: data.detail.expires_at
            } as TwoFactorPayload
          }
          return { status: '2fa_required', requires_2fa: true, message: 'LinkedIn requires 2FA verification' }
        }
        
        const data = statusResponse.data
        
        // Still processing - continue polling
        if (data.status === 'processing') {
          console.log('[API] Still processing...')
          continue
        }
        
        // Connected successfully
        if (data.status === 'connected') {
          console.log('[API] Connection verified!')
          return { status: 'connected', requires_2fa: false, message: data.message || 'Connected successfully' }
        }
        
        // 2FA App Approval required (user must approve on LinkedIn app)
        // The backend will actively check the microservice for approval status
        // Return immediately to show the UI message - frontend will start its own polling
        if (data.status === '2fa_app_approval') {
          console.log('[API] 2FA App Approval required - user needs to approve on LinkedIn app')
          return {
            status: '2fa_app_approval',
            requires_2fa: false,
            requires_app_approval: true,
            message: data.message || 'Check your LinkedIn app and tap "Yes" to approve the sign-in request.',
            error_type: '2fa_app_approval',
            expires_at: data.expires_at
          } as AppApprovalPayload
        }
        
        // 2FA PIN required (user must enter verification code)
        if (data.status === '2fa_pin_required') {
          console.log('[API] 2FA PIN required!')
          return {
            requires_2fa: true,
            profile_id: data.profile_id || profile_id,
            verification_request_id: data.verification_request_id,
            session_key: data.session_key,
            expires_at: data.expires_at,
            error_type: '2fa_pin'
          } as TwoFactorPayload
        }
        
        // 2FA required (legacy/generic - from response body)
        if (data.status === '2fa_required' || data.requires_2fa) {
          console.log('[API] 2FA required (from body)!')
          return {
            requires_2fa: true,
            profile_id: data.profile_id || profile_id,
            verification_request_id: data.verification_request_id,
            session_key: data.session_key,
            expires_at: data.expires_at
          } as TwoFactorPayload
        }
        
        if (data.status === 'checkpoint_action_required' || data.status === 'checkpoint_unknown') {
          return {
            status: data.status,
            requires_2fa: false,
            requires_manual_action: true,
            message: data.message || 'LinkedIn requires additional verification.',
            checkpoint_context: (data as { checkpoint_context?: Record<string, unknown> }).checkpoint_context ?? null
          } as CheckpointActionPayload
        }
        
        // Error
        if (data.status === 'error') {
          console.log('[API] Verification failed:', data.message)
          // Include error_type in the error message if available
          const errorType = (data as { error_type?: string }).error_type
          const errorMessage = errorType 
            ? `${data.message || 'Verification failed'} [${errorType}]`
            : data.message || 'Verification failed'
          throw new Error(errorMessage)
        }
        
        // No status in progress
        if (data.status === 'none') {
          console.log('[API] No verification in progress')
          throw new Error('No verification in progress')
        }
        
      } catch (pollError: unknown) {
        // Check if it's a 428 error
        if (pollError && typeof pollError === 'object' && 'response' in pollError) {
          const errResponse = (pollError as { response?: ErrorResponseData }).response
          if (errResponse?.status === 428) {
            const data = errResponse.data?.detail || errResponse.data
            return {
              requires_2fa: true,
              profile_id: data?.profile_id || profile_id,
              verification_request_id: data?.verification_request_id,
              session_key: data?.session_key,
              expires_at: data?.expires_at
            } as TwoFactorPayload
          }
        }
        // Re-throw other errors
        if (pollError instanceof Error && !pollError.message.includes('timeout')) {
          throw pollError
        }
        // Continue polling on timeout
        console.log('[API] Poll timeout, retrying...')
      }
    }
    
    throw new Error('Verification timed out after 3 minutes')
  },

  // Keep old method for backward compatibility
  verify_profile_connection_legacy: async (
    profile_id: number,
    client_token: string
  ): Promise<{ status: string; message?: string; requires_2fa: boolean } | TwoFactorPayload> => {
    try {
      console.log('[API] Starting verify_profile_connection_legacy for profile:', profile_id)
      
      const response = await apiClient.post<VerifyConnectionResponse>(
        `/profiles/outreach/${profile_id}/verify-connection`,
        {},
        {
          timeout: 120000,
          headers: { Authorization: `Bearer ${client_token}` },
          validateStatus: (status) => (status >= 200 && status < 300) || status === 428
        }
      )
      
      if (response.status === 428) {
        const data = response.data as TwoFactorResponseData
        if (data?.detail && typeof data.detail === 'object') {
          return {
            requires_2fa: true,
            profile_id: data.detail.profile_id || profile_id,
            verification_request_id: data.detail.verification_request_id,
            session_key: data.detail.session_key,
            expires_at: data.detail.expires_at
          } as TwoFactorPayload
        }
        return { status: 'requires_2fa', requires_2fa: true, message: 'LinkedIn requires 2FA verification' }
      }
      
      const data = response.data
      if (data?.status === 'connected') {
        return { status: 'connected', requires_2fa: false, message: data.message || 'Connected successfully' }
      }
      
      return { status: data?.status || 'unknown', requires_2fa: false, message: data?.message }
    } catch (error: unknown) {
      if (error && typeof error === 'object' && 'response' in error) {
        const errResponse = (error as { response?: ErrorResponseData }).response
        if (errResponse?.status === 428) {
          const data = errResponse.data as TwoFactorResponseData
          if (data?.detail && typeof data.detail === 'object') {
            return {
              requires_2fa: true,
              profile_id: data.detail.profile_id || profile_id,
              verification_request_id: data.detail.verification_request_id,
              session_key: data.detail.session_key,
              expires_at: data.detail.expires_at
            } as TwoFactorPayload
          }
        }
      }
      throw error
    }
  },

  submit_pin_verification: async (
    profile_id: number,
    pin: string,
    client_token: string,
    operator_name?: string
  ): Promise<{ status: string; message: string; success: boolean }> => {
    try {
      const response = await apiClient.post<{ status: string; message: string }>(
        `/profiles/outreach/${profile_id}/verify-pin`,
        { pin, operator_name },
        {
          headers: {
            Authorization: `Bearer ${client_token}`
          }
        }
      )
      return { ...response.data, success: true }
    } catch (error: unknown) {
      // PIN verification failures are expected (400 status) - don't propagate error
      // The profile page will poll for the actual status
      const err = error as { response?: { data?: { detail?: string } } }
      const detail = err.response?.data?.detail || 'PIN verification failed'
      console.log('[profiles_api] PIN verification returned:', detail)
      return { status: 'error', message: detail, success: false }
    }
  },

  /**
   * Poll for app approval status (push notification 2FA).
   * This is used after verify_profile_connection returns 2fa_app_approval.
   * The backend will actively check the microservice for approval status.
   * 
   * @returns Promise with status: 'connected' | '2fa_app_approval' | 'error'
   */
  poll_app_approval_status: async (
    profile_id: number,
    client_token: string
  ): Promise<{ status: string; message?: string; error_type?: string; checkpoint_context?: Record<string, unknown> }> => {
    try {
      const response = await apiClient.get<{ status: string; message?: string; error_type?: string }>(
        `/profiles/outreach/${profile_id}/verify-connection-status`,
        {
          timeout: 15000,
          headers: { Authorization: `Bearer ${client_token}` },
          validateStatus: () => true
        }
      )
      
      if (response.status >= 500) {
        console.warn('[API] poll_app_approval_status server error:', response.status, response.data)
        return {
          status: '2fa_app_approval',
          message: 'Waiting for LinkedIn approval...'
        }
      }
      
      console.log('[API] poll_app_approval_status response:', response.data)
      return response.data
    } catch (error: unknown) {
      console.error('[API] poll_app_approval_status error:', error)
      return {
        status: '2fa_app_approval',
        message: 'Still waiting for approval...'
      }
    }
  },

  cancel_2fa_session: async (
    profile_id: number,
    client_token: string
  ): Promise<{ status: string; message: string }> => {
    const response = await apiClient.post<{ status: string; message: string }>(
      `/profiles/outreach/${profile_id}/cancel-2fa`,
      {},
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  delete_profile: async (
    profile_id: number,
    client_token: string
  ): Promise<{ id: number; status: string; message: string }> => {
    const response = await apiClient.delete<{ id: number; status: string; message: string }>(
      `/profiles/outreach/${profile_id}`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  update_profile_all_fields: async (
    profile_id: number,
    data: UpdateProfileData,
    client_token: string
  ): Promise<OutreachProfile> => {
    const response = await apiClient.put<OutreachProfile>(
      `/profiles/outreach/${profile_id}`,
      data,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_profile_stats: async (
    profile_id: number,
    client_token: string
  ): Promise<ProfileStats> => {
    const response = await apiClient.get<ProfileStats>(
      `/profiles/outreach/${profile_id}/stats`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_profile_status: async (
    profile_id: number,
    client_token: string
  ): Promise<ProfileStatus> => {
    const response = await apiClient.get<ProfileStatus>(
      `/profiles/outreach/${profile_id}/status`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data
  },

  get_profiles_status_bulk: async (
    profile_ids: number[],
    client_token: string
  ): Promise<Record<number, ProfileStatus>> => {
    if (profile_ids.length === 0) {
      return {}
    }
    const response = await apiClient.get<{ statuses: Record<number, ProfileStatus> }>(
      `/profiles/outreach/status/bulk?profile_ids=${profile_ids.join(',')}`,
      {
        headers: {
          Authorization: `Bearer ${client_token}`
        }
      }
    )
    return response.data.statuses
  },
}


