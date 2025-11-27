'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/lib/context/AuthContext'
import { campaigns_api } from '@/lib/api/campaigns'
import { toast } from 'sonner'
import { PauseIcon } from 'lucide-react'
import { CampaignDetailResponse, ScheduledTask } from '@/types'
import { AxiosError } from 'axios'

export default function CampaignDetailsPage() {
  const params = useParams()
  const campaign_id = params.id
  const { accessToken } = useAuth()
  const [is_pausing, set_is_pausing] = useState(false)
  const [campaign, set_campaign] = useState<CampaignDetailResponse | null>(null)
  const [scheduled_tasks, set_scheduled_tasks] = useState<ScheduledTask[]>([])
  const [loading, set_loading] = useState(true)
  const [error, set_error] = useState<string | null>(null)

  const fetch_campaign_data = async () => {
    if (!accessToken || !campaign_id) {
      return
    }

    const campaign_id_num = parseInt(campaign_id as string, 10)
    if (isNaN(campaign_id_num)) {
      set_error('Invalid campaign ID')
      set_loading(false)
      return
    }

    try {
      set_loading(true)
      set_error(null)
      
      const [campaign_data, tasks_data] = await Promise.all([
        campaigns_api.get_campaign_detail(campaign_id_num, accessToken),
        campaigns_api.get_scheduled_tasks(campaign_id_num, accessToken)
      ])
      
      set_campaign(campaign_data)
      set_scheduled_tasks(tasks_data)
    } catch (error: unknown) {
      const axios_error = error as AxiosError<{ detail?: string }>
      const error_message = axios_error.response?.data?.detail || axios_error.message || 'Failed to load campaign details'
      console.error('Fetch campaign error:', error_message, axios_error)
      set_error(error_message)
      toast.error(error_message)
    } finally {
      set_loading(false)
    }
  }

  useEffect(() => {
    fetch_campaign_data()
  }, [accessToken, campaign_id])

  const handle_pause = async () => {
    if (!accessToken || !campaign) {
      toast.error('Authentication required')
      return
    }

    const campaign_id_num = parseInt(campaign_id as string, 10)
    if (isNaN(campaign_id_num)) {
      toast.error('Invalid campaign ID')
      return
    }

    set_is_pausing(true)

    try {
      const result = await campaigns_api.pause_campaign(campaign_id_num, accessToken)
      toast.success(result.message || 'Campaign paused successfully')
      await fetch_campaign_data()
    } catch (error: unknown) {
      const axios_error = error as AxiosError<{ detail?: string }>
      const error_message = axios_error.response?.data?.detail || axios_error.message || 'Failed to pause campaign'
      console.error('Pause campaign error:', error_message, axios_error)
      toast.error(error_message)
    } finally {
      set_is_pausing(false)
    }
  }

  const get_status_variant = (status: string) => {
    switch (status) {
      case 'active':
        return 'default'
      case 'completed':
        return 'secondary'
      case 'failed':
        return 'destructive'
      case 'cancelled':
        return 'outline'
      case 'paused':
        return 'outline'
      default:
        return 'secondary'
    }
  }

  if (loading) {
    return (
      <div className="text-center py-20">
        <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900"></div>
        <p className="text-gray-600 mt-4">Loading campaign details...</p>
      </div>
    )
  }

  if (error || !campaign) {
    return (
      <div className="text-center py-20 bg-red-50 rounded-lg border border-red-200">
        <h3 className="text-lg font-medium text-red-900">Error Loading Campaign</h3>
        <p className="text-red-600 mt-1 mb-4">{error || 'Campaign not found'}</p>
        <div className="flex gap-2 justify-center">
          <Link href="/campaigns">
            <Button variant="outline">Back to Campaigns</Button>
          </Link>
          <Button onClick={fetch_campaign_data}>Retry</Button>
        </div>
      </div>
    )
  }

  // Calculate completed steps from step_histories
  const completed_steps = campaign.step_histories
    ? [...new Set(
        campaign.step_histories
          .filter(step => step.status === 'success' || step.status === 'completed')
          .map(step => step.step_number)
      )].length
    : 0
  // If campaign is completed, show all steps; otherwise use calculated completed steps
  const current_step = campaign.status === 'completed' 
    ? campaign.number_of_steps 
    : (campaign.finished_on_step_number || completed_steps)
  const progress = (current_step / campaign.number_of_steps) * 100
  
  // Find active watcher for this campaign
  const active_watcher = scheduled_tasks.find(
    task => task.task_name === 'incoming_message_watcher' && 
    (task.status === 'scheduled' || task.status === 'executing')
  )
  
  // Calculate watcher remaining time
  const get_watcher_remaining_time = () => {
    if (!active_watcher?.details) return null
    const max_wait = (active_watcher.details as Record<string, unknown>).max_wait_seconds as number
    const started_at = new Date(active_watcher.scheduled_at).getTime()
    const now = Date.now()
    const elapsed = (now - started_at) / 1000
    const remaining = Math.max(0, max_wait - elapsed)
    
    if (remaining <= 0) return null
    
    const days = Math.floor(remaining / 86400)
    const hours = Math.floor((remaining % 86400) / 3600)
    const minutes = Math.floor((remaining % 3600) / 60)
    
    if (days > 0) return `${days}d ${hours}h remaining`
    if (hours > 0) return `${hours}h ${minutes}m remaining`
    return `${minutes}m remaining`
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <Link href="/campaigns">
            <Button variant="ghost" size="sm" className="mb-2">
              ← Back to Campaigns
            </Button>
          </Link>
          <h1 className="text-3xl font-bold text-gray-900">
            Campaign #{campaign.campaign_history_id}
          </h1>
          <p className="text-gray-600 mt-1">View and manage campaign details</p>
        </div>
        <div className="flex gap-2">
          {campaign.status === 'active' && (
            <Button 
              variant="outline" 
              onClick={handle_pause}
              disabled={is_pausing}
            >
              <PauseIcon className="h-4 w-4 mr-1" />
              {is_pausing ? 'Pausing...' : 'Pause Campaign'}
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Status</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant={get_status_variant(campaign.status)} className="text-lg py-1 px-3">
              {campaign.status}
            </Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Progress</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Progress value={progress} className="h-2" />
              <p className="text-sm text-gray-600">Step {current_step} of {campaign.number_of_steps}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Target Profile</CardTitle>
          </CardHeader>
          <CardContent>
            {campaign.target_profile_url ? (
              <a 
                href={campaign.target_profile_url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline text-sm truncate block"
              >
                {campaign.target_profile_url}
              </a>
            ) : (
              <p className="text-sm text-gray-600">No URL</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Campaign Information</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-gray-600">Runtime ID</p>
              <p className="font-mono text-sm">{campaign.runtime_id}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600">Outreach Profile</p>
              <p className="font-medium">{campaign.outreach_profile_email || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600">Template</p>
              <p className="font-medium">{campaign.template_name || 'N/A'}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600">Target Responded</p>
              <p className="font-medium">{campaign.target_profile_responded ? 'Yes' : 'No'}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600">Started At</p>
              <p className="font-medium">{new Date(campaign.started_at).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600">Last Modified</p>
              <p className="font-medium">{new Date(campaign.modified_at).toLocaleString()}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Response Watcher / n8n Status Card */}
      <Card className={active_watcher ? 'border-blue-200 bg-blue-50/30' : ''}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>Response Watcher</span>
            {active_watcher && (
              <Badge variant="outline" className="bg-blue-100 text-blue-700 border-blue-300">
                Active
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {active_watcher ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                <span className="text-sm font-medium text-blue-700">Monitoring for response</span>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-gray-600">Status</p>
                  <Badge variant="outline" className="bg-yellow-100 text-yellow-800 border-yellow-300">
                    Waiting for Reply
                  </Badge>
                </div>
                <div>
                  <p className="text-gray-600">Time Remaining</p>
                  <p className="font-medium text-blue-600">{get_watcher_remaining_time() || 'Calculating...'}</p>
                </div>
                <div>
                  <p className="text-gray-600">n8n Webhook</p>
                  <p className="font-medium">Will trigger on response</p>
                </div>
                <div>
                  <p className="text-gray-600">Started</p>
                  <p className="font-medium">{new Date(active_watcher.scheduled_at).toLocaleString()}</p>
                </div>
              </div>
            </div>
          ) : campaign.target_profile_responded ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-green-500 rounded-full" />
                <span className="text-sm font-medium text-green-700">Response received!</span>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-gray-600">Status</p>
                  <Badge variant="outline" className="bg-green-100 text-green-800 border-green-300">
                    Completed
                  </Badge>
                </div>
                <div>
                  <p className="text-gray-600">n8n Webhook</p>
                  <Badge variant="outline" className="bg-green-100 text-green-800 border-green-300">
                    Sent Successfully
                  </Badge>
                </div>
              </div>
            </div>
          ) : campaign.status === 'completed' ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full" />
                <span className="text-sm text-gray-600">No active watcher</span>
              </div>
              <p className="text-sm text-gray-500">
                Campaign completed. Watcher may have expired or no response was received.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full" />
                <span className="text-sm text-gray-600">No watcher active</span>
              </div>
              <p className="text-sm text-gray-500">
                A response watcher will be created after the message is sent.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Campaign Steps</CardTitle>
        </CardHeader>
        <CardContent>
          {campaign.step_histories && campaign.step_histories.length > 0 ? (
            <div className="space-y-4">
              {campaign.step_histories.map((step) => {
                const step_status_bg = 
                  step.status === 'completed' ? 'bg-green-50' :
                  step.status === 'failed' ? 'bg-red-50' :
                  step.status === 'pending' ? 'bg-gray-50' :
                  'bg-blue-50'
                
                const step_status_variant = 
                  step.status === 'completed' ? 'secondary' :
                  step.status === 'failed' ? 'destructive' :
                  step.status === 'pending' ? 'outline' :
                  'default'

                return (
                  <div key={step.id} className={`flex items-start gap-4 p-4 rounded-lg ${step_status_bg}`}>
                    <Badge variant="outline">Step {step.step_number}</Badge>
                    <div className="flex-1">
                      <p className="font-medium">{step.action}</p>
                      <p className="text-sm text-gray-600">
                        {new Date(step.modified_at).toLocaleString()}
                      </p>
                      {step.details && Object.keys(step.details).length > 0 && (
                        <p className="text-xs text-gray-500 mt-1">
                          {JSON.stringify(step.details, null, 2)}
                        </p>
                      )}
                    </div>
                    <Badge variant={step_status_variant}>{step.status}</Badge>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-gray-600 text-center py-8">No step history available</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scheduled Tasks</CardTitle>
        </CardHeader>
        <CardContent>
          {scheduled_tasks.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Task Name</TableHead>
                  <TableHead>Step</TableHead>
                  <TableHead>Scheduled At</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {scheduled_tasks.map((task) => (
                  <TableRow key={task.id}>
                    <TableCell className="font-mono text-xs">{task.task_name}</TableCell>
                    <TableCell>Step {task.step_number}</TableCell>
                    <TableCell>{new Date(task.scheduled_at).toLocaleString()}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{task.status}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-gray-600 text-center py-8">No scheduled tasks</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}




