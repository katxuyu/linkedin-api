'use client'

import React, { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Campaign } from '@/types'

interface CampaignEditorProps {
  campaign: Campaign
  on_save?: (updates: Partial<Campaign>) => void
}

export const CampaignEditor: React.FC<CampaignEditorProps> = ({
  campaign,
  on_save,
}) => {
  const [is_editing, set_is_editing] = useState(false)
  const [expanded_sections, set_expanded_sections] = useState<string[]>(['info'])

  const toggle_section = (section: string) => {
    if (expanded_sections.includes(section)) {
      set_expanded_sections(expanded_sections.filter(s => s !== section))
    } else {
      set_expanded_sections([...expanded_sections, section])
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          className="cursor-pointer hover:bg-gray-50"
          onClick={() => toggle_section('info')}
        >
          <CardTitle className="flex justify-between items-center">
            Campaign Information
            <span>{expanded_sections.includes('info') ? '−' : '+'}</span>
          </CardTitle>
        </CardHeader>
        {expanded_sections.includes('info') && (
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-gray-600">Campaign ID</p>
                <p className="font-medium">{campaign.campaign_history_id}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Runtime ID</p>
                <p className="font-mono text-sm">{campaign.runtime_id}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Status</p>
                <p className="font-medium capitalize">{campaign.status}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Total Steps</p>
                <p className="font-medium">{campaign.total_steps}</p>
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader
          className="cursor-pointer hover:bg-gray-50"
          onClick={() => toggle_section('progress')}
        >
          <CardTitle className="flex justify-between items-center">
            Campaign Progress
            <span>{expanded_sections.includes('progress') ? '−' : '+'}</span>
          </CardTitle>
        </CardHeader>
        {expanded_sections.includes('progress') && (
          <CardContent>
            <p className="text-sm text-gray-600">
              Currently on step {campaign.latest_step} of {campaign.total_steps}
            </p>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader
          className="cursor-pointer hover:bg-gray-50"
          onClick={() => toggle_section('details')}
        >
          <CardTitle className="flex justify-between items-center">
            Additional Details
            <span>{expanded_sections.includes('details') ? '−' : '+'}</span>
          </CardTitle>
        </CardHeader>
        {expanded_sections.includes('details') && (
          <CardContent>
            <pre className="text-xs bg-gray-50 p-4 rounded-lg overflow-x-auto">
              {JSON.stringify(campaign.details, null, 2)}
            </pre>
          </CardContent>
        )}
      </Card>

      {is_editing && on_save && (
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => set_is_editing(false)}>
            Cancel
          </Button>
          <Button onClick={() => on_save({})}>
            Save Changes
          </Button>
        </div>
      )}
    </div>
  )
}





