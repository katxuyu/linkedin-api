'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { useRegisterProfile } from '@/lib/hooks/useProfiles'
import { profiles_api } from '@/lib/api/profiles'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { toast } from 'sonner'
import { ArrowLeft, Loader2, Link2, CheckCircle, ExternalLink, RefreshCw } from 'lucide-react'
import { useGHLAccounts } from '@/lib/hooks/useGHL'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export default function NewProfilePage() {
  const router = useRouter()
  const { accessToken, user } = useAuth()
  const register_profile = useRegisterProfile(accessToken || '')
  const { data: ghl_accounts, isLoading: ghl_loading, refetch: refetch_ghl } = useGHLAccounts(accessToken)
  
  const [account_name, set_account_name] = useState('')
  const [linkedin_email, set_linkedin_email] = useState('')
  const [linkedin_password, set_linkedin_password] = useState('')
  const [linkedin_url, set_linkedin_url] = useState('')
  const [gohighlevel_location_id, set_gohighlevel_location_id] = useState('')
  const [ghl_input_mode, set_ghl_input_mode] = useState<'select' | 'manual'>('select')
  const [manual_location_id, set_manual_location_id] = useState('')
  const [show_2fa_dialog, set_show_2fa_dialog] = useState(false)
  const [profile_id_for_2fa, set_profile_id_for_2fa] = useState<number | null>(null)
  const [pin_code, set_pin_code] = useState('')
  const [is_submitting_pin, set_is_submitting_pin] = useState(false)
  const [has_auto_populated, set_has_auto_populated] = useState(false)

  // Auto-populate GHL location from default account (only once)
  const default_ghl_account = ghl_accounts?.find(a => a.is_default)
  
  useEffect(() => {
    if (default_ghl_account && !has_auto_populated) {
      set_gohighlevel_location_id(default_ghl_account.location_id)
      set_has_auto_populated(true)
    }
  }, [default_ghl_account, has_auto_populated])

  // Sync manual input with location id
  useEffect(() => {
    if (ghl_input_mode === 'manual') {
      set_gohighlevel_location_id(manual_location_id)
    }
  }, [manual_location_id, ghl_input_mode])

  const validate_form = () => {
    if (!linkedin_email || !linkedin_password || !linkedin_url) {
      toast.error('Please fill in all required fields')
      return false
    }

    const url_pattern = /^https:\/\/(www\.)?linkedin\.com\/(in|company)\/[\w-]+\/?$/
    if (!url_pattern.test(linkedin_url)) {
      toast.error('Please enter a valid LinkedIn profile URL (e.g., https://www.linkedin.com/in/username)')
      return false
    }

    const email_pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!email_pattern.test(linkedin_email)) {
      toast.error('Please enter a valid email address')
      return false
    }

    return true
  }

  const handle_submit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (!validate_form()) {
      return
    }

    try {
      const result = await register_profile.mutateAsync({
        linkedin_email,
        linkedin_password,
        linkedin_url,
        account_name: account_name || null,
        gohighlevel_location_id: gohighlevel_location_id || null,
      })
      
      if (result && typeof result === 'object' && 'requires_2fa' in result && result.requires_2fa) {
        set_profile_id_for_2fa((result as { requires_2fa: true; profile_id: number }).profile_id)
        set_show_2fa_dialog(true)
        toast.info('LinkedIn requires 2FA verification. Please enter your verification code.')
      } else {
        toast.success('LinkedIn profile registered and verified successfully')
        router.push('/profiles')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string }; status?: number } }
      const message = err.response?.data?.detail || (error instanceof Error ? error.message : 'Failed to register profile')
      const status = err.response?.status
      
      // Handle "already registered" error with better UX
      if (status === 403 || status === 409 || message.toLowerCase().includes('already registered')) {
        toast.error('This LinkedIn profile is already registered. Go to Profiles to manage existing profiles.', {
          duration: 8000,
        })
      } else {
        toast.error(message)
      }
    }
  }

  const handle_submit_pin = async () => {
    if (!pin_code.trim() || !profile_id_for_2fa || !accessToken) {
      toast.error('Please enter a verification code')
      return
    }

    set_is_submitting_pin(true)
    try {
      await profiles_api.submit_pin_verification(profile_id_for_2fa, pin_code.trim(), accessToken)
      
      const verify_result = await profiles_api.verify_profile_connection(profile_id_for_2fa, accessToken)
      
      if ('requires_2fa' in verify_result && verify_result.requires_2fa) {
        toast.error('Verification still required. Please try again.')
        set_pin_code('')
      } else {
        toast.success('LinkedIn profile registered and verified successfully')
        set_show_2fa_dialog(false)
        set_pin_code('')
        set_profile_id_for_2fa(null)
        router.push('/profiles')
      }
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        (error instanceof Error ? error.message : 'Failed to verify PIN')
      toast.error(message)
    } finally {
      set_is_submitting_pin(false)
    }
  }

  if (!accessToken) {
    return (
      <div className="container mx-auto py-6">
        <p className="text-red-500">Please log in to add a profile</p>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 max-w-2xl">
      <div className="mb-6">
        <Button
          variant="ghost"
          onClick={() => router.push('/profiles')}
          className="mb-4"
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Profiles
        </Button>
        <h1 className="text-3xl font-bold tracking-tight">Add LinkedIn Profile</h1>
        <p className="text-muted-foreground mt-2">
          Register a new LinkedIn account for outreach campaigns
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Profile Information</CardTitle>
          <CardDescription>
            Enter the credentials for your LinkedIn account
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handle_submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="account_name">
                Account Name <span className="text-muted-foreground">(Optional)</span>
              </Label>
              <Input
                id="account_name"
                type="text"
                placeholder="e.g., John's LinkedIn"
                value={account_name}
                onChange={(e) => set_account_name(e.target.value)}
                disabled={register_profile.isPending}
              />
              <p className="text-xs text-muted-foreground">
                A friendly name to identify this account
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="linkedin_email">
                LinkedIn Email <span className="text-red-500">*</span>
              </Label>
              <Input
                id="linkedin_email"
                type="email"
                placeholder="your.email@example.com"
                value={linkedin_email}
                onChange={(e) => set_linkedin_email(e.target.value)}
                required
                disabled={register_profile.isPending}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="linkedin_password">
                LinkedIn Password <span className="text-red-500">*</span>
              </Label>
              <Input
                id="linkedin_password"
                type="password"
                placeholder="••••••••"
                value={linkedin_password}
                onChange={(e) => set_linkedin_password(e.target.value)}
                required
                disabled={register_profile.isPending}
              />
              <p className="text-xs text-muted-foreground">
                Your password is encrypted and stored securely
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="linkedin_url">
                LinkedIn Profile URL <span className="text-red-500">*</span>
              </Label>
              <Input
                id="linkedin_url"
                type="url"
                placeholder="https://www.linkedin.com/in/username"
                value={linkedin_url}
                onChange={(e) => set_linkedin_url(e.target.value)}
                required
                disabled={register_profile.isPending}
              />
              <p className="text-xs text-muted-foreground">
                Your full LinkedIn profile URL
              </p>
            </div>

            {/* GHL Location Selection */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>
                  GoHighLevel Location <span className="text-muted-foreground">(Optional)</span>
                </Label>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant={ghl_input_mode === 'select' ? 'secondary' : 'ghost'}
                    size="sm"
                    onClick={() => set_ghl_input_mode('select')}
                    className="h-6 px-2 text-xs"
                  >
                    Select
                  </Button>
                  <Button
                    type="button"
                    variant={ghl_input_mode === 'manual' ? 'secondary' : 'ghost'}
                    size="sm"
                    onClick={() => set_ghl_input_mode('manual')}
                    className="h-6 px-2 text-xs"
                  >
                    Manual
                  </Button>
                  {ghl_input_mode === 'select' && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => refetch_ghl()}
                      disabled={ghl_loading}
                      className="h-6 px-2"
                    >
                      <RefreshCw className={`h-3 w-3 ${ghl_loading ? 'animate-spin' : ''}`} />
                    </Button>
                  )}
                </div>
              </div>
              
              {ghl_input_mode === 'manual' ? (
                <div className="space-y-2">
                  <Input
                    type="text"
                    placeholder="Enter GHL Location ID manually"
                    value={manual_location_id}
                    onChange={(e) => set_manual_location_id(e.target.value)}
                    disabled={register_profile.isPending}
                  />
                  <p className="text-xs text-muted-foreground">
                    Enter your GoHighLevel Location ID (e.g., abc123XYZ...)
                  </p>
                </div>
              ) : ghl_loading ? (
                <div className="flex items-center gap-2 text-muted-foreground text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading GHL accounts...
                </div>
              ) : ghl_accounts && ghl_accounts.length > 0 ? (
                <div className="flex gap-2">
                  <Select
                    value={gohighlevel_location_id || 'none'}
                    onValueChange={(value) => set_gohighlevel_location_id(value === 'none' ? '' : value)}
                    disabled={register_profile.isPending}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue placeholder="Select GHL Location" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None (No GHL sync)</SelectItem>
                      {ghl_accounts.map((account) => {
                        const label = account.display_name || account.location_id
                        const suffix = account.is_default ? ' (Default)' : ''
                        return (
                          <SelectItem key={account.id} value={account.location_id}>
                            {label}{suffix}
                          </SelectItem>
                        )
                      })}
                    </SelectContent>
                  </Select>
                  {user?.is_admin && (
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      onClick={() => router.push('/settings/ghl')}
                      title="Connect new GHL account"
                      disabled={register_profile.isPending}
                    >
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-md">
                    <Link2 className="h-4 w-4 text-amber-600" />
                    <div className="flex-1">
                      <p className="text-sm text-amber-800">No GHL account connected</p>
                      <p className="text-xs text-amber-700">
                        Use Manual mode to enter a Location ID, or connect an account
                      </p>
                    </div>
                  </div>
                  {user?.is_admin && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => router.push('/settings/ghl')}
                      className="w-full"
                      disabled={register_profile.isPending}
                    >
                      <Link2 className="h-4 w-4 mr-2" />
                      Connect GoHighLevel Account
                    </Button>
                  )}
                </div>
              )}
              
              {gohighlevel_location_id && (
                <div className="flex items-center gap-2 p-2 bg-green-50 border border-green-200 rounded-md">
                  <CheckCircle className="h-4 w-4 text-green-600" />
                  <span className="text-xs text-green-700 font-mono">{gohighlevel_location_id}</span>
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                Link this profile to a GoHighLevel location for contact sync
              </p>
            </div>

            <div className="flex gap-3 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => router.push('/profiles')}
                disabled={register_profile.isPending}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={register_profile.isPending}
                className="flex-1"
              >
                {register_profile.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Registering...
                  </>
                ) : (
                  'Register Profile'
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h3 className="font-semibold text-blue-900 mb-2">Important Notes</h3>
        <ul className="text-sm text-blue-800 space-y-1 list-disc list-inside">
          <li>Your profile will be automatically verified when added</li>
          <li>If 2FA is enabled, you&apos;ll be prompted to enter a verification code</li>
          <li>Your credentials are encrypted and stored securely</li>
          <li>This account will be used for automated outreach campaigns</li>
        </ul>
      </div>

      <Dialog open={show_2fa_dialog} onOpenChange={set_show_2fa_dialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>LinkedIn 2FA Verification Required</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="bg-blue-50 p-4 rounded-lg">
              <p className="text-sm text-blue-900">
                LinkedIn requires two-factor authentication. Please check your email or phone for the verification code.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="pin-code">Verification Code</Label>
              <Input
                id="pin-code"
                type="text"
                value={pin_code}
                onChange={(e) => set_pin_code(e.target.value)}
                placeholder="Enter verification code"
                disabled={is_submitting_pin}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handle_submit_pin()
                  }
                }}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                set_show_2fa_dialog(false)
                set_pin_code('')
                set_profile_id_for_2fa(null)
              }}
              disabled={is_submitting_pin}
            >
              Cancel
            </Button>
            <Button
              onClick={handle_submit_pin}
              disabled={is_submitting_pin || !pin_code.trim()}
            >
              {is_submitting_pin ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Verifying...
                </>
              ) : (
                'Verify'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
