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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { MoreHorizontal, Edit, Trash2, RefreshCw, ExternalLink, Activity } from 'lucide-react'
import { OutreachProfile } from '@/types'
import { ProfileStatus } from '@/lib/api/profiles'

interface ProfilesTableProps {
  profiles: OutreachProfile[]
  onDelete: (id: number) => void
  onVerify: (id: number) => void
  isVerifying: boolean
  statuses?: Record<number, ProfileStatus>
  stats?: Record<number, {
    active_campaigns: number
    total_connections: number
  }>
}

export const ProfilesTable: React.FC<ProfilesTableProps> = ({
  profiles,
  onDelete,
  onVerify,
  isVerifying,
  statuses,
  stats
}) => {
  const router = useRouter()

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

  return (
    <div className="border rounded-lg">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Account</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-center">GHL</TableHead>
            <TableHead className="text-center">Active Campaigns</TableHead>
            <TableHead className="text-center">Connections</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {profiles.map((profile) => {
            const status = statuses?.[profile.id]
            const profile_stats = stats?.[profile.id]
            
            return (
              <TableRow
                key={profile.id}
                className="cursor-pointer hover:bg-gray-50"
                onClick={() => router.push(`/profiles/${profile.id}`)}
              >
                <TableCell className="font-medium">
                  {profile.account_name || 'N/A'}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {profile.linkedin_email}
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
                <TableCell className="text-center">
                  {profile.gohighlevel_location_id ? (
                    <Activity className="h-4 w-4 inline text-green-600" />
                  ) : (
                    <span className="text-muted-foreground text-xs">-</span>
                  )}
                </TableCell>
                <TableCell className="text-center">
                  {profile_stats?.active_campaigns ?? '-'}
                </TableCell>
                <TableCell className="text-center">
                  {profile_stats?.total_connections ?? '-'}
                </TableCell>
                <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" className="h-8 w-8 p-0">
                        <span className="sr-only">Open menu</span>
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuLabel>Actions</DropdownMenuLabel>
                      <DropdownMenuItem onClick={() => router.push(`/profiles/${profile.id}`)}>
                        <Edit className="mr-2 h-4 w-4" />
                        Edit Profile
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => onVerify(profile.id)} disabled={isVerifying}>
                        <RefreshCw className={`mr-2 h-4 w-4 ${isVerifying ? 'animate-spin' : ''}`} />
                        Verify Connection
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => window.open(profile.linkedin_url, '_blank')}>
                        <ExternalLink className="mr-2 h-4 w-4" />
                        View on LinkedIn
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => onDelete(profile.id)} className="text-red-600 focus:text-red-600">
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete Profile
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

