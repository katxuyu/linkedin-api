import { useState, useCallback } from 'react'
import { TwoFactorPayload } from '@/lib/api/profiles'

interface TwoFactorState extends TwoFactorPayload {
  profile_name?: string
}

export const useTwoFactorPrompt = () => {
  const [two_factor_state, set_two_factor_state] = useState<TwoFactorState | null>(null)

  const show_two_factor_prompt = useCallback((payload: TwoFactorPayload, profile_name?: string) => {
    set_two_factor_state({
      ...payload,
      profile_name
    })
  }, [])

  const hide_two_factor_prompt = useCallback(() => {
    set_two_factor_state(null)
  }, [])

  return {
    two_factor_state,
    show_two_factor_prompt,
    hide_two_factor_prompt,
    is_showing: two_factor_state !== null
  }
}









