'use client'

import { useState, useEffect } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { profiles_api } from '@/lib/api/profiles'
import { toast } from 'sonner'
import Link from 'next/link'

const OPERATOR_STORAGE_KEY = 'code-request-operator-name'

interface TwoFactorModalProps {
  profile_id: number
  profile_name?: string
  session_key: string
  expires_at: string
  open: boolean
  on_close: () => void
  on_success?: () => void
  client_token: string
}

export function TwoFactorModal({
  profile_id,
  profile_name,
  session_key,
  expires_at,
  open,
  on_close,
  on_success,
  client_token,
}: TwoFactorModalProps) {
  const [code, set_code] = useState('')
  const [operator_name, set_operator_name] = useState(() => {
    if (typeof window === 'undefined') return ''
    return localStorage.getItem(OPERATOR_STORAGE_KEY) || ''
  })
  const [is_submitting, set_is_submitting] = useState(false)
  const [remaining_seconds, set_remaining_seconds] = useState(0)

  useEffect(() => {
    if (!expires_at) return

    const calculate_remaining = () => {
      const expires = new Date(expires_at).getTime()
      const now = Date.now()
      const remaining = Math.max(0, Math.floor((expires - now) / 1000))
      set_remaining_seconds(remaining)
      
      if (remaining === 0) {
        toast.error('Verification session expired. Please start a new verification.')
        on_close()
      }
    }

    calculate_remaining()
    const interval = setInterval(calculate_remaining, 1000)

    return () => clearInterval(interval)
  }, [expires_at, on_close])

  const format_remaining_time = (seconds: number): string => {
    const minutes = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${minutes}:${secs.toString().padStart(2, '0')}`
  }

  const handle_operator_change = (value: string) => {
    set_operator_name(value)
    if (value.trim()) {
      localStorage.setItem(OPERATOR_STORAGE_KEY, value.trim())
    }
  }

  const handle_submit = async () => {
    if (!operator_name.trim()) {
      toast.error('Please enter your name or initials')
      return
    }
    if (!code.trim()) {
      toast.error('Please enter a verification code')
      return
    }

    set_is_submitting(true)
    
    // Fire-and-forget: Submit the code, then close the modal
    // The profile page will show the verification result
    profiles_api.submit_pin_verification(profile_id, code.trim(), client_token, operator_name.trim())
      .then(() => {
        console.log('[TwoFactorModal] PIN submission completed successfully')
      })
      .catch((error) => {
        // Expected - backend returns 400 when PIN fails
        console.log('[TwoFactorModal] PIN submission returned error:', error?.message || 'unknown')
      })
    
    // Show toast and close modal - profile page will show the result
    toast.info('📤 Code submitted! Check the profile status for verification result.')
    set_is_submitting(false)
    
    // Close modal after a brief delay so user sees the toast
    setTimeout(() => {
      on_close()
    }, 500)
  }

  const handle_cancel = async () => {
    try {
      await profiles_api.cancel_2fa_session(profile_id, client_token)
    } catch (error) {
      console.error('Failed to cancel 2FA session:', error)
    }
    on_close()
  }

  // Check if form should be interactive
  const is_expired = remaining_seconds === 0
  const can_submit = !is_expired && !is_submitting

  return (
    <Dialog open={open} onOpenChange={(is_open) => !is_open && on_close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>LinkedIn 2FA Verification Required</DialogTitle>
          <DialogDescription>
            {profile_name ? `Verification needed for ${profile_name}` : 'LinkedIn requires verification to continue'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Expired State */}
          {is_expired ? (
            <div className="bg-amber-50 border border-amber-200 p-4 rounded-lg text-center">
              <p className="text-lg font-semibold text-amber-800">⏱ Session Expired</p>
              <p className="text-sm text-amber-700 mt-1">
                The verification session has timed out. Please start a new verification.
              </p>
            </div>
          ) : (
            <>
              <div className="bg-blue-50 p-4 rounded-lg">
                <p className="text-sm font-medium text-blue-900 mb-1">
                  Check your email or phone
                </p>
                <p className="text-xs text-blue-700">
                  LinkedIn has sent a verification code. Enter it below to complete the connection.
                </p>
                {remaining_seconds > 0 && (
                  <p className="text-xs text-blue-700 mt-2">
                    ⏱ Time remaining: {format_remaining_time(remaining_seconds)}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="operator-name">Your Name / Initials <span className="text-red-500">*</span></Label>
                <Input
                  id="operator-name"
                  type="text"
                  value={operator_name}
                  onChange={(e) => handle_operator_change(e.target.value)}
                  placeholder="e.g. JD or Ops Team"
                  disabled={is_submitting}
                  autoFocus={!operator_name}
                />
                <p className="text-xs text-gray-500">Required for audit trail</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="verification-code">Verification Code <span className="text-red-500">*</span></Label>
                <Input
                  id="verification-code"
                  type="text"
                  value={code}
                  onChange={(e) => set_code(e.target.value)}
                  placeholder="Enter 6-digit code"
                  maxLength={6}
                  disabled={is_submitting}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && can_submit && code.trim() && operator_name.trim()) {
                      handle_submit()
                    }
                  }}
                  autoFocus={!!operator_name}
                />
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          {is_expired ? (
            <Button onClick={on_close}>
              Close
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={handle_cancel} disabled={is_submitting}>
                Cancel & Close Session
              </Button>
              <Button onClick={handle_submit} disabled={!can_submit || !code.trim() || !operator_name.trim()}>
                {is_submitting ? 'Submitting...' : 'Verify'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

