'use client'

import React, { useState, useEffect } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { useVerificationRequest, useSubmitVerification } from '@/lib/hooks/useVerification'
import { toast } from 'sonner'

interface VerificationModalProps {
  request_id: number | null
  client_token: string | null
  open: boolean
  on_close: () => void
  on_success?: () => void
}

export const VerificationModal: React.FC<VerificationModalProps> = ({
  request_id,
  client_token,
  open,
  on_close,
  on_success,
}) => {
  const { data: verification_request, isLoading } = useVerificationRequest(
    request_id,
    client_token
  )
  const submit_verification = useSubmitVerification(client_token || '')
  
  const [code, set_code] = useState('')

  useEffect(() => {
    if (verification_request?.status === 'completed') {
      toast.success('Verification completed!')
      if (on_success) {
        on_success()
      }
      on_close()
    }
  }, [verification_request?.status, on_success, on_close])

  const handle_submit = async () => {
    if (!code.trim()) {
      toast.error('Please enter a verification code')
      return
    }

    if (!request_id) {
      toast.error('No verification request found')
      return
    }

    try {
      await submit_verification.mutateAsync({
        request_id,
        code: code.trim(),
        source: 'manual',
        submitted_by: 'admin',
      })

      toast.success('Verification code submitted')
      set_code('')
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        (error instanceof Error ? error.message : 'Failed to submit code')
      toast.error(message)
    }
  }

  const format_remaining_time = (seconds: number): string => {
    const minutes = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${minutes}:${secs.toString().padStart(2, '0')}`
  }

  return (
    <Dialog open={open} onOpenChange={(is_open) => !is_open && on_close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>LinkedIn Verification Required</DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="text-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
            <p className="mt-2 text-gray-600">Loading verification request...</p>
          </div>
        ) : verification_request ? (
          <div className="space-y-4">
            <div className="bg-blue-50 p-4 rounded-lg">
              <p className="text-sm font-medium text-blue-900 mb-2">
                Verification Details
              </p>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-blue-700">Status:</span>
                  <Badge variant={verification_request.status === 'pending' ? 'default' : 'secondary'}>
                    {verification_request.status}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-blue-700">Type:</span>
                  <span className="text-blue-900">{verification_request.request_type}</span>
                </div>
                {verification_request.pending_reason && (
                  <div className="flex justify-between">
                    <span className="text-blue-700">Reason:</span>
                    <span className="text-blue-900">{verification_request.pending_reason}</span>
                  </div>
                )}
                {verification_request.remaining_seconds > 0 && (
                  <div className="flex justify-between">
                    <span className="text-blue-700">Time Remaining:</span>
                    <span className="text-blue-900 font-mono">
                      {format_remaining_time(verification_request.remaining_seconds)}
                    </span>
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="verification-code">Verification Code</Label>
              <Input
                id="verification-code"
                type="text"
                value={code}
                onChange={(e) => set_code(e.target.value)}
                placeholder="Enter code from LinkedIn"
                disabled={submit_verification.isPending || verification_request.status !== 'pending'}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handle_submit()
                  }
                }}
              />
              <p className="text-xs text-gray-600">
                Check your email or phone for the verification code from LinkedIn
              </p>
            </div>

            {verification_request.status === 'pending' && (
              <div className="bg-yellow-50 border border-yellow-200 p-3 rounded-lg">
                <p className="text-xs text-yellow-800">
                  ⏱ This verification request will expire in{' '}
                  {format_remaining_time(verification_request.remaining_seconds)}
                </p>
              </div>
            )}

            {verification_request.status === 'expired' && (
              <div className="bg-red-50 border border-red-200 p-3 rounded-lg">
                <p className="text-xs text-red-800">
                  This verification request has expired. Please try logging in again.
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-gray-600">No verification request found</p>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={on_close}>
            Close
          </Button>
          {verification_request?.status === 'pending' && (
            <Button
              onClick={handle_submit}
              disabled={submit_verification.isPending || !code.trim()}
            >
              {submit_verification.isPending ? 'Submitting...' : 'Submit Code'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}




