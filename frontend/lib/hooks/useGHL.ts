import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ghl_api, GHLAccount, GHLAuthResponse, GHLExchangeResponse, GHLStatusResponse } from '@/lib/api/ghl'

/**
 * Check if GHL integration is configured
 */
export const useGHLStatus = (client_token: string | null) => {
  return useQuery<GHLStatusResponse>({
    queryKey: ['ghl-status', client_token],
    queryFn: () => ghl_api.get_status(client_token!),
    enabled: !!client_token,
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: false, // Don't retry if GHL is not configured
  })
}

/**
 * List GHL accounts for the current user
 */
export const useGHLAccounts = (client_token: string | null) => {
  return useQuery<GHLAccount[]>({
    queryKey: ['ghl-accounts', client_token],
    queryFn: () => ghl_api.list_accounts(client_token!),
    enabled: !!client_token,
    staleTime: 30 * 1000, // 30 seconds
  })
}

/**
 * List GHL accounts for a specific user (admin only)
 */
export const useGHLAccountsForUser = (admin_token: string | null, user_id: number | null) => {
  return useQuery<GHLAccount[]>({
    queryKey: ['ghl-accounts-user', admin_token, user_id],
    queryFn: () => ghl_api.list_accounts_for_user(admin_token!, user_id!),
    enabled: !!admin_token && !!user_id,
    staleTime: 30 * 1000, // 30 seconds
  })
}

/**
 * Get GHL OAuth authorization URL
 */
export const useGHLAuthUrl = (client_token: string) => {
  return useMutation<GHLAuthResponse, Error, { client_state?: string; make_default?: boolean }>({
    mutationFn: (options) => ghl_api.get_auth_url(client_token, options),
  })
}

/**
 * Exchange authorization code for tokens
 */
export const useGHLExchangeCode = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation<GHLExchangeResponse, Error, { code: string; client_state?: string; make_default?: boolean }>({
    mutationFn: ({ code, client_state, make_default }) => 
      ghl_api.exchange_code(client_token, code, { client_state, make_default }),
    onSuccess: () => {
      // Invalidate accounts list to refresh
      query_client.invalidateQueries({ queryKey: ['ghl-accounts'] })
    },
  })
}

/**
 * Set default GHL account
 */
export const useSetDefaultGHLAccount = (client_token: string) => {
  const query_client = useQueryClient()
  
  return useMutation<GHLAccount, Error, number>({
    mutationFn: (account_id) => ghl_api.set_default_account(client_token, account_id),
    onSuccess: () => {
      query_client.invalidateQueries({ queryKey: ['ghl-accounts'] })
    },
  })
}

