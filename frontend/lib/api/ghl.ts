import { apiClient } from './client'

export interface GHLAuthResponse {
  authorization_url: string
  message: string
}

export interface GHLAccount {
  id: number
  user_id: number
  location_id: string
  display_name: string | null
  is_default: boolean
  is_active: boolean
  expires_at: string | null
  created_at: string
  updated_at: string
}

export interface GHLExchangeResponse {
  status: string
  account_id: number
  location_id: string
  is_default: boolean
  client_state?: string
}

export interface GHLStatusResponse {
  status: string
  ghl_integration: {
    configured: boolean
    client_id_set: boolean
    client_secret_set: boolean
    redirect_uri_set: boolean
  }
}

export const ghl_api = {
  /**
   * Check if GHL integration is configured on the backend
   */
  get_status: async (client_token: string): Promise<GHLStatusResponse> => {
    const response = await apiClient.get<GHLStatusResponse>('/gh/status', {
      headers: { Authorization: `Bearer ${client_token}` }
    })
    return response.data
  },

  /**
   * Get the GHL OAuth authorization URL
   * User should be redirected to this URL to authorize the app
   */
  get_auth_url: async (
    client_token: string,
    options?: { client_state?: string; make_default?: boolean }
  ): Promise<GHLAuthResponse> => {
    const params = new URLSearchParams()
    if (options?.client_state) {
      params.append('client_state', options.client_state)
    }
    if (options?.make_default) {
      params.append('make_default', 'true')
    }
    
    const response = await apiClient.get<GHLAuthResponse>(
      `/gh/auth${params.toString() ? '?' + params.toString() : ''}`,
      { headers: { Authorization: `Bearer ${client_token}` } }
    )
    return response.data
  },

  /**
   * Manually exchange an authorization code for tokens
   * Used when the OAuth callback can't reach the backend directly
   */
  exchange_code: async (
    client_token: string,
    code: string,
    options?: { client_state?: string; make_default?: boolean }
  ): Promise<GHLExchangeResponse> => {
    const response = await apiClient.post<GHLExchangeResponse>(
      '/gh/oauth/manual-exchange',
      {
        code,
        client_state: options?.client_state,
        make_default: options?.make_default ?? false
      },
      { headers: { Authorization: `Bearer ${client_token}` } }
    )
    return response.data
  },

  /**
   * List all GHL accounts connected for the current user
   */
  list_accounts: async (client_token: string): Promise<GHLAccount[]> => {
    const response = await apiClient.get<GHLAccount[]>('/gh/accounts', {
      headers: { Authorization: `Bearer ${client_token}` }
    })
    return response.data
  },

  /**
   * List GHL accounts for a specific user (admin only)
   */
  list_accounts_for_user: async (admin_token: string, user_id: number): Promise<GHLAccount[]> => {
    const response = await apiClient.get<GHLAccount[]>(`/gh/accounts/user/${user_id}`, {
      headers: { Authorization: `Bearer ${admin_token}` }
    })
    return response.data
  },

  /**
   * Set a GHL account as the default for the current user
   */
  set_default_account: async (
    client_token: string,
    account_id: number
  ): Promise<GHLAccount> => {
    const response = await apiClient.patch<GHLAccount>(
      `/gh/accounts/${account_id}/default`,
      {},
      { headers: { Authorization: `Bearer ${client_token}` } }
    )
    return response.data
  }
}

