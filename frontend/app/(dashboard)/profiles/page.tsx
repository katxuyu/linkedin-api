'use client'

import React, { useState, useRef, useCallback, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { useOutreachProfiles, useDeleteProfile, useVerifyProfile, useProfilesStatusBulk } from '@/lib/hooks/useProfiles'
import { ProfileCard } from '@/components/dashboard/ProfileCard'
import { ProfilesTable } from '@/components/dashboard/ProfilesTable'
import { ViewToggle } from '@/components/ui/view-toggle'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Plus, Search, Loader2, CheckCircle } from 'lucide-react'
import { toast } from 'sonner'
import { get_view_preference, save_view_preference } from '@/lib/utils/view-preferences'
import { useTwoFactorPrompt } from '@/lib/hooks/useTwoFactorPrompt'
import { TwoFactorModal } from '@/components/forms/TwoFactorModal'
import { TwoFactorPayload, CheckpointActionPayload } from '@/lib/api/profiles'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

export default function ProfilesPage() {
  const { accessToken } = useAuth()
  const router = useRouter()
  const { data: profiles, isLoading, error, refetch } = useOutreachProfiles(accessToken)
  const delete_profile = useDeleteProfile(accessToken || '')
  const verify_profile = useVerifyProfile(accessToken || '')
  const { two_factor_state, show_two_factor_prompt, hide_two_factor_prompt } = useTwoFactorPrompt()
  
  const profile_ids = profiles?.map(p => p.id) || []
  const { data: statuses } = useProfilesStatusBulk(accessToken, profile_ids)
  
  const [searchQuery, setSearchQuery] = useState('')
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [viewMode, setViewMode] = useState<'card' | 'list'>(() => get_view_preference('profiles'))
  
  // Track profiles waiting for app approval (push notification 2FA) with polling
  const [app_approval_pending, set_app_approval_pending] = useState<{
    profile_id: number
    profile_name: string
    expires_at?: string
    poll_count?: number
    started_at?: number
    message?: string
  } | null>(null)
  const [appApprovalTick, setAppApprovalTick] = useState(Date.now())
  const app_approval_polling_ref = useRef<NodeJS.Timeout | null>(null)
  
  // Poll for app approval completion using the profiles API
  const poll_app_approval_status = useCallback(async () => {
    if (!accessToken || !app_approval_pending) return
    
    try {
      // Use the profiles API to poll status - backend will check microservice
      const { profiles_api } = await import('@/lib/api/profiles')
      const data = await profiles_api.poll_app_approval_status(app_approval_pending.profile_id, accessToken)
      
      console.log('[AppApproval] Poll result:', data)
      
      if (data.status === 'connected') {
        if (app_approval_polling_ref.current) {
          clearInterval(app_approval_polling_ref.current)
          app_approval_polling_ref.current = null
        }
        set_app_approval_pending(null)
        toast.success('LinkedIn approved! Connection verified successfully.')
        refetch()
        return
      }
      
      if (data.status === '2fa_app_approval') {
        const timeoutMs = 5 * 60 * 1000
        set_app_approval_pending(prev => {
          if (!prev) return null
          const startedAt = prev.started_at ?? Date.now()
          const elapsedMs = Date.now() - startedAt
          if (elapsedMs >= timeoutMs) {
            if (app_approval_polling_ref.current) {
              clearInterval(app_approval_polling_ref.current)
              app_approval_polling_ref.current = null
            }
            toast.error('App approval timed out. Please try again.')
            return null
          }
          return {
            ...prev,
            poll_count: (prev.poll_count || 0) + 1,
            message: data.message,
            started_at: startedAt
          }
        })
        return
      }
      
      if (data.status === 'checkpoint_action_required' || data.status === 'checkpoint_unknown') {
        if (app_approval_polling_ref.current) {
          clearInterval(app_approval_polling_ref.current)
          app_approval_polling_ref.current = null
        }
        set_app_approval_pending(null)
        toast.warning(data.message || 'LinkedIn requires additional verification. Please log in manually to resolve the checkpoint.')
        refetch()
        return
      }
      
      // Check if error, rejected, or expired (but NOT 2fa_app_approval)
      if (data.status === 'error' || data.status === 'none') {
        if (app_approval_polling_ref.current) {
          clearInterval(app_approval_polling_ref.current)
          app_approval_polling_ref.current = null
        }
        set_app_approval_pending(null)
        
        // Show appropriate error message
        if (data.error_type === 'app_approval_rejected') {
          toast.error('Sign-in request was denied. Please try again and approve on your LinkedIn app.')
        } else if (data.error_type === 'session_expired') {
          toast.error('Session expired. Please start a new verification.')
        } else if (data.message) {
          toast.error(data.message)
        }
        refetch()
        return
      }
    } catch (error) {
      console.error('Error polling app approval status:', error)
    }
  }, [accessToken, app_approval_pending, refetch])
  
  useEffect(() => {
    if (app_approval_pending && !app_approval_polling_ref.current) {
      poll_app_approval_status()
      app_approval_polling_ref.current = setInterval(poll_app_approval_status, 5000)
    }
    
    return () => {
      if (app_approval_polling_ref.current) {
        clearInterval(app_approval_polling_ref.current)
        app_approval_polling_ref.current = null
      }
    }
  }, [app_approval_pending, poll_app_approval_status])

useEffect(() => {
  if (!app_approval_pending) return
  const interval = setInterval(() => setAppApprovalTick(Date.now()), 1000)
  return () => clearInterval(interval)
}, [app_approval_pending])

  const handle_view_change = (mode: 'card' | 'list') => {
    setViewMode(mode)
    save_view_preference('profiles', mode)
  }

  const filteredProfiles = profiles?.filter(profile => 
    (profile.account_name?.toLowerCase().includes(searchQuery.toLowerCase()) || 
     profile.linkedin_email.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  const handleDelete = async () => {
    if (!deleteId) return
    try {
      await delete_profile.mutateAsync(deleteId)
      toast.success('Profile deleted successfully')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to delete profile'
      toast.error(message)
    } finally {
      setDeleteId(null)
    }
  }

  const handleVerify = async (id: number) => {
    const profile = profiles?.find(p => p.id === id)
    const profile_name = profile?.account_name || profile?.linkedin_email || `Profile ${id}`
    
    try {
      const result = await verify_profile.mutateAsync(id)
      
      // Handle LinkedIn App Approval required (push notification 2FA)
      if ('requires_app_approval' in result && result.requires_app_approval) {
        const expires_at = (result as { expires_at?: string }).expires_at
        set_app_approval_pending(prev => prev && prev.started_at ? { ...prev, expires_at } : { profile_id: id, profile_name, expires_at, started_at: Date.now(), poll_count: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 5000 })
        return
      }
      
      // Handle 2FA App Approval status
      if ('status' in result && result.status === '2fa_app_approval') {
        const expires_at = (result as { expires_at?: string }).expires_at
        set_app_approval_pending(prev => prev && prev.started_at ? { ...prev, expires_at } : { profile_id: id, profile_name, expires_at, started_at: Date.now(), poll_count: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 5000 })
        return
      }
      
      if ('requires_manual_action' in result && result.requires_manual_action) {
        const manualResult = result as CheckpointActionPayload
        toast.warning(manualResult.message || 'LinkedIn requires additional verification. Please log in manually to continue.')
        refetch()
        return
      }
      
      // Clear any pending app approval on success
      set_app_approval_pending(null)
      
      if ('requires_2fa' in result && result.requires_2fa) {
        show_two_factor_prompt(result as TwoFactorPayload, profile_name)
      } else {
        toast.success('Connection verified!')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Verification failed'
      
      // Check if the error message indicates app approval needed
      if (message.toLowerCase().includes('app_approval') || message.toLowerCase().includes('check your linkedin app')) {
        set_app_approval_pending(prev => prev && prev.started_at ? prev : { profile_id: id, profile_name, started_at: Date.now(), poll_count: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 5000 })
        return
      }
      
      toast.error(message)
    }
  }

  if (!accessToken) return null

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">LinkedIn Profiles</h1>
          <p className="text-muted-foreground">
            Manage your connected LinkedIn accounts and outreach profiles.
          </p>
        </div>
        <Button onClick={() => router.push('/profiles/new')}>
          <Plus className="mr-2 h-4 w-4" />
          Add Profile
        </Button>
      </div>

      <div className="flex items-center justify-between space-x-2">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search profiles..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8"
          />
        </div>
        <ViewToggle value={viewMode} onValueChange={handle_view_change} />
      </div>

      {/* App Approval Modal - shows when user needs to approve on LinkedIn app */}
      {app_approval_pending && (
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
                    {app_approval_pending.profile_name}
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
                const startedAt = app_approval_pending.started_at ?? appApprovalTick
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
                  if (app_approval_polling_ref.current) {
                    clearInterval(app_approval_polling_ref.current)
                    app_approval_polling_ref.current = null
                  }
                  set_app_approval_pending(null)
                }}
              >
                Cancel Verification
              </Button>
            </div>
          </div>
        </div>
      )}

      {isLoading ? (
        viewMode === 'card' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
             {[1, 2, 3].map(i => (
               <div key={i} className="h-48 bg-gray-100 rounded-lg animate-pulse"></div>
             ))}
          </div>
        ) : (
          <div className="h-48 bg-gray-100 rounded-lg animate-pulse"></div>
        )
      ) : error ? (
        <div className="text-center py-10 text-red-500">
          Failed to load profiles. Please try again.
        </div>
      ) : filteredProfiles?.length === 0 ? (
        <div className="text-center py-20 bg-gray-50 rounded-lg border border-dashed">
          <h3 className="text-lg font-medium text-gray-900">No profiles found</h3>
          <p className="text-gray-500 mt-1 mb-4">
            {searchQuery ? 'Try adjusting your search.' : 'Get started by adding your first LinkedIn profile.'}
          </p>
          {!searchQuery && (
            <Button onClick={() => router.push('/profiles/new')}>
              Add Profile
            </Button>
          )}
        </div>
      ) : viewMode === 'card' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredProfiles?.map((profile) => (
            <ProfileCard
              key={profile.id}
              profile={profile}
              onDelete={setDeleteId}
              onVerify={handleVerify}
              isVerifying={verify_profile.isPending}
              status={statuses?.[profile.id]} 
            />
          ))}
        </div>
      ) : (
        <ProfilesTable
          profiles={filteredProfiles || []}
          onDelete={setDeleteId}
          onVerify={handleVerify}
          isVerifying={verify_profile.isPending}
          statuses={statuses}
        />
      )}

      <AlertDialog open={!!deleteId} onOpenChange={(open) => !open && setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. This will permanently delete the LinkedIn profile
              and remove it from all associated campaigns.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-red-600 hover:bg-red-700">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {two_factor_state && accessToken && (
        <TwoFactorModal
          profile_id={two_factor_state.profile_id}
          profile_name={two_factor_state.profile_name}
          session_key={two_factor_state.session_key}
          expires_at={two_factor_state.expires_at}
          open={true}
          on_close={hide_two_factor_prompt}
          on_success={() => {
            refetch()
            hide_two_factor_prompt()
          }}
          client_token={accessToken}
        />
      )}
    </div>
  )
}
