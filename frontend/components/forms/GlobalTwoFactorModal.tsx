'use client'

import React, { useEffect } from 'react'
import { useTwoFactorContext } from '@/lib/context/TwoFactorContext'
import { TwoFactorModal } from './TwoFactorModal'
import { useAuth } from '@/lib/context/AuthContext'

export const GlobalTwoFactorModal: React.FC = () => {
  const { two_factor_state, show_two_factor_prompt, hide_two_factor_prompt } = useTwoFactorContext()
  const { accessToken } = useAuth()

  useEffect(() => {
    const handle_2fa_event = (event: Event) => {
      const custom_event = event as CustomEvent
      const payload = custom_event.detail
      
      if (payload && payload.verification_request_id) {
        show_two_factor_prompt(payload)
      }
    }

    window.addEventListener('linkedin-2fa-required', handle_2fa_event)

    return () => {
      window.removeEventListener('linkedin-2fa-required', handle_2fa_event)
    }
  }, [show_two_factor_prompt])

  if (!two_factor_state || !accessToken) {
    return null
  }

  return (
    <TwoFactorModal
      profile_id={two_factor_state.profile_id}
      profile_name={two_factor_state.profile_name}
      session_key={two_factor_state.session_key}
      expires_at={two_factor_state.expires_at}
      open={true}
      on_close={hide_two_factor_prompt}
      on_success={() => {
        hide_two_factor_prompt()
        window.location.reload()
      }}
      client_token={accessToken}
    />
  )
}









