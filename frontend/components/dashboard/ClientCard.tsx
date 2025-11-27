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
import { MoreHorizontal, Edit, Trash2, ExternalLink, User, Calendar } from 'lucide-react'
import { Client } from '@/types'

interface ClientCardProps {
  client: Client
  onDelete: (id: number) => void
  onEdit: (id: number) => void
}

export const ClientCard: React.FC<ClientCardProps> = ({
  client,
  onDelete,
  onEdit,
}) => {
  const router = useRouter()

  const format_date = (date_string: string) => {
    const date = new Date(date_string)
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
  }

  return (
    <Card className="w-full hover:shadow-md transition-shadow">
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
        <div className="flex flex-col space-y-1">
          <CardTitle className="text-lg font-medium truncate max-w-[200px]" title={client.email}>
            {client.email}
          </CardTitle>
          <p className="text-sm text-muted-foreground truncate max-w-[200px]">
            ID: {client.id}
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
            <DropdownMenuItem onClick={() => onEdit(client.id)}>
              <Edit className="mr-2 h-4 w-4" />
              Edit Client
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push(`/clients/${client.id}`)}>
              <ExternalLink className="mr-2 h-4 w-4" />
              View Details
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onDelete(client.id)} className="text-red-600 focus:text-red-600">
              <Trash2 className="mr-2 h-4 w-4" />
              Delete Client
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            {client.is_admin ? (
              <Badge variant="default" className="bg-blue-600">
                Admin
              </Badge>
            ) : (
              <Badge variant="outline">Regular User</Badge>
            )}
          </div>
          
          <div className="grid grid-cols-2 gap-4 pt-2">
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <User className="h-3 w-3" />
                Profiles
              </span>
              <span className="text-lg font-bold">{client.profile_count}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                Campaigns
              </span>
              <span className="text-lg font-bold">{client.campaign_count}</span>
            </div>
          </div>
          
          <div className="pt-2 flex items-center text-xs text-muted-foreground">
            <Calendar className="mr-1 h-3 w-3" />
            Joined: {format_date(client.created_at)}
          </div>
        </div>
      </CardContent>
      <CardFooter className="pt-0">
        <Button variant="outline" className="w-full" onClick={() => router.push(`/clients/${client.id}`)}>
          View Details
        </Button>
      </CardFooter>
    </Card>
  )
}

