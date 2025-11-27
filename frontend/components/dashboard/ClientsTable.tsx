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
import { MoreHorizontal, Edit, Trash2, ExternalLink, User, Calendar } from 'lucide-react'
import { Client } from '@/types'

interface ClientsTableProps {
  clients: Client[]
  onDelete: (id: number) => void
  onEdit: (id: number) => void
}

export const ClientsTable: React.FC<ClientsTableProps> = ({
  clients,
  onDelete,
  onEdit,
}) => {
  const router = useRouter()

  const format_date = (date_string: string) => {
    const date = new Date(date_string)
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
  }

  return (
    <div className="border rounded-lg">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead className="text-center">Profiles</TableHead>
            <TableHead className="text-center">Campaigns</TableHead>
            <TableHead>Joined</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {clients.map((client) => (
            <TableRow
              key={client.id}
              className="cursor-pointer hover:bg-gray-50"
              onClick={() => router.push(`/clients/${client.id}`)}
            >
              <TableCell className="font-medium">
                {client.email}
              </TableCell>
              <TableCell>
                {client.is_admin ? (
                  <Badge variant="default" className="bg-blue-600">
                    Admin
                  </Badge>
                ) : (
                  <Badge variant="outline">Regular User</Badge>
                )}
              </TableCell>
              <TableCell className="text-center">
                <div className="flex items-center justify-center gap-1">
                  <User className="h-4 w-4 text-muted-foreground" />
                  {client.profile_count}
                </div>
              </TableCell>
              <TableCell className="text-center">
                <div className="flex items-center justify-center gap-1">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  {client.campaign_count}
                </div>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {format_date(client.created_at)}
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
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

