'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { CampaignHistoryResponse } from '@/types'
import { PauseIcon } from 'lucide-react'

interface CampaignCardProps {
  campaign: CampaignHistoryResponse
  on_pause?: (campaign_id: number) => void
  is_pausing?: boolean
}

export const CampaignCard: React.FC<CampaignCardProps> = ({
  campaign,
  on_pause,
  is_pausing = false,
}) => {
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

  // If campaign is completed, show all steps done; otherwise use finished_on_step_number
  const current_step = campaign.status === 'completed' 
    ? campaign.number_of_steps 
    : (campaign.finished_on_step_number || 0)
  const progress = (current_step / campaign.number_of_steps) * 100

  return (
    <Card className="hover:shadow-lg transition-shadow">
      <CardHeader>
        <div className="flex justify-between items-start">
          <CardTitle className="text-lg">Campaign #{campaign.campaign_history_id}</CardTitle>
          <Badge variant={get_status_variant(campaign.status)}>
            {campaign.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-sm text-gray-600">Runtime ID</p>
          <p className="font-mono text-xs truncate">{campaign.runtime_id}</p>
        </div>
        <div>
          <p className="text-sm text-gray-600 mb-2">Progress</p>
          <Progress value={progress} className="h-2" />
          <p className="text-xs text-gray-500 mt-1">
            Step {current_step} of {campaign.number_of_steps}
          </p>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-gray-600">Started:</span>
          <span className="font-medium">
            {new Date(campaign.started_at).toLocaleDateString()}
          </span>
        </div>
        <div className="flex gap-2">
          <Link href={`/campaigns/${campaign.campaign_history_id}`} className="flex-1">
            <Button size="sm" variant="outline" className="w-full">
              View Details
            </Button>
          </Link>
          {campaign.status === 'active' && on_pause && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => on_pause(campaign.campaign_history_id)}
              disabled={is_pausing}
            >
              <PauseIcon className="h-4 w-4 mr-1" />
              {is_pausing ? 'Pausing...' : 'Pause'}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}





