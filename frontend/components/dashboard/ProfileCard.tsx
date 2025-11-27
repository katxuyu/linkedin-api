'use client'

import React from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card'
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

interface ProfileCardProps {
  profile: OutreachProfile
  status?: ProfileStatus
  onDelete: (id: number) => void
  onVerify: (id: number) => void
  isVerifying: boolean
  stats?: {
    active_campaigns: number
    total_connections: number
  }
}

export const ProfileCard: React.FC<ProfileCardProps> = ({
  profile,
  status,
  onDelete,
  onVerify,
  isVerifying,
  stats
}) => {
  const router = useRouter()

  const getStatusColor = (status?: ProfileStatus) => {
    if (!status) return 'bg-gray-100 text-gray-600 border-gray-200'
    if (status.session_status === 'pending_approval') return 'bg-indigo-100 text-indigo-700 border-indigo-200'
    if (status.session_status === 'verifying') return 'bg-blue-100 text-blue-700 border-blue-200'
    if (status.session_status === 'manual_verification') return 'bg-amber-100 text-amber-800 border-amber-200'
    if (status.needs_attention) return 'bg-red-100 text-red-700 border-red-200'
    if (status.is_connected && status.session_status === 'active') return 'bg-green-100 text-green-700 border-green-200'
    if (status.session_status === 'missing') return 'bg-yellow-100 text-yellow-700 border-yellow-200'
    return 'bg-gray-100 text-gray-600 border-gray-200'
  }

  const getStatusLabel = (status?: ProfileStatus) => {
    if (!status) return 'Loading...'
    if (status.session_status === 'pending_approval') return 'Awaiting Approval'
    if (status.session_status === 'verifying') return 'Verifying...'
    if (status.session_status === 'manual_verification') return 'Manual Action Needed'
    if (status.needs_attention) return 'Needs Attention'
    if (status.is_connected && status.session_status === 'active') return 'Active'
    if (status.session_status === 'missing') return 'No Session'
    return 'Inactive'
  }
  
  const getStatusTooltip = (status?: ProfileStatus) => {
    if (!status || status.issues.length === 0) return undefined
    return status.issues[0]
  }

  return (
    <Card className="w-full hover:shadow-md transition-shadow">
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
        <div className="flex flex-col space-y-1">
          <CardTitle className="text-lg font-medium truncate max-w-[200px]" title={profile.account_name || profile.linkedin_email}>
            {profile.account_name || profile.linkedin_email}
          </CardTitle>
          <p className="text-sm text-muted-foreground truncate max-w-[200px]" title={profile.linkedin_email}>
            {profile.linkedin_email}
          </p>
        </div>
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
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Badge 
              variant="outline" 
              className={`${getStatusColor(status)} border`}
              title={getStatusTooltip(status)}
            >
              {getStatusLabel(status)}
            </Badge>
            {status?.is_verified && (
              <Badge variant="secondary" className="text-xs">
                Verified
              </Badge>
            )}
          </div>
          
          {stats && (
            <div className="grid grid-cols-2 gap-4 pt-2">
              <div className="flex flex-col">
                <span className="text-xs text-muted-foreground">Active Campaigns</span>
                <span className="text-lg font-bold">{stats.active_campaigns}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-xs text-muted-foreground">Connections</span>
                <span className="text-lg font-bold">{stats.total_connections}</span>
              </div>
            </div>
          )}
          
          {profile.gohighlevel_location_id && (
            <div className="pt-2 flex items-center text-xs text-muted-foreground">
               <Activity className="mr-1 h-3 w-3" />
               GHL Connected
            </div>
          )}
        </div>
      </CardContent>
      <CardFooter className="pt-0">
        <Button variant="outline" className="w-full" onClick={() => router.push(`/profiles/${profile.id}`)}>
          Manage Profile
        </Button>
      </CardFooter>
    </Card>
  )
}

