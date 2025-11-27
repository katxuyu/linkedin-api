'use client'

import React from 'react'
import { useRouter } from 'next/navigation'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { CampaignHistoryResponse } from '@/types'
import { PauseIcon } from 'lucide-react'

interface CampaignsTableProps {
  campaigns: CampaignHistoryResponse[]
  on_pause?: (campaign_id: number) => void
  pausing_campaign_id?: number | null
}

export const CampaignsTable: React.FC<CampaignsTableProps> = ({
  campaigns,
  on_pause,
  pausing_campaign_id = null,
}) => {
  const router = useRouter()

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

  return (
    <div className="border rounded-lg">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Campaign ID</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Progress</TableHead>
            <TableHead>Step</TableHead>
            <TableHead>Started</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {campaigns.map((campaign) => {
            // If campaign is completed, show all steps done
            const current_step = campaign.status === 'completed' 
              ? campaign.number_of_steps 
              : (campaign.finished_on_step_number || 0)
            const progress = (current_step / campaign.number_of_steps) * 100
            
            return (
              <TableRow
                key={campaign.campaign_history_id}
                className="cursor-pointer hover:bg-gray-50"
                onClick={() => router.push(`/campaigns/${campaign.campaign_history_id}`)}
              >
                <TableCell className="font-medium font-mono text-sm">
                  #{campaign.campaign_history_id}
                </TableCell>
                <TableCell>
                  <Badge variant={get_status_variant(campaign.status)}>
                    {campaign.status}
                  </Badge>
                </TableCell>
                <TableCell className="w-[200px]">
                  <div className="space-y-1">
                    <Progress value={progress} className="h-2" />
                  </div>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {current_step} / {campaign.number_of_steps}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {new Date(campaign.started_at).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => router.push(`/campaigns/${campaign.campaign_history_id}`)}
                    >
                      View Details
                    </Button>
                    {campaign.status === 'active' && on_pause && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => on_pause(campaign.campaign_history_id)}
                        disabled={pausing_campaign_id === campaign.campaign_history_id}
                      >
                        <PauseIcon className="h-4 w-4 mr-1" />
                        {pausing_campaign_id === campaign.campaign_history_id ? 'Pausing...' : 'Pause'}
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

