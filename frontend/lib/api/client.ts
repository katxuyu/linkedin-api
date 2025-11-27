import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'

const get_api_url = (): string => {
  if (typeof window !== 'undefined') {
    return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  }
  return process.env.NEXT_PUBLIC_API_URL_SSR || process.env.NEXT_PUBLIC_API_URL || 'http://web:8000'
}

const API_URL = get_api_url()

if (typeof window !== 'undefined') {
  console.log('[API Client] Using API URL:', API_URL)
  console.log('[API Client] Current origin:', window.location.origin)
  console.log('[API Client] Environment:', {
    is_client: true,
    api_url: API_URL,
    origin: window.location.origin,
    protocol: window.location.protocol,
    hostname: window.location.hostname,
  })
  
  setTimeout(() => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000)
    
    fetch(`${API_URL}/`, { 
      method: 'GET', 
      mode: 'cors',
      credentials: 'include',
      signal: controller.signal
    })
      .then((res) => {
        clearTimeout(timeoutId)
        if (res.ok) {
          console.log('[API Client] ✓ Backend is reachable (status:', res.status + ')')
          return res.json().catch(() => null)
        } else {
          console.warn('[API Client] ⚠ Backend responded with status:', res.status)
          return null
        }
      })
      .then((data) => {
        if (data) {
          console.log('[API Client] Backend response:', data)
        }
      })
      .catch((err) => {
        clearTimeout(timeoutId)
        if (err.name === 'AbortError' || err.message.includes('aborted')) {
          console.warn('[API Client] ⚠ Connection test timed out after 5s')
        } else if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
          console.warn('[API Client] ⚠ Backend connection test failed. This is normal if the backend is starting up.')
          console.info('[API Client] If login fails, check that Docker services are running: docker-compose -f docker-compose.dev.yml up web')
        } else {
          console.warn('[API Client] ⚠ Connection test error:', err.message)
        }
      })
  }, 1000)
}

export const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 120000, // Increased to 2 minutes for long-running operations like profile registration
  headers: {
    'Content-Type': 'application/json',
  },
})

const get_stored_token = (): string | null => {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('access_token')
  }
  return null
}

const set_cookie = (name: string, value: string, days: number = 7): void => {
  if (typeof window !== 'undefined') {
    const expires = new Date()
    expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000)
    // Use SameSite=Lax for security while allowing same-site navigation
    document.cookie = `${name}=${value};expires=${expires.toUTCString()};path=/;SameSite=Lax`
  }
}

