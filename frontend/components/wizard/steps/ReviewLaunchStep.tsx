'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useWizard } from '@/lib/context/WizardContext'
import { useRunCampaign, useImportSearchRun, useCampaignTemplates } from '@/lib/hooks/useCampaigns'
import { useClientById } from '@/lib/hooks/useClients'
import { useOutreachProfiles } from '@/lib/hooks/useProfiles'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog'
import { campaigns_api } from '@/lib/api/campaigns'
import { AlertCircle, CheckCircle, Loader2 } from 'lucide-react'

interface ReviewLaunchStepProps {
  on_next?: () => void
  on_back: () => void
}

interface ConnectionCheckResult {
  url: string
  connected: boolean
  pending: boolean
  name?: string
  error?: string
}

export const ReviewLaunchStep: React.FC<ReviewLaunchStepProps> = () => {
  const router = useRouter()
  const { state, reset_state, set_current_step } = useWizard()
  const run_campaign = useRunCampaign(state.clientAccessToken || '')
  const import_and_run = useImportSearchRun(state.clientAccessToken || '')
  
  const { data: client } = useClientById(state.selectedClientId)
  const { data: profiles } = useOutreachProfiles(state.clientAccessToken)
  const { data: templates } = useCampaignTemplates(state.clientAccessToken)
  
  const [confirm_dialog_open, set_confirm_dialog_open] = useState(false)
  const [is_launching, set_is_launching] = useState(false)
  const [is_message_only, set_is_message_only] = useState(false)
  const [connection_results, set_connection_results] = useState<ConnectionCheckResult[]>([])
  const [is_checking_connections, set_is_checking_connections] = useState(false)
  const [connection_check_done, set_connection_check_done] = useState(false)

  const selected_profile = profiles?.find(p => p.id === state.outreachProfileId)
  const selected_template = templates?.find(t => t.id === state.campaignTemplateId)
  
  // Check if template is message-only (no connection step)
  useEffect(() => {
    const check_template_type = async () => {
      if (!state.clientAccessToken || !state.campaignTemplateId) return
      
      try {
        const steps_data = await campaigns_api.get_template_steps(
          state.campaignTemplateId,
          state.clientAccessToken
        )
        const has_connection_step = steps_data.steps.some(
          step => step.action === 'send_connection'
        )
        set_is_message_only(!has_connection_step)
      } catch {
        // Ignore errors, default to not message-only
      }
    }
    
    check_template_type()
  }, [state.campaignTemplateId, state.clientAccessToken])
  
  // Check connections when dialog opens for message-only campaigns
  const check_connections = async () => {
    if (!is_message_only || !state.clientAccessToken || !state.outreachProfileId) return
    if (connection_check_done) return
    
    set_is_checking_connections(true)
    try {
      const target_urls = state.targetProfiles.map(t => t.url)
      const result = await campaigns_api.verify_targets_connection(
        state.outreachProfileId,
        target_urls,
        state.clientAccessToken
      )
      set_connection_results(result.results)
      set_connection_check_done(true)
      
      if (!result.all_connected) {
        const not_connected = result.results.filter(r => !r.connected)
        toast.warning(`${not_connected.length} target(s) are not connected. Messages can only be sent to connections.`)
      }
    } catch (error) {
      console.error('Error checking connections:', error)
      toast.error('Failed to verify connection status')
    } finally {
      set_is_checking_connections(false)
    }
  }
  
  const unconnected_targets = connection_results.filter(r => !r.connected)
  const can_launch_message_only = !is_message_only || (connection_check_done && unconnected_targets.length === 0)

  const handle_launch = async () => {
    if (!state.clientAccessToken || !state.campaignTemplateId || !state.outreachProfileId) {
      toast.error('Missing required information')
      return
    }

    set_is_launching(true)

    try {
      if (state.importMethod === 'manual' && state.targetProfiles.length > 0) {
        const result = await run_campaign.mutateAsync({
          campaign_template_id: state.campaignTemplateId,
          outreach_profile_id: state.outreachProfileId,
          target_profiles: state.targetProfiles,
        })
        
        toast.success(result.message || 'Campaign launched successfully!')
      } else if (state.importMethod === 'search') {
        toast.error('Search import not yet fully implemented in this step. Use manual targets.')
        set_is_launching(false)
        return
      } else {
        toast.error('No targets to launch campaign with')
        set_is_launching(false)
        return
      }

      set_confirm_dialog_open(false)
      reset_state()
      
      setTimeout(() => {
        router.push('/campaigns')
      }, 1500)
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        (error instanceof Error ? error.message : 'Failed to launch campaign')
      console.error('Launch error:', message, error)
      toast.error(message)
      set_is_launching(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="text-center mb-6">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          Review Your Campaign
        </h2>
        <p className="text-gray-600">
          Please review all details before launching
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Client
              <Button
                size="sm"
                variant="outline"
                onClick={() => set_current_step(0)}
              >
                Edit
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm font-medium">{client?.email || 'Unknown'}</p>
            <p className="text-xs text-gray-600">ID: {state.selectedClientId}</p>
            {client?.is_admin && (
              <Badge variant="secondary" className="mt-2">Admin</Badge>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              LinkedIn Profile
              <Button
                size="sm"
                variant="outline"
                onClick={() => set_current_step(1)}
              >
                Edit
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm font-medium">{selected_profile?.linkedin_email || 'Unknown'}</p>
            <p className="text-xs text-gray-600 truncate">
              {selected_profile?.linkedin_url || ''}
            </p>
            {selected_profile?.gohighlevel_location_id && (
              <Badge variant="secondary" className="mt-2">GHL Connected</Badge>
            )}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Campaign Template
              <Button
                size="sm"
                variant="outline"
                onClick={() => set_current_step(2)}
              >
                Edit
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="font-medium">{selected_template?.name || 'Unknown'}</p>
              {selected_template?.description && (
                <p className="text-sm text-gray-600">{selected_template.description}</p>
              )}
            </div>
            
            <div className="flex gap-2 flex-wrap">
              <Badge variant="secondary">
                {selected_template?.number_of_steps || 0} steps
              </Badge>
              <Badge variant="outline">
                {state.requiredVariables.length} variables
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Target Contacts
              <Button
                size="sm"
                variant="outline"
                onClick={() => set_current_step(3)}
              >
                Edit
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              <div>
                <p className="text-2xl font-bold">{state.targetProfiles.length}</p>
                <p className="text-sm text-gray-600">Total Targets</p>
              </div>
              <Separator orientation="vertical" className="h-12" />
              <div>
                <p className="text-lg font-medium capitalize">{state.importMethod || 'None'}</p>
                <p className="text-sm text-gray-600">Import Method</p>
              </div>
            </div>

            {state.targetProfiles.length > 0 && (
              <div className="mt-4 bg-gray-50 p-4 rounded-lg max-h-48 overflow-y-auto">
                <p className="text-sm font-medium mb-2">Sample Targets:</p>
                <ul className="space-y-1">
                  {state.targetProfiles.slice(0, 5).map((target, index) => (
                    <li key={index} className="text-sm text-gray-600 truncate">
                      {target.url}
                    </li>
                  ))}
                  {state.targetProfiles.length > 5 && (
                    <li className="text-sm text-gray-500 italic">
                      ...and {state.targetProfiles.length - 5} more
                    </li>
                  )}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Separator />

      {/* Connection Warning for Message-Only Templates */}
      {is_message_only && (
        <Card className="border-amber-200 bg-amber-50">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2 text-amber-800">
              <AlertCircle className="h-5 w-5" />
              Message-Only Campaign
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-amber-700 mb-3">
              This template only sends messages. Targets must already be connected to receive messages.
            </p>
            
            {!connection_check_done ? (
              <Button 
                variant="outline" 
                onClick={check_connections}
                disabled={is_checking_connections}
                className="w-full"
              >
                {is_checking_connections ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Checking Connections...
                  </>
                ) : (
                  'Verify Target Connections'
                )}
              </Button>
            ) : (
              <div className="space-y-2">
                {unconnected_targets.length === 0 ? (
                  <div className="flex items-center gap-2 text-green-700">
                    <CheckCircle className="h-4 w-4" />
                    <span className="text-sm">All targets are connected!</span>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-red-700">
                      <AlertCircle className="h-4 w-4" />
                      <span className="text-sm font-medium">
                        {unconnected_targets.length} target(s) not connected:
                      </span>
                    </div>
                    <ul className="text-sm text-red-600 space-y-1 pl-6">
                      {unconnected_targets.slice(0, 5).map((t, i) => (
                        <li key={i} className="truncate">
                          {t.name || t.url} {t.pending && '(pending)'}
                        </li>
                      ))}
                      {unconnected_targets.length > 5 && (
                        <li className="text-gray-500">
                          ... and {unconnected_targets.length - 5} more
                        </li>
                      )}
                    </ul>
                    <p className="text-xs text-gray-600 mt-2">
                      Remove unconnected targets or use a template with a connection step first.
                    </p>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex justify-center">
        <Dialog open={confirm_dialog_open} onOpenChange={set_confirm_dialog_open}>
          <DialogTrigger asChild>
            <Button 
              size="lg" 
              className="px-8"
              disabled={is_message_only && !can_launch_message_only}
            >
              Launch Campaign
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Confirm Campaign Launch</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                You are about to launch a campaign with:
              </p>
              <ul className="list-disc list-inside space-y-1 text-sm">
                <li><strong>{state.targetProfiles.length}</strong> target contacts</li>
                <li><strong>{selected_template?.number_of_steps || 0}</strong> campaign steps</li>
                <li>Client: <strong>{client?.email}</strong></li>
                <li>Profile: <strong>{selected_profile?.linkedin_email}</strong></li>
              </ul>
              {is_message_only && (
                <p className="text-sm text-green-600 flex items-center gap-1">
                  <CheckCircle className="h-4 w-4" />
                  All targets verified as connected
                </p>
              )}
              <p className="text-sm text-gray-600">
                The campaign will start immediately. Are you sure?
              </p>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => set_confirm_dialog_open(false)}
                disabled={is_launching}
              >
                Cancel
              </Button>
              <Button onClick={handle_launch} disabled={is_launching}>
                {is_launching ? 'Launching...' : 'Confirm & Launch'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  )
}

