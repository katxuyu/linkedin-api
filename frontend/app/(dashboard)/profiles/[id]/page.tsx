'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { 
  useOutreachProfiles, 
  useUpdateProfile, 
  useProfileStats, 
  useProfileStatus,
  useVerifyProfile,
  useDeleteProfile
} from '@/lib/hooks/useProfiles'
import { ProfileEditForm } from '@/components/dashboard/ProfileEditForm'
import { ProfileStats } from '@/components/dashboard/ProfileStats'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, RefreshCw, Trash2, CheckCircle, AlertCircle, Loader2, Clock } from 'lucide-react'
import { toast } from 'sonner'
import { useTwoFactorPrompt } from '@/lib/hooks/useTwoFactorPrompt'
import { TwoFactorModal } from '@/components/forms/TwoFactorModal'
import { UpdateProfileData, TwoFactorPayload, CheckpointActionPayload } from '@/lib/api/profiles'
import { codeRequestsApi } from '@/lib/api/codeRequests'
import { 
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'

// Verification status polling component
interface VerificationStatusProps {
  profileId: number
  onStatusChange: () => void  // Called immediately when status changes (to refresh profile status)
  onDismiss: () => void       // Called when banner should be hidden
}

function VerificationStatusBanner({ profileId, onStatusChange, onDismiss }: VerificationStatusProps) {
  const [status, setStatus] = useState<'polling' | 'succeeded' | 'failed' | null>('polling')
  const [detail, setDetail] = useState<string>('Verifying your code...')
  const pollingRef = useRef<NodeJS.Timeout | null>(null)
  const pollCountRef = useRef(0)
  const hasNotifiedRef = useRef(false)
  const MAX_POLLS = 30 // 60 seconds max (30 * 2s)

  const pollStatus = useCallback(async () => {
    try {
      const response = await codeRequestsApi.list()
      const allRequests = [...response.pending, ...response.succeeded, ...response.errored]
      const ourRequest = allRequests.find(r => r.outreach_profile_id === profileId)
      
      if (ourRequest) {
        if (ourRequest.status === 'succeeded') {
          setStatus('succeeded')
          setDetail('✅ Verification successful! LinkedIn session authenticated.')
          if (pollingRef.current) clearInterval(pollingRef.current)
          
          // Immediately refresh profile status, then dismiss banner after delay
          if (!hasNotifiedRef.current) {
            hasNotifiedRef.current = true
            toast.success('Verification successful!')
            onStatusChange()  // Refresh profile status NOW
          }
          setTimeout(onDismiss, 2000)
          
        } else if (ourRequest.status === 'failed' || ourRequest.status === 'expired') {
          setStatus('failed')
          setDetail(ourRequest.status_detail || 'Verification failed')
          if (pollingRef.current) clearInterval(pollingRef.current)
          
          // Immediately refresh profile status, then dismiss banner after delay
          if (!hasNotifiedRef.current) {
            hasNotifiedRef.current = true
            toast.error(ourRequest.status_detail || 'Verification failed')
            onStatusChange()  // Refresh profile status NOW
          }
          setTimeout(onDismiss, 3000)
        }
        // If submitted/pending, keep polling
      }
      
      pollCountRef.current++
      if (pollCountRef.current >= MAX_POLLS) {
        setStatus('failed')
        setDetail('Verification timed out - please try again')
        if (pollingRef.current) clearInterval(pollingRef.current)
        if (!hasNotifiedRef.current) {
          hasNotifiedRef.current = true
          onStatusChange()
        }
        setTimeout(onDismiss, 3000)
      }
    } catch (error) {
      console.error('Polling error:', error)
    }
  }, [profileId, onStatusChange, onDismiss])

  useEffect(() => {
    // Start polling - defer first call to avoid synchronous setState in effect
    const initialPoll = setTimeout(pollStatus, 0)
    pollingRef.current = setInterval(pollStatus, 2000)
    
    return () => {
      clearTimeout(initialPoll)
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [pollStatus])

  if (!status) return null

  return (
    <div className={`p-4 rounded-lg border mb-4 ${
      status === 'polling' ? 'bg-blue-50 border-blue-200' :
      status === 'succeeded' ? 'bg-green-50 border-green-200' :
      'bg-red-50 border-red-200'
    }`}>
      <div className="flex items-center gap-3">
        {status === 'polling' && (
          <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />
        )}
        {status === 'succeeded' && (
          <CheckCircle className="h-5 w-5 text-green-600" />
        )}
        {status === 'failed' && (
          <AlertCircle className="h-5 w-5 text-red-600" />
        )}
        <div>
          <p className={`font-medium ${
            status === 'polling' ? 'text-blue-900' :
            status === 'succeeded' ? 'text-green-900' :
            'text-red-900'
          }`}>
            {status === 'polling' ? 'Verifying...' :
             status === 'succeeded' ? 'Verified!' :
             'Verification Failed'}
          </p>
          <p className={`text-sm ${
            status === 'polling' ? 'text-blue-700' :
            status === 'succeeded' ? 'text-green-700' :
            'text-red-700'
          }`}>
            {detail}
          </p>
        </div>
      </div>
    </div>
  )
}

export default function ProfileDetailPage() {
  const { accessToken } = useAuth()
  const router = useRouter()
  const params = useParams()
  const id = parseInt(params.id as string)
  const [showVerificationStatus, setShowVerificationStatus] = useState(false)
  
  // Track app approval pending state with polling
  const [appApprovalPending, setAppApprovalPending] = useState<{
    expires_at?: string
    polling?: boolean
    pollCount?: number
    started_at?: number
    message?: string
  } | null>(null)
  const [appApprovalTick, setAppApprovalTick] = useState(Date.now())
  const appApprovalPollingRef = useRef<NodeJS.Timeout | null>(null)

  const { data: profiles, isLoading: profilesLoading } = useOutreachProfiles(accessToken)
  const profile = profiles?.find(p => p.id === id)
  
  const { data: stats, isLoading: statsLoading } = useProfileStats(accessToken, id)
  const { data: status, refetch: refetchStatus } = useProfileStatus(accessToken, id)
  const statusSessionState = status?.session_status
  const isStatusVerifying = statusSessionState === 'verifying'
  const isStatusPendingApproval = statusSessionState === 'pending_approval'
  const isManualVerification = statusSessionState === 'manual_verification'
  
  // Poll for app approval completion using the profiles API
  const pollAppApprovalStatus = useCallback(async () => {
    if (!accessToken || !appApprovalPending) return
    
    try {
      // Use the profiles API to poll status - backend will check microservice
      const { profiles_api } = await import('@/lib/api/profiles')
      const data = await profiles_api.poll_app_approval_status(Number(id), accessToken)
      
      console.log('[AppApproval] Poll result:', data)
      
      // Check if connected successfully
      if (data.status === 'connected') {
        if (appApprovalPollingRef.current) {
          clearInterval(appApprovalPollingRef.current)
          appApprovalPollingRef.current = null
        }
        setAppApprovalPending(null)
        toast.success('LinkedIn approved! Connection verified successfully.')
        refetchStatus()
        return
      }
      
      // Check if still waiting for app approval
      if (data.status === '2fa_app_approval') {
        const timeoutMs = 5 * 60 * 1000
        setAppApprovalPending(prev => {
          if (!prev) return null
          const startedAt = prev.started_at ?? Date.now()
          const elapsedMs = Date.now() - startedAt
          if (elapsedMs >= timeoutMs) {
            if (appApprovalPollingRef.current) {
              clearInterval(appApprovalPollingRef.current)
              appApprovalPollingRef.current = null
            }
            toast.error('App approval timed out. Please try again.')
            return null
          }
          return {
            ...prev,
            pollCount: (prev.pollCount || 0) + 1,
            message: data.message,
            started_at: startedAt
          }
        })
        return
      }
      
      if (data.status === 'checkpoint_action_required' || data.status === 'checkpoint_unknown') {
        if (appApprovalPollingRef.current) {
          clearInterval(appApprovalPollingRef.current)
          appApprovalPollingRef.current = null
        }
        setAppApprovalPending(null)
        toast.warning(data.message || 'LinkedIn requires additional verification. Please complete the checkpoint from your LinkedIn session.')
        refetchStatus()
        return
      }
      
      // Check if error, rejected, or expired (but NOT 2fa_app_approval)
      if (data.status === 'error' || data.status === 'none') {
        if (appApprovalPollingRef.current) {
          clearInterval(appApprovalPollingRef.current)
          appApprovalPollingRef.current = null
        }
        setAppApprovalPending(null)
        
        // Show appropriate error message
        if (data.error_type === 'app_approval_rejected') {
          toast.error('Sign-in request was denied. Please try again and approve on your LinkedIn app.')
        } else if (data.error_type === 'session_expired') {
          toast.error('Session expired. Please start a new verification.')
        } else if (data.message) {
          toast.error(data.message)
        }
        refetchStatus()
        return
      }
    } catch (error) {
      console.error('Error polling app approval status:', error)
    }
  }, [accessToken, id, appApprovalPending, refetchStatus])
  
  // Start/stop polling when appApprovalPending changes
  useEffect(() => {
    if (appApprovalPending && !appApprovalPollingRef.current) {
      // Start polling every 5 seconds
      pollAppApprovalStatus() // Initial poll
      appApprovalPollingRef.current = setInterval(pollAppApprovalStatus, 5000)
    }
    
    return () => {
      if (appApprovalPollingRef.current) {
        clearInterval(appApprovalPollingRef.current)
        appApprovalPollingRef.current = null
      }
    }
  }, [appApprovalPending, pollAppApprovalStatus])
  
  useEffect(() => {
    if (!appApprovalPending) return
    const interval = setInterval(() => setAppApprovalTick(Date.now()), 1000)
    return () => clearInterval(interval)
  }, [appApprovalPending])
  
  const update_profile = useUpdateProfile(accessToken || '')
  const verify_profile = useVerifyProfile(accessToken || '')
  const delete_profile = useDeleteProfile(accessToken || '')
  const { two_factor_state, show_two_factor_prompt, hide_two_factor_prompt } = useTwoFactorPrompt()

  const handleUpdate = async (data: UpdateProfileData) => {
    try {
      await update_profile.mutateAsync({ profile_id: id, data })
    } catch (error) {
      throw error // Form handles the error toast
    }
  }

  const handleVerify = async () => {
    try {
      const result = await verify_profile.mutateAsync(id)
      
      // Handle LinkedIn App Approval required (push notification 2FA)
      if ('requires_app_approval' in result && result.requires_app_approval) {
        const expires_at = (result as { expires_at?: string }).expires_at
        setAppApprovalPending(prev => prev && prev.started_at ? { ...prev, expires_at } : { expires_at, started_at: Date.now(), pollCount: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 8000 })
        return
      }
      
      // Handle 2FA App Approval status
      if ('status' in result && result.status === '2fa_app_approval') {
        const expires_at = (result as { expires_at?: string }).expires_at
        setAppApprovalPending(prev => prev && prev.started_at ? { ...prev, expires_at } : { expires_at, started_at: Date.now(), pollCount: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 8000 })
        return
      }
      
      if ('requires_manual_action' in result && result.requires_manual_action) {
        const manualResult = result as CheckpointActionPayload
        toast.warning(manualResult.message || 'LinkedIn requires additional verification. Please log in manually to continue.')
        refetchStatus()
        return
      }
      
      // Clear app approval state on any other result
      setAppApprovalPending(null)
      
      // Handle traditional 2FA (PIN required)
      if ('requires_2fa' in result && result.requires_2fa) {
        show_two_factor_prompt(result as TwoFactorPayload, profile?.account_name || profile?.linkedin_email)
      } else if ('status' in result && result.status === 'connected') {
        toast.success('Connection verified successfully')
        refetchStatus()
      } else {
        toast.success('Connection verified successfully')
        refetchStatus()
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Verification failed'
      
      // Check if the error message indicates app approval needed
      if (message.toLowerCase().includes('app_approval') || message.toLowerCase().includes('check your linkedin app')) {
        setAppApprovalPending(prev => prev && prev.started_at ? prev : { started_at: Date.now(), pollCount: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 8000 })
        return
      }
      
      toast.error(message)
    }
  }

  const handleDelete = async () => {
    try {
      await delete_profile.mutateAsync(id)
      toast.success('Profile deleted')
      router.push('/profiles')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to delete profile'
      toast.error(message)
    }
  }

  if (!accessToken) return null

  if (profilesLoading) {
    return <div className="p-8 flex justify-center"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div></div>
  }

  if (!profile) {
    return (
      <div className="container mx-auto py-10 text-center">
        <h2 className="text-xl font-semibold">Profile not found</h2>
        <Button variant="link" onClick={() => router.push('/profiles')} className="mt-4">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Profiles
        </Button>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.push('/profiles')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">{profile.account_name || profile.linkedin_email}</h1>
              {status && (
                <Badge variant={status.is_connected ? "default" : "destructive"} className={status.is_connected ? "bg-green-600" : ""}>
                  {status.is_connected ? "Active" : "Needs Attention"}
                </Badge>
              )}
            </div>
            <p className="text-muted-foreground text-sm">
              {profile.linkedin_url}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleVerify} disabled={verify_profile.isPending}>
            <RefreshCw className={`mr-2 h-4 w-4 ${verify_profile.isPending ? 'animate-spin' : ''}`} />
            Verify Connection
          </Button>
          
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="icon">
                <Trash2 className="h-4 w-4" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete Profile?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will permanently delete this profile and all associated data. This action cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={handleDelete} className="bg-red-600">Delete</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* App Approval Modal - shows when user needs to approve on LinkedIn app */}
      {appApprovalPending && !verify_profile.isPending && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          
          {/* Modal */}
          <div className="relative bg-white rounded-2xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
            {/* Header with gradient */}
            <div className="bg-gradient-to-r from-blue-600 to-blue-700 px-6 py-5">
              <div className="flex items-center gap-3">
                <div className="bg-white/20 rounded-full p-3">
                  <svg className="h-8 w-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
                  </svg>
                </div>
                <div>
                  <h3 className="text-xl font-bold text-white">LinkedIn App Approval</h3>
                  <p className="text-blue-100 text-sm">Check your mobile device</p>
                </div>
              </div>
            </div>
            
            {/* Content */}
            <div className="px-6 py-6">
              <div className="text-center mb-6">
                <div className="inline-flex items-center justify-center w-20 h-20 bg-blue-50 rounded-full mb-4">
                  <svg className="w-10 h-10 text-blue-600 animate-pulse" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M19 7.001c0 3.865-3.134 7-7 7s-7-3.135-7-7c0-3.867 3.134-7.001 7-7.001s7 3.134 7 7.001zm-1.598 7.18c-1.506 1.137-3.374 1.82-5.402 1.82-2.03 0-3.899-.685-5.407-1.822-4.072 1.793-6.593 7.376-6.593 9.821h24c0-2.423-2.6-8.006-6.598-9.819z"/>
                  </svg>
                </div>
                <p className="text-gray-700 text-lg">
                  Open your <strong>LinkedIn app</strong> and tap
                </p>
                <div className="mt-3 inline-flex items-center gap-2 bg-green-100 text-green-800 px-4 py-2 rounded-full font-semibold">
                  <CheckCircle className="h-5 w-5" />
                  <span>Yes, it&apos;s me</span>
                </div>
                <p className="text-gray-500 text-sm mt-3">
                  to approve the sign-in request
                </p>
              </div>
              
              <div className="bg-gray-50 rounded-xl p-4 mb-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-gray-600">Account</span>
                  <span className="text-sm font-medium text-gray-900">
                    {profile?.account_name || profile?.linkedin_email}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-600">Status</span>
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
                    <span className="text-sm font-medium text-blue-600">Waiting for approval...</span>
                  </div>
                </div>
              </div>
              
              {/* Progress bar */}
              <div className="mb-4">
                {(() => {
                  const totalMs = 5 * 60 * 1000
                  const startedAt = appApprovalPending.started_at ?? appApprovalTick
                  const elapsedMs = Math.max(0, appApprovalTick - startedAt)
                  const remainingMs = Math.max(0, totalMs - elapsedMs)
                  const remainingMinutes = Math.max(0, Math.ceil(remainingMs / 60000))
                  const progress = Math.max(0, 100 - (elapsedMs / totalMs) * 100)
                  return (
                    <>
                      <div className="flex justify-between text-xs text-gray-500 mb-1">
                        <span>Time remaining</span>
                        <span>~{remainingMinutes} min</span>
                      </div>
                      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-blue-600 rounded-full transition-all duration-1000"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    </>
                  )
                })()}
              </div>
            </div>
            
            {/* Footer */}
            <div className="px-6 py-4 bg-gray-50 border-t flex justify-end">
              <Button 
                variant="outline"
                onClick={() => {
                  if (appApprovalPollingRef.current) {
                    clearInterval(appApprovalPollingRef.current)
                    appApprovalPollingRef.current = null
                  }
                  setAppApprovalPending(null)
                }}
              >
                Cancel Verification
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Loading Banner - shows while "Verify Connection" is running */}
      {verify_profile.isPending && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-4 flex items-start gap-3">
          <Loader2 className="h-5 w-5 text-blue-600 mt-0.5 animate-spin" />
          <div>
            <h4 className="font-medium text-blue-900">Verifying LinkedIn Connection</h4>
            <p className="text-sm text-blue-800 mt-1">
              Connecting to LinkedIn and checking credentials... This may take a moment.
            </p>
          </div>
        </div>
      )}

      {/* Verification Status Banner - shows when code was submitted */}
      {showVerificationStatus && !verify_profile.isPending && (
        <VerificationStatusBanner 
          profileId={id} 
          onStatusChange={() => {
            // Immediately refresh the profile status when verification completes
            refetchStatus()
          }}
          onDismiss={() => {
            setShowVerificationStatus(false)
          }}
        />
      )}

      {/* Status reminders for verification/pending approval */}
      {status && !verify_profile.isPending && (
        <>
          {isStatusVerifying && (
            <div className="bg-blue-50 border border-blue-200 rounded-md p-4 flex items-start gap-3 mb-4">
              <Loader2 className="h-5 w-5 text-blue-600 mt-0.5 animate-spin" />
              <div>
                <h4 className="font-medium text-blue-900">Verification In Progress</h4>
                <p className="text-sm text-blue-800 mt-1">
                  LinkedIn is still processing this check. You can continue working—this page will refresh automatically once we have a result.
                </p>
              </div>
            </div>
          )}
          {isStatusPendingApproval && (
            <div className="bg-indigo-50 border border-indigo-200 rounded-md p-4 flex items-start gap-3 mb-4">
              <Clock className="h-5 w-5 text-indigo-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-indigo-900">Waiting for App Approval</h4>
                <p className="text-sm text-indigo-800 mt-1">
                  Approve the sign-in request from your LinkedIn mobile app. We&apos;ll keep monitoring and update the status as soon as it completes.
                </p>
              </div>
            </div>
          )}
          {isManualVerification && (
            <div className="bg-amber-50 border border-amber-200 rounded-md p-4 flex items-start gap-3 mb-4">
              <AlertCircle className="h-5 w-5 text-amber-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-amber-900">Manual Verification Needed</h4>
                <p className="text-sm text-amber-800 mt-1">
                  {status?.issues?.[0] || 'LinkedIn is asking for additional verification. Please log in directly to your LinkedIn account to complete the checkpoint, then return here and verify again.'}
                </p>
              </div>
            </div>
          )}
        </>
      )}

      {/* Status Messages - only show when NOT verifying / pending approval and NOT using the verification banner */}
      {!verify_profile.isPending && !showVerificationStatus && status && !isStatusVerifying && !isStatusPendingApproval && !isManualVerification && (
        <>
          {/* Success state */}
          {status.is_verified && status.is_connected && status.issues.length === 0 && (
            <div className="bg-green-50 border border-green-200 rounded-md p-4 flex items-start gap-3">
              <CheckCircle className="h-5 w-5 text-green-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-green-900">Connection Verified</h4>
                <p className="text-sm text-green-800 mt-1">
                  LinkedIn session is active and authenticated.
                </p>
              </div>
            </div>
          )}
          
          {/* Error/Warning state */}
          {status.issues.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-md p-4 flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-red-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-red-900">Connection Issues Detected</h4>
                <ul className="list-disc list-inside text-sm text-red-800 mt-1">
                  {status.issues.map((issue, idx) => (
                    <li key={idx}>{issue}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </>
      )}

      {/* Stats */}
      {stats && <ProfileStats stats={stats} isLoading={statsLoading} />}

      {/* Edit Form */}
      <div className="max-w-3xl">
        <ProfileEditForm 
          profile={profile} 
          onSubmit={handleUpdate}
          isSubmitting={update_profile.isPending}
        />
      </div>

      {two_factor_state && accessToken && (
        <TwoFactorModal
          profile_id={two_factor_state.profile_id}
          profile_name={two_factor_state.profile_name}
          session_key={two_factor_state.session_key}
          expires_at={two_factor_state.expires_at}
          open={true}
          on_close={() => {
            hide_two_factor_prompt()
            // Start showing verification status on the page
            setShowVerificationStatus(true)
          }}
          on_success={() => {
            refetchStatus()
            hide_two_factor_prompt()
          }}
          client_token={accessToken}
        />
      )}
    </div>
  )
}
