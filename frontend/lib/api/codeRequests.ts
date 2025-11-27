import axios from 'axios'
import { apiClient } from './client'
import { CodeRequestListResponse, LoginCodeAttempt } from '@/types'

// Create a silent client for polling that doesn't spam console errors
const silentClient = axios.create({
  baseURL: apiClient.defaults.baseURL,
  timeout: 30000, // 30 seconds - enough time for backend to respond
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth interceptor
silentClient.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// Suppress error logging for polling requests
silentClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // Don't log errors for polling - they're expected sometimes
    return Promise.reject(error)
  }
)

export const codeRequestsApi = {
  async list(): Promise<CodeRequestListResponse> {
    try {
      const response = await silentClient.get<CodeRequestListResponse>('/internal/verification/code-requests')
      return response.data
    } catch {
      // Return empty response on error - polling will retry
      return { pending: [], errored: [], succeeded: [] }
    }
  },

  async submit(request_id: number, code: string, operator_name?: string, source: string = 'portal'): Promise<LoginCodeAttempt> {
    const response = await apiClient.post<LoginCodeAttempt>(
      `/internal/verification/code-requests/${request_id}/submit`,
      {
        code,
        operator_name,
        source,
      }
    )
    return response.data
  },
}

