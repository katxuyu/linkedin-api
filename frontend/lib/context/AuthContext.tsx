'use client'

import React, { createContext, useContext, useState, useEffect } from 'react'
import { User, AuthTokens } from '@/types'
import { auth_api } from '@/lib/api/auth'
import { get_stored_token, remove_token } from '@/lib/api/client'
import { apiClient } from '@/lib/api/client'
import { retry_with_backoff } from '@/lib/utils/retry'

interface AuthContextType {
  user: User | null
  accessToken: string | null
  is_loading: boolean
  is_authenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

interface AuthProviderProps {
  children: React.ReactNode
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, set_user] = useState<User | null>(null)
  const [access_token, set_access_token] = useState<string | null>(null)
  const [is_loading, set_is_loading] = useState(true)

  const fetch_current_user = async (silent: boolean = false) => {
    try {
      const token = get_stored_token()
      if (!token) {
        set_is_loading(false)
        set_access_token(null)
        return
      }

      set_access_token(token)
      const response = await retry_with_backoff(
        () => apiClient.get<User>('/auth/me'),
        {
          max_retries: 2,
          initial_delay_ms: 1000,
        }
      )
      set_user(response.data)
    } catch (error) {
      if (!silent) {
        console.error('Failed to fetch user:', error)
      }
      remove_token()
      set_user(null)
      set_access_token(null)
    } finally {
      set_is_loading(false)
    }
  }

  useEffect(() => {
    fetch_current_user(true)
  }, [])

  const login = async (email: string, password: string) => {
    set_is_loading(true)
    try {
      const tokens = await auth_api.login(email, password)
      
      try {
        await fetch_current_user()
      } catch (fetch_error) {
        const error_message = fetch_error instanceof Error ? fetch_error.message : String(fetch_error)
        console.warn('[AuthContext] Login succeeded but failed to fetch user:', fetch_error)
        
        const is_network_error = error_message.includes('Cannot connect') || 
                                 error_message.includes('Network error') ||
                                 error_message.includes('timeout')
        
        if (is_network_error) {
          throw new Error(`Login successful, but unable to fetch user profile. ${error_message}`)
        }
        
        throw fetch_error
      }
    } catch (error) {
      set_is_loading(false)
      throw error
    }
  }

  const logout = () => {
    set_user(null)
    set_access_token(null)
    auth_api.logout()
  }

  const is_authenticated = !!user

  return (
    <AuthContext.Provider
      value={{
        user,
        accessToken: access_token,
        is_loading,
        is_authenticated,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}





