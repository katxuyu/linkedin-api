import { apiClient, store_token, remove_token, check_backend_health } from './client'
import { AuthTokens, RegistrationKey } from '@/types'
import { retry_with_backoff } from '@/lib/utils/retry'

export const auth_api = {
  login: async (email: string, password: string): Promise<AuthTokens> => {
    const is_healthy = await check_backend_health()
    if (!is_healthy && typeof window !== 'undefined') {
      console.warn('[Auth API] Health check failed, but proceeding with login attempt. The actual request will verify connectivity.')
    }
    
    const response = await retry_with_backoff(
      () => apiClient.post<AuthTokens>('/auth/login', {
        email,
        password,
      }),
      {
        max_retries: 2,
        initial_delay_ms: 1000,
      }
    )
    
    if (typeof window !== 'undefined') {
      store_token(response.data.access_token)
      localStorage.setItem('refresh_token', response.data.refresh_token)
    }
    
    return response.data
  },

  generate_registration_key: async (): Promise<RegistrationKey> => {
    const response = await apiClient.post<RegistrationKey>('/admin/registration-keys')
    return response.data
  },

  register_client: async (
    email: string,
    password: string,
    registration_key: string
  ): Promise<{ id: number; email: string; created_at: string }> => {
    const response = await apiClient.post('/auth/register', {
      email,
      password,
      registration_key,
    })
    return response.data
  },

  logout: (): void => {
    if (typeof window !== 'undefined') {
      // This removes from both localStorage and cookies
      remove_token()
      window.location.href = '/login'
    }
  },
}





