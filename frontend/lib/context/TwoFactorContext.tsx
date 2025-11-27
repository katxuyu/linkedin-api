'use client'

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react'

export interface TwoFactorPayload {
  requires_2fa: true
  profile_id: number
  verification_request_id: number
  session_key: string
  expires_at: string
  profile_name?: string
}

interface TwoFactorContextType {
  two_factor_state: TwoFactorPayload | null
  show_two_factor_prompt: (payload: TwoFactorPayload, profile_name?: string) => void
  hide_two_factor_prompt: () => void
  is_showing: boolean
}

const TwoFactorContext = createContext<TwoFactorContextType | undefined>(undefined)

export const TwoFactorProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [two_factor_state, set_two_factor_state] = useState<TwoFactorPayload | null>(null)

  const show_two_factor_prompt = useCallback((payload: TwoFactorPayload, profile_name?: string) => {
    set_two_factor_state({
      ...payload,
      profile_name
    })
  }, [])

  const hide_two_factor_prompt = useCallback(() => {
    set_two_factor_state(null)
  }, [])

  return (
    <TwoFactorContext.Provider
      value={{
        two_factor_state,
        show_two_factor_prompt,
        hide_two_factor_prompt,
        is_showing: two_factor_state !== null
      }}
    >
      {children}
    </TwoFactorContext.Provider>
  )
}

export const useTwoFactorContext = () => {
  const context = useContext(TwoFactorContext)
  if (context === undefined) {
    throw new Error('useTwoFactorContext must be used within a TwoFactorProvider')
  }
  return context
}









