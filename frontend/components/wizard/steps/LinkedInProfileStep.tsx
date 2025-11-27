'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useWizard } from '@/lib/context/WizardContext'
import { 
  useOutreachProfiles, 
  useRegisterProfile, 
  useVerifyProfile, 
  useUpdateProfile, 
  useDeleteProfile,
  useSubmitPin,
  useProfilesStatusBulk
} from '@/lib/hooks/useProfiles'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Edit, Trash2, ExternalLink, Loader2, CheckCircle } from 'lucide-react'
import { OutreachProfile } from '@/types'
import { ViewToggle } from '@/components/ui/view-toggle'
import { get_view_preference, save_view_preference } from '@/lib/utils/view-preferences'
import { ProfileStatus, TwoFactorPayload, CheckpointActionPayload } from '@/lib/api/profiles'
import { WizardProfilesTable } from './WizardProfilesTable'
import { useTwoFactorPrompt } from '@/lib/hooks/useTwoFactorPrompt'
import { TwoFactorModal } from '@/components/forms/TwoFactorModal'
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

interface LinkedInProfileStepProps {
  on_next: () => void
  on_back: () => void
}

export const LinkedInProfileStep: React.FC<LinkedInProfileStepProps> = ({
  on_next,
}) => {
  const { state, update_state } = useWizard()
  const { data: profiles, isLoading, refetch, error } = useOutreachProfiles(state.clientAccessToken)
  const register_profile = useRegisterProfile(state.clientAccessToken || '')
  const verify_profile = useVerifyProfile(state.clientAccessToken || '')
  const update_profile = useUpdateProfile(state.clientAccessToken || '')
  const delete_profile = useDeleteProfile(state.clientAccessToken || '')
  const { two_factor_state, show_two_factor_prompt, hide_two_factor_prompt } = useTwoFactorPrompt()
  
  const profile_ids = profiles?.map(p => p.id) || []
  const { data: statuses, isLoading: statuses_loading } = useProfilesStatusBulk(state.clientAccessToken, profile_ids)
  
  const [show_form, set_show_form] = useState(false)
  const [editing_profile, set_editing_profile] = useState<OutreachProfile | null>(null)
  const [delete_id, set_delete_id] = useState<number | null>(null)
  const [view_mode, set_view_mode] = useState<'card' | 'list'>(() => get_view_preference('wizard-profiles'))
  
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

  const [account_name, set_account_name] = useState('')
  const [linkedin_email, set_linkedin_email] = useState('')
  const [linkedin_password, set_linkedin_password] = useState('')
  const [linkedin_url, set_linkedin_url] = useState('')
  const [gohighlevel_id, set_gohighlevel_id] = useState('')

  useEffect(() => {
    if (profiles && profiles.length === 0) {
      set_show_form(true)
    }
  }, [profiles])

  useEffect(() => {
    if (!state.clientAccessToken) {
      toast.error('No client access token. Please go back and select a client.')
    }
  }, [state.clientAccessToken])

  // Poll for app approval completion using the profiles API
  const poll_app_approval_status = useCallback(async () => {
    if (!state.clientAccessToken || !app_approval_pending) return
    
    try {
      // Use the profiles API to poll status - backend will check microservice
      const { profiles_api } = await import('@/lib/api/profiles')
      const data = await profiles_api.poll_app_approval_status(app_approval_pending.profile_id, state.clientAccessToken)
      
      console.log('[AppApproval] Poll result:', data)
      
      // Check if connected successfully
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
      
      // Check if still waiting for app approval
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
  }, [state.clientAccessToken, app_approval_pending, refetch])
  
  // Start/stop polling when app_approval_pending changes
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

  const resetForm = () => {
    set_account_name('')
    set_linkedin_email('')
    set_linkedin_password('')
    set_linkedin_url('')
    set_gohighlevel_id('')
    set_editing_profile(null)
    set_show_form(false)
  }

  const startEdit = (profile: OutreachProfile, e: React.MouseEvent) => {
    e.stopPropagation()
    set_editing_profile(profile)
    set_account_name(profile.account_name || '')
    set_linkedin_email(profile.linkedin_email)
    set_linkedin_password('') // Leave blank for updates
    set_linkedin_url(profile.linkedin_url)
    set_gohighlevel_id(profile.gohighlevel_location_id || '')
    set_show_form(true)
  }

  const handle_verify_profile = async (e: React.MouseEvent, profile_id: number) => {
    e.stopPropagation()
    const profile = profiles?.find(p => p.id === profile_id)
    const profile_name = profile?.account_name || profile?.linkedin_email || `Profile ${profile_id}`
    
    try {
      const result = await verify_profile.mutateAsync(profile_id)
      
      // Handle LinkedIn App Approval required (push notification 2FA)
      if ('requires_app_approval' in result && result.requires_app_approval) {
        const expires_at = (result as { expires_at?: string }).expires_at
        set_app_approval_pending(prev => prev && prev.started_at ? { ...prev, expires_at } : { profile_id, profile_name, expires_at, started_at: Date.now(), poll_count: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 5000 })
        return
      }
      
      // Handle 2FA App Approval status
      if ('status' in result && result.status === '2fa_app_approval') {
        const expires_at = (result as { expires_at?: string }).expires_at
        set_app_approval_pending(prev => prev && prev.started_at ? { ...prev, expires_at } : { profile_id, profile_name, expires_at, started_at: Date.now(), poll_count: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 5000 })
        return
      }
      
      if ('requires_manual_action' in result && result.requires_manual_action) {
        const manualResult = result as CheckpointActionPayload
        toast.warning(manualResult.message || 'LinkedIn requires additional verification. Please log in manually to continue.')
        await refetch()
        return
      }
      
      // Clear any pending app approval on success
      set_app_approval_pending(null)
      
      // Handle traditional 2FA (PIN required)
      if ('requires_2fa' in result && result.requires_2fa) {
        show_two_factor_prompt(result as TwoFactorPayload, profile_name)
      } else if ('status' in result && result.status === 'connected') {
        const msg = (result as { message?: string }).message || 'Connection verified successfully!'
        toast.success(msg)
      } else {
        toast.success('Connection verified successfully!')
      }
    } catch (err: unknown) {
      const msg = format_error_message(err)
      
      // Check if the error message indicates app approval needed
      if (msg.toLowerCase().includes('app_approval') || msg.toLowerCase().includes('check your linkedin app')) {
        set_app_approval_pending(prev => prev && prev.started_at ? prev : { profile_id, profile_name, started_at: Date.now(), poll_count: 0 })
        toast.info('Check your LinkedIn app to approve the sign-in request.', { duration: 5000 })
        return
      }
      
      toast.error(`Connection failed: ${msg}`)
    }
  }

  const handle_delete_profile = async () => {
    if (!delete_id) return
    try {
      await delete_profile.mutateAsync(delete_id)
      toast.success('Profile deleted successfully')
      if (state.outreachProfileId === delete_id) {
        update_state({ outreachProfileId: undefined })
      }
    } catch (error: unknown) {
      toast.error(format_error_message(error))
    } finally {
      set_delete_id(null)
    }
  }

  const handle_select_profile = (profile_id: number) => {
    update_state({ outreachProfileId: profile_id })
    toast.success('Profile selected')
    on_next()
  }

  const handle_view_change = (mode: 'card' | 'list') => {
    set_view_mode(mode)
    save_view_preference('wizard-profiles', mode)
  }

  const get_status_color = (status?: ProfileStatus) => {
    if (!status) return 'bg-gray-100 text-gray-600 border-gray-200'
    if (status.session_status === 'pending_approval') return 'bg-indigo-100 text-indigo-700 border-indigo-200'
    if (status.session_status === 'verifying') return 'bg-blue-100 text-blue-700 border-blue-200'
    if (status.session_status === 'manual_verification') return 'bg-amber-100 text-amber-800 border-amber-200'
    if (status.needs_attention) return 'bg-red-100 text-red-700 border-red-200'
    if (status.is_connected && status.session_status === 'active') return 'bg-green-100 text-green-700 border-green-200'
    if (status.session_status === 'missing') return 'bg-yellow-100 text-yellow-700 border-yellow-200'
    return 'bg-gray-100 text-gray-600 border-gray-200'
  }

  const get_status_label = (status?: ProfileStatus) => {
    if (!status) return 'Loading...'
    if (status.session_status === 'pending_approval') return 'Awaiting Approval'
    if (status.session_status === 'verifying') return 'Verifying...'
    if (status.session_status === 'manual_verification') return 'Manual Action Needed'
    if (status.needs_attention) return 'Needs Attention'
    if (status.is_connected && status.session_status === 'active') return 'Active'
    if (status.session_status === 'missing') return 'No Session'
    return 'Inactive'
  }
  
  const get_status_tooltip = (status?: ProfileStatus) => {
    if (!status || status.issues.length === 0) return undefined
    return status.issues[0]
  }

  const format_error_message = (error: unknown): string => {
    if (typeof error === 'string') {
      return error
    }
    
    if (error && typeof error === 'object') {
      const errObj = error as { response?: { data?: { detail?: unknown } }; message?: string }
      const detail = errObj.response?.data?.detail
      
      if (typeof detail === 'string') {
        return detail
      }
      
      if (Array.isArray(detail)) {
        return detail.map((err) => (typeof err === 'object' && err && 'msg' in err ? (err as { msg?: string }).msg : JSON.stringify(err))).join(', ')
      }
      
      if (detail && typeof detail === 'object' && 'msg' in detail) {
        return (detail as { msg?: string }).msg || JSON.stringify(detail)
      }

      if (errObj.message) {
        return errObj.message
      }
    }
    
    return 'An unexpected error occurred'
  }

  const handle_save_profile = async () => {
    if (!linkedin_email || !linkedin_url) {
      toast.error('Email and URL are required')
      return
    }

    if (!editing_profile && !linkedin_password) {
      toast.error('Password is required for new profiles')
      return
    }

    if (!state.clientAccessToken) {
      toast.error('No client token available')
      return
    }

    try {
      if (editing_profile) {
        await update_profile.mutateAsync({
          profile_id: editing_profile.id,
          data: {
            linkedin_email,
            linkedin_password: linkedin_password || undefined,
            linkedin_url,
            account_name: account_name || undefined,
            gohighlevel_location_id: gohighlevel_id || undefined,
          }
        })
        toast.success('Profile updated successfully')
      } else {
        const new_profile = await register_profile.mutateAsync({
          linkedin_email,
          linkedin_password,
          linkedin_url,
          account_name: account_name || undefined,
          gohighlevel_location_id: gohighlevel_id || undefined,
        })
        // Check if the result is a profile (has id) or a 2FA payload
        if ('id' in new_profile) {
          update_state({ outreachProfileId: new_profile.id })
        }
        toast.success('Profile created successfully')
      }

      await refetch()
      resetForm()
      if (!editing_profile) {
        on_next()
      }
    } catch (error: unknown) {
      const error_message = format_error_message(error)
      toast.error(error_message)
    }
  }

  if (!state.clientAccessToken) {
    return (
      <div className="text-center py-8">
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
          <p className="text-gray-800 font-medium mb-2">No Client Selected</p>
          <p className="text-gray-600 mb-4">
            Please go back and select a client first.
          </p>
          <Button variant="outline" onClick={() => window.history.back()}>
            Go Back
          </Button>
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="text-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
        <p className="mt-2 text-gray-600">Loading profiles...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <p className="text-gray-800 font-medium mb-2">Error Loading Profiles</p>
          <p className="text-gray-600 mb-4">
            {error instanceof Error ? error.message : 'Failed to load profiles'}
          </p>
          <Button variant="outline" onClick={() => refetch()}>
            Try Again
          </Button>
        </div>
      </div>
    )
  }

  const isSubmitting = register_profile.isPending || update_profile.isPending

  return (
    <div className="space-y-6">
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
      
      {!show_form && profiles && profiles.length > 0 && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium">Select Existing Profile</h3>
            <div className="flex items-center gap-2">
              <ViewToggle value={view_mode} onValueChange={handle_view_change} />
              <Button variant="outline" onClick={() => set_show_form(true)}>
                Add New Profile
              </Button>
            </div>
          </div>
          
          {view_mode === 'card' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {profiles.map((profile) => {
                const status = statuses?.[profile.id]
                return (
                  <Card
                    key={profile.id}
                    className={`cursor-pointer transition-all hover:shadow-lg ${
                      state.outreachProfileId === profile.id
                        ? 'ring-2 ring-blue-500'
                        : ''
                    }`}
                    onClick={() => handle_select_profile(profile.id)}
                  >
                    <CardHeader>
                      <CardTitle className="text-lg flex justify-between items-start">
                        <span className="truncate max-w-[180px]" title={profile.account_name || profile.linkedin_email}>
                          {profile.account_name || profile.linkedin_email}
                        </span>
                        <div className="flex gap-1">
                          <Button 
                            size="icon" 
                            variant="ghost" 
                            className="h-6 w-6" 
                            onClick={(e) => startEdit(profile, e)}
                            title="Edit Profile"
                          >
                            <Edit className="h-3 w-3" />
                          </Button>
                          <Button 
                            size="icon" 
                            variant="ghost" 
                            className="h-6 w-6 text-red-500 hover:text-red-700" 
                            onClick={(e) => { e.stopPropagation(); set_delete_id(profile.id); }}
                            title="Delete Profile"
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </CardTitle>
                      {profile.account_name && (
                        <p className="text-sm text-gray-600 mt-1 truncate">
                          {profile.linkedin_email}
                        </p>
                      )}
                    </CardHeader>
                    <CardContent>
                      <div className="flex items-center justify-between mb-2">
                        <Badge 
                          variant="outline" 
                          className={`${get_status_color(status)} border`}
                          title={get_status_tooltip(status)}
                        >
                          {get_status_label(status)}
                        </Badge>
                        {status?.is_verified && (
                          <Badge variant="secondary" className="text-xs">
                            Verified
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-gray-600 truncate">
                        {profile.linkedin_url}
                      </p>
                      <div className="flex gap-2 mt-2">
                        {profile.gohighlevel_location_id && (
                            <Badge variant="secondary">
                            GHL Connected
                            </Badge>
                        )}
                      </div>
                      
                      <div className="mt-4 flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => { e.stopPropagation(); window.open(`/profiles/${profile.id}`, '_blank'); }}
                          title="Manage in Dashboard"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => handle_verify_profile(e, profile.id)}
                          disabled={verify_profile.isPending}
                        >
                          {verify_profile.isPending ? 'Verifying...' : 'Verify Connection'}
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          ) : (
            <WizardProfilesTable
              profiles={profiles}
              statuses={statuses}
              selected_profile_id={state.outreachProfileId}
              on_select={handle_select_profile}
              on_edit={startEdit}
              on_delete={(id) => set_delete_id(id)}
              on_verify={handle_verify_profile}
              is_verifying={verify_profile.isPending}
              get_status_color={get_status_color}
              get_status_label={get_status_label}
              get_status_tooltip={get_status_tooltip}
            />
          )}
        </div>
      )}

      {show_form && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-lg font-medium">
              {editing_profile ? 'Edit LinkedIn Profile' : 'Add LinkedIn Profile'}
            </h3>
            <Button variant="outline" onClick={resetForm}>
              Cancel
            </Button>
          </div>

          <div className="space-y-4 border p-4 rounded-lg">
            <div>
              <Label htmlFor="account-name">Account Name (Optional)</Label>
              <Input
                id="account-name"
                type="text"
                value={account_name}
                onChange={(e) => set_account_name(e.target.value)}
                placeholder="e.g., Main Account, Personal Profile, Work Account"
                disabled={isSubmitting}
              />
            </div>

            <div>
              <Label htmlFor="linkedin-email">LinkedIn Email *</Label>
              <Input
                id="linkedin-email"
                type="email"
                value={linkedin_email}
                onChange={(e) => set_linkedin_email(e.target.value)}
                placeholder="your.email@example.com"
                disabled={isSubmitting}
              />
            </div>

            <div>
              <Label htmlFor="linkedin-password">
                LinkedIn Password {editing_profile ? '(Leave blank to keep)' : '*'}
              </Label>
              <Input
                id="linkedin-password"
                type="password"
                value={linkedin_password}
                onChange={(e) => set_linkedin_password(e.target.value)}
                placeholder="••••••••"
                disabled={isSubmitting}
              />
            </div>

            <div>
              <Label htmlFor="linkedin-url">LinkedIn Profile URL *</Label>
              <Input
                id="linkedin-url"
                type="url"
                value={linkedin_url}
                onChange={(e) => set_linkedin_url(e.target.value)}
                placeholder="https://www.linkedin.com/in/your-profile/"
                disabled={isSubmitting}
              />
            </div>

            <div>
              <Label htmlFor="gohighlevel-id">GoHighLevel Location ID (Optional)</Label>
              <Input
                id="gohighlevel-id"
                type="text"
                value={gohighlevel_id}
                onChange={(e) => set_gohighlevel_id(e.target.value)}
                placeholder="GHL Location ID"
                disabled={isSubmitting}
              />
            </div>

            <Button
              onClick={handle_save_profile}
              disabled={isSubmitting}
              className="w-full"
            >
              {isSubmitting ? 'Saving...' : (editing_profile ? 'Update Profile' : 'Create Profile')}
            </Button>
          </div>
        </div>
      )}

      {!show_form && (!profiles || profiles.length === 0) && (
        <div className="text-center py-8">
          <p className="text-gray-600 mb-4">No profiles found. Create one to continue.</p>
          <Button onClick={() => set_show_form(true)}>
            Add LinkedIn Profile
          </Button>
        </div>
      )}

      <AlertDialog open={!!delete_id} onOpenChange={(open) => !open && set_delete_id(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete this LinkedIn profile from the system.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handle_delete_profile} className="bg-red-600">Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {two_factor_state && state.clientAccessToken && (
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
          client_token={state.clientAccessToken}
        />
      )}
    </div>
  )
}
