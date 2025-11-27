'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { CampaignCard } from '@/components/dashboard/CampaignCard'
import { CampaignsTable } from '@/components/dashboard/CampaignsTable'
import { ViewToggle } from '@/components/ui/view-toggle'
import { get_view_preference, save_view_preference } from '@/lib/utils/view-preferences'
import { CampaignHistoryResponse } from '@/types'
import { useAuth } from '@/lib/context/AuthContext'
import { campaigns_api } from '@/lib/api/campaigns'
import { toast } from 'sonner'
import { AxiosError } from 'axios'

export default function CampaignsPage() {
  const [search_query, set_search_query] = useState('')
  const [filter_status, set_filter_status] = useState<string>('all')
  const [viewMode, setViewMode] = useState<'card' | 'list'>('card')
  const [pausing_campaign_id, set_pausing_campaign_id] = useState<number | null>(null)
  const [campaigns, set_campaigns] = useState<CampaignHistoryResponse[]>([])
  const [loading, set_loading] = useState(true)
  const [error, set_error] = useState<string | null>(null)
  const { accessToken } = useAuth()

  useEffect(() => {
    setViewMode(get_view_preference('campaigns'))
  }, [])

  const fetch_campaigns = async () => {
    if (!accessToken) {
      return
    }

    try {
      set_loading(true)
      set_error(null)
      const status = filter_status === 'all' ? undefined : filter_status
      const data = await campaigns_api.list_campaigns(accessToken, status)
      set_campaigns(data)
    } catch (error: unknown) {
      const axios_error = error as AxiosError<{ detail?: string }>
      const error_message = axios_error.response?.data?.detail || axios_error.message || 'Failed to load campaigns'
      console.error('Fetch campaigns error:', error_message, axios_error)
      set_error(error_message)
      toast.error(error_message)
    } finally {
      set_loading(false)
    }
  }

  useEffect(() => {
    fetch_campaigns()
  }, [accessToken, filter_status])

  useEffect(() => {
    const has_active_campaigns = campaigns.some(c => c.status === 'active')
    
    if (!has_active_campaigns || !accessToken) {
      return
    }

    const poll_interval = setInterval(() => {
      fetch_campaigns()
    }, 10000)

    return () => clearInterval(poll_interval)
  }, [campaigns, accessToken])

  const handle_view_change = (mode: 'card' | 'list') => {
    setViewMode(mode)
    save_view_preference('campaigns', mode)
  }

  const filtered_campaigns = campaigns.filter(campaign => {
    if (search_query === '') return true
    
    const search_lower = search_query.toLowerCase()
    return (
      campaign.campaign_history_id.toString().includes(search_query) ||
      campaign.runtime_id.toLowerCase().includes(search_lower) ||
      (campaign.target_profile_url && campaign.target_profile_url.toLowerCase().includes(search_lower)) ||
      (campaign.outreach_profile_email && campaign.outreach_profile_email.toLowerCase().includes(search_lower)) ||
      (campaign.template_name && campaign.template_name.toLowerCase().includes(search_lower))
    )
  })

  const handle_pause = async (campaign_id: number) => {
    if (!accessToken) {
      toast.error('Authentication required')
      return
    }

    set_pausing_campaign_id(campaign_id)

    try {
      const result = await campaigns_api.pause_campaign(campaign_id, accessToken)
      toast.success(result.message || 'Campaign paused successfully')
      
      await fetch_campaigns()
    } catch (error: unknown) {
      const axios_error = error as AxiosError<{ detail?: string }>
      const error_message = axios_error.response?.data?.detail || axios_error.message || 'Failed to pause campaign'
      console.error('Pause campaign error:', error_message, axios_error)
      toast.error(error_message)
    } finally {
      set_pausing_campaign_id(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Campaigns</h1>
          <p className="text-gray-600 mt-1">
            Manage your LinkedIn outreach campaigns
          </p>
        </div>
        <Link href="/campaigns/new">
          <Button size="lg">Create New Campaign</Button>
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle>Filters</CardTitle>
            <ViewToggle value={viewMode} onValueChange={handle_view_change} />
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Input
                placeholder="Search campaigns..."
                value={search_query}
                onChange={(e) => set_search_query(e.target.value)}
              />
            </div>
            <div>
              <select
                className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white"
                value={filter_status}
                onChange={(e) => set_filter_status(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="active">Active</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="paused">Paused</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <div className="text-center py-20">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900"></div>
          <p className="text-gray-600 mt-4">Loading campaigns...</p>
        </div>
      ) : error ? (
        <div className="text-center py-20 bg-red-50 rounded-lg border border-red-200">
          <h3 className="text-lg font-medium text-red-900">Error Loading Campaigns</h3>
          <p className="text-red-600 mt-1 mb-4">{error}</p>
          <Button onClick={fetch_campaigns}>Retry</Button>
        </div>
      ) : filtered_campaigns.length === 0 ? (
        <div className="text-center py-20 bg-gray-50 rounded-lg border border-dashed">
          <h3 className="text-lg font-medium text-gray-900">No campaigns found</h3>
          <p className="text-gray-500 mt-1 mb-4">
            {search_query || filter_status !== 'all' 
              ? 'Try adjusting your filters.' 
              : 'Get started by creating your first campaign.'}
          </p>
          {!search_query && filter_status === 'all' && (
            <Link href="/campaigns/new">
              <Button>Create Your First Campaign</Button>
            </Link>
          )}
        </div>
      ) : viewMode === 'card' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered_campaigns.map((campaign) => (
            <CampaignCard
              key={campaign.campaign_history_id}
              campaign={campaign}
              on_pause={handle_pause}
              is_pausing={pausing_campaign_id === campaign.campaign_history_id}
            />
          ))}
        </div>
      ) : (
        <CampaignsTable
          campaigns={filtered_campaigns}
          on_pause={handle_pause}
          pausing_campaign_id={pausing_campaign_id}
        />
      )}
    </div>
  )
}