const remove_cookie = (name: string): void => {
  if (typeof window !== 'undefined') {
    document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 UTC;path=/;`
  }
}

const store_token = (token: string): void => {
  if (typeof window !== 'undefined') {
    localStorage.setItem('access_token', token)
    // Also store in cookie for middleware to access
    set_cookie('access_token', token, 7)
  }
}

const remove_token = (): void => {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    // Also remove from cookies
    remove_cookie('access_token')
    remove_cookie('refresh_token')
  }
}

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = get_stored_token()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    } else if (typeof window !== 'undefined') {
      console.warn('[API Client] No auth token found for request:', config.url)
    }
    return config
  },
  (error: AxiosError) => {
    return Promise.reject(error)
  }
)

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined
    const responseData = error.response?.data as unknown
    const requestUrl = originalRequest?.url ?? error.config?.url ?? 'unknown'
    const requestMethod = originalRequest?.method ?? error.config?.method ?? 'unknown'
    const fullUrl = originalRequest ? `${API_URL}${originalRequest.url}` : requestUrl
    
    let resolvedMessage =
      (responseData && typeof responseData === 'object' && 'detail' in responseData && typeof responseData.detail === 'string'
        ? responseData.detail
        : undefined) ||
      (typeof responseData === 'string' ? responseData : undefined) ||
      error.message ||
      'Unknown request error'

    if (!error.response) {
      const isNetworkError = error.code === 'ECONNREFUSED' || 
                            error.message.includes('Network Error') || 
                            error.message.includes('ERR_NETWORK') ||
                            error.message.includes('Failed to fetch')
      
      const endpoint_info = requestUrl !== 'unknown' ? ` (endpoint: ${requestMethod.toUpperCase()} ${requestUrl})` : ''
      
      if (isNetworkError) {
        const is_client_side = typeof window !== 'undefined'
        const is_localhost = API_URL.includes('localhost') || API_URL.includes('127.0.0.1')
        
        let troubleshooting = ''
        if (is_client_side && is_localhost) {
          troubleshooting = ' Make sure Docker services are running: docker-compose -f docker-compose.dev.yml up web. If services are running, check that the backend is accessible on port 8000 and try refreshing the page.'
        } else if (is_client_side && !is_localhost) {
          troubleshooting = ` Verify that the backend is accessible at ${API_URL}. Check your network connection and firewall settings.`
        } else {
          troubleshooting = ` Verify that the backend service is accessible at ${API_URL} from the server environment. Check Docker network configuration.`
        }
        
        resolvedMessage = `Cannot connect to API server at ${API_URL}${endpoint_info}.${troubleshooting}`
      } else if (error.code === 'ETIMEDOUT' || error.message.includes('timeout')) {
        resolvedMessage = `Request to ${API_URL}${endpoint_info} timed out. The server may be processing a long-running request (like LinkedIn verification). Please wait and check the Verification tab.`
      } else {
        resolvedMessage = `Network error${endpoint_info}: ${error.message || 'Unable to reach the server'}. API URL: ${API_URL}. Error code: ${error.code || 'unknown'}`
      }
    } else {
      const endpoint_info = requestUrl !== 'unknown' ? ` (endpoint: ${requestMethod.toUpperCase()} ${requestUrl})` : ''
      if (!resolvedMessage || resolvedMessage === 'Unknown request error') {
        resolvedMessage = `Request failed${endpoint_info}: ${error.response.status} ${error.response.statusText || ''}`
      } else if (!resolvedMessage.includes(endpoint_info)) {
        resolvedMessage = `${resolvedMessage}${endpoint_info}`
      }
    }

    if (resolvedMessage && error.message !== resolvedMessage) {
      error.message = resolvedMessage
    }
    
    if (typeof window !== 'undefined') {
      console.error(`[API Client] Request failed: ${resolvedMessage}`, {
        url: fullUrl,
        method: requestMethod,
        status: error.response?.status ?? 'no response',
        statusText: error.response?.statusText ?? 'no status text',
        message: resolvedMessage,
        data: responseData ?? null,
        code: error.code,
        apiUrl: API_URL,
      })
    }
    
    if (error.response?.status === 428) {
      console.log('[Axios Interceptor] 428 status detected - 2FA required')
      console.log('[Axios Interceptor] Error response:', error.response)
      
      if (typeof window !== 'undefined') {
        const responseData = error.response.data as { detail?: { profile_id?: number; verification_request_id?: number; session_key?: string; expires_at?: string } } | undefined
        const detail = responseData?.detail
        if (detail && typeof detail === 'object' && 'verification_request_id' in detail) {
          const event = new CustomEvent('linkedin-2fa-required', {
            detail: {
              profile_id: detail.profile_id,
              verification_request_id: detail.verification_request_id,
              session_key: detail.session_key,
              expires_at: detail.expires_at,
              requires_2fa: true
            }
          })
          window.dispatchEvent(event)
        }
      }
      
      return Promise.reject(error)
    }
    
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true
      
      try {
        const refreshToken = typeof window !== 'undefined' 
          ? localStorage.getItem('refresh_token') 
          : null
        
        if (!refreshToken) {
          remove_token()
          if (typeof window !== 'undefined') {
            window.location.href = '/login'
          }
          return Promise.reject(error)
        }
        
        const response = await axios.post(`${API_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        })
        
        const { access_token } = response.data
        store_token(access_token)
        
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${access_token}`
        }
        
        return apiClient(originalRequest)
      } catch (refreshError) {
        remove_token()
        if (typeof window !== 'undefined') {
          window.location.href = '/login'
        }
        return Promise.reject(refreshError)
      }
    }
    
    return Promise.reject(error)
  }
)

export const check_backend_health = async (): Promise<boolean> => {
  try {
    const health_check_client = axios.create({
      baseURL: API_URL,
      timeout: 3000,
      headers: {
        'Content-Type': 'application/json',
      },
    })
    
    const response = await health_check_client.get('/')
    return response.status >= 200 && response.status < 400
  } catch (error) {
    if (typeof window !== 'undefined') {
      const error_message = error instanceof Error ? error.message : String(error)
      const is_timeout = error_message.includes('timeout') || 
                        (error as { code?: string })?.code === 'ETIMEDOUT'
      
      if (!is_timeout) {
        console.warn('[API Client] Health check failed (non-critical):', error_message)
      }
    }
    return false
  }
}

export { store_token, remove_token, get_stored_token }


