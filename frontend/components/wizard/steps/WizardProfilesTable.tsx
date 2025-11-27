'use client'

import React from 'react'
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
import { Edit, Trash2, ExternalLink, RefreshCw } from 'lucide-react'
import { OutreachProfile } from '@/types'
import { ProfileStatus } from '@/lib/api/profiles'

interface WizardProfilesTableProps {
  profiles: OutreachProfile[]
  statuses?: Record<number, ProfileStatus>
  selected_profile_id?: number | null
  on_select: (profile_id: number) => void
  on_edit: (profile: OutreachProfile, e: React.MouseEvent) => void
  on_delete: (id: number) => void
  on_verify: (e: React.MouseEvent, profile_id: number) => void
  is_verifying: boolean
  get_status_color: (status?: ProfileStatus) => string
  get_status_label: (status?: ProfileStatus) => string
  get_status_tooltip: (status?: ProfileStatus) => string | undefined
}

export const WizardProfilesTable: React.FC<WizardProfilesTableProps> = ({
  profiles,
  statuses,
  selected_profile_id,
  on_select,
  on_edit,
  on_delete,
  on_verify,
  is_verifying,
  get_status_color,
  get_status_label,
  get_status_tooltip,
}) => {
  return (
    <div className="border rounded-lg">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Account</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {profiles.map((profile) => {
            const status = statuses?.[profile.id]
            const is_selected = selected_profile_id === profile.id
            
            return (
              <TableRow
                key={profile.id}
                className={`cursor-pointer hover:bg-gray-50 ${
                  is_selected ? 'bg-blue-50' : ''
                }`}
                onClick={() => on_select(profile.id)}
              >
                <TableCell className="font-medium">
                  {profile.account_name || profile.linkedin_email}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {profile.account_name ? profile.linkedin_email : '-'}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
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
                </TableCell>
                <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0"
                      onClick={(e) => on_edit(profile, e)}
                      title="Edit Profile"
                    >
                      <Edit className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0"
                      onClick={(e) => on_verify(e, profile.id)}
                      disabled={is_verifying}
                      title="Verify Connection"
                    >
                      <RefreshCw className={`h-4 w-4 ${is_verifying ? 'animate-spin' : ''}`} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0"
                      onClick={(e) => { e.stopPropagation(); window.open(`/profiles/${profile.id}`, '_blank'); }}
                      title="Manage in Dashboard"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0 text-red-500 hover:text-red-700"
                      onClick={(e) => { e.stopPropagation(); on_delete(profile.id); }}
                      title="Delete Profile"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
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

