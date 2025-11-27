'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { useClients, useDeleteClient, useUpdateClient } from '@/lib/hooks/useClients'
import { ClientCard } from '@/components/dashboard/ClientCard'
import { ClientsTable } from '@/components/dashboard/ClientsTable'
import { ViewToggle } from '@/components/ui/view-toggle'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Search, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { get_view_preference, save_view_preference } from '@/lib/utils/view-preferences'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { auth_api } from '@/lib/api/auth'
import { clients_api } from '@/lib/api/clients'

export default function ClientsPage() {
  const { user } = useAuth()
  const router = useRouter()
  const { data: clients, isLoading, error, refetch } = useClients()
  const delete_client = useDeleteClient()
  const update_client = useUpdateClient()
  
  const [search_query, set_search_query] = useState('')
  const [filter_admin, set_filter_admin] = useState<string>('all')
  const [view_mode, set_view_mode] = useState<'card' | 'list'>('card')
  const [delete_id, set_delete_id] = useState<number | null>(null)
  const [edit_id, set_edit_id] = useState<number | null>(null)
  const [edit_email, set_edit_email] = useState('')
  const [edit_is_admin, set_edit_is_admin] = useState(false)
  
  // Add client state
  const [add_dialog_open, set_add_dialog_open] = useState(false)
  const [new_client_email, set_new_client_email] = useState('')
  const [new_client_password, set_new_client_password] = useState('')
  const [new_client_is_admin, set_new_client_is_admin] = useState(false)
  const [is_creating, set_is_creating] = useState(false)

  useEffect(() => {
    if (user && !user.is_admin) {
      router.push('/campaigns')
      return
    }
  }, [user, router])

  useEffect(() => {
    set_view_mode(get_view_preference('clients'))
  }, [])

  useEffect(() => {
    if (edit_id && clients) {
      const client = clients.find(c => c.id === edit_id)
      if (client) {
        set_edit_email(client.email)
        set_edit_is_admin(client.is_admin)
      }
    }
  }, [edit_id, clients])

  const handle_view_change = (mode: 'card' | 'list') => {
    set_view_mode(mode)
    save_view_preference('clients', mode)
  }

  const filtered_clients = clients?.filter(client => {
    const search_match = search_query === '' || 
      client.email.toLowerCase().includes(search_query.toLowerCase()) ||
      client.id.toString().includes(search_query)
    const admin_match = filter_admin === 'all' || 
      (filter_admin === 'admin' && client.is_admin) ||
      (filter_admin === 'regular' && !client.is_admin)
    return search_match && admin_match
  }) || []

  const handle_delete = async () => {
    if (!delete_id) return
    try {
      await delete_client.mutateAsync(delete_id)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to delete client'
      toast.error(message)
    } finally {
      set_delete_id(null)
    }
  }

  const handle_edit = async () => {
    if (!edit_id) return
    try {
      await update_client.mutateAsync({
        id: edit_id,
        data: {
          email: edit_email !== clients?.find(c => c.id === edit_id)?.email ? edit_email : undefined,
          is_admin: edit_is_admin !== clients?.find(c => c.id === edit_id)?.is_admin ? edit_is_admin : undefined,
        }
      })
      set_edit_id(null)
      set_edit_email('')
      set_edit_is_admin(false)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to update client'
      toast.error(message)
    }
  }

  const handle_add_client = async () => {
    if (!new_client_email || !new_client_password) {
      toast.error('Please provide email and password')
      return
    }

    // Password validation
    const password_regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/
    if (!password_regex.test(new_client_password)) {
      toast.error('Password must be at least 8 characters with 1 uppercase, 1 lowercase, 1 number, and 1 special character')
      return
    }

    set_is_creating(true)
    try {
      // Generate registration key (admin function)
      const key_response = await auth_api.generate_registration_key()
      
      // Register the new client
      const new_user = await auth_api.register_client(
        new_client_email,
        new_client_password,
        key_response.registration_key
      )
      
      // If admin checkbox is checked, update the user to be admin
      if (new_client_is_admin && new_user.id) {
        await clients_api.update_client(new_user.id, { is_admin: true })
        toast.success(`Admin "${new_client_email}" created successfully!`)
      } else {
        toast.success(`Client "${new_client_email}" created successfully!`)
      }
      
      // Reset form and close dialog
      set_add_dialog_open(false)
      set_new_client_email('')
      set_new_client_password('')
      set_new_client_is_admin(false)
      
      // Refresh the clients list
      await refetch()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string | { msg?: string }[] } }; message?: string }
      let message = 'Failed to create client'
      
      if (error.response?.data?.detail) {
        if (typeof error.response.data.detail === 'string') {
          message = error.response.data.detail
        } else if (Array.isArray(error.response.data.detail)) {
          message = error.response.data.detail.map(d => d.msg).join(', ')
        }
      } else if (error.message) {
        message = error.message
      }
      
      toast.error(message)
    } finally {
      set_is_creating(false)
    }
  }

  const reset_add_dialog = () => {
    set_new_client_email('')
    set_new_client_password('')
    set_new_client_is_admin(false)
  }

  if (!user?.is_admin) {
    return null
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-start gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Clients</h1>
          <p className="text-sm text-gray-600">
            Manage your clients and their accounts
          </p>
        </div>
        <Button 
          onClick={() => set_add_dialog_open(true)}
          className="bg-black hover:bg-gray-800 text-white shrink-0"
        >
          <Plus className="h-4 w-4 mr-1.5" />
          Add Client
        </Button>
      </div>

      <Card className="py-3">
        <CardContent className="px-4">
          <div className="flex flex-col sm:flex-row gap-2 items-center w-full">
            <div className="relative flex-1 w-full">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search clients..."
                value={search_query}
                onChange={(e) => set_search_query(e.target.value)}
                className="pl-8 h-9"
              />
            </div>
            <div className="w-full sm:w-auto sm:min-w-[150px]">
              <select
                className="w-full h-9 px-3 text-sm rounded-md border border-gray-300 bg-white"
                value={filter_admin}
                onChange={(e) => set_filter_admin(e.target.value)}
              >
                <option value="all">All Roles</option>
                <option value="admin">Admin</option>
                <option value="regular">Regular Users</option>
              </select>
            </div>
            <ViewToggle value={view_mode} onValueChange={handle_view_change} />
          </div>
        </CardContent>
      </Card>

      {isLoading ? (
        view_mode === 'card' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-48 bg-gray-100 rounded-lg animate-pulse"></div>
            ))}
          </div>
        ) : (
          <div className="h-48 bg-gray-100 rounded-lg animate-pulse"></div>
        )
      ) : error ? (
        <div className="text-center py-10 text-red-500">
          Failed to load clients. Please try again.
        </div>
      ) : filtered_clients.length === 0 ? (
        <div className="text-center py-20 bg-gray-50 rounded-lg border border-dashed">
          <h3 className="text-lg font-medium text-gray-900">No clients found</h3>
          <p className="text-gray-500 mt-1 mb-4">
            {search_query || filter_admin !== 'all' 
              ? 'Try adjusting your filters.' 
              : 'No clients registered yet.'}
          </p>
        </div>
      ) : view_mode === 'card' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered_clients.map((client) => (
            <ClientCard
              key={client.id}
              client={client}
              onDelete={set_delete_id}
              onEdit={set_edit_id}
            />
          ))}
        </div>
      ) : (
        <ClientsTable
          clients={filtered_clients}
          onDelete={set_delete_id}
          onEdit={set_edit_id}
        />
      )}

      <AlertDialog open={!!delete_id} onOpenChange={(open) => !open && set_delete_id(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you sure?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. This will permanently delete the client
              and remove all associated data.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handle_delete} className="bg-red-600 hover:bg-red-700">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={!!edit_id} onOpenChange={(open) => !open && set_edit_id(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Client</DialogTitle>
            <DialogDescription>
              Update client information. Leave fields unchanged to keep current values.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={edit_email}
                onChange={(e) => set_edit_email(e.target.value)}
              />
            </div>
            <div className="flex items-center space-x-2">
              <Checkbox
                id="is_admin"
                checked={edit_is_admin}
                onCheckedChange={(checked) => set_edit_is_admin(checked === true)}
              />
              <Label htmlFor="is_admin" className="cursor-pointer">
                Admin privileges
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => set_edit_id(null)}>
              Cancel
            </Button>
            <Button onClick={handle_edit} disabled={update_client.isPending}>
              {update_client.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Client Dialog */}
      <Dialog open={add_dialog_open} onOpenChange={(open) => {
        set_add_dialog_open(open)
        if (!open) reset_add_dialog()
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Client</DialogTitle>
            <DialogDescription>
              Create a new client account. They will be able to log in with these credentials.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="new-email">Email</Label>
              <Input
                id="new-email"
                type="email"
                placeholder="client@example.com"
                value={new_client_email}
                onChange={(e) => set_new_client_email(e.target.value)}
                disabled={is_creating}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">Password</Label>
              <Input
                id="new-password"
                type="password"
                placeholder="Min 8 chars, 1 upper, 1 lower, 1 number, 1 special"
                value={new_client_password}
                onChange={(e) => set_new_client_password(e.target.value)}
                disabled={is_creating}
              />
              <p className="text-xs text-muted-foreground">
                Password must contain at least 8 characters, including uppercase, lowercase, number, and special character.
              </p>
            </div>
            <div className="flex items-center space-x-2">
              <Checkbox
                id="new-is-admin"
                checked={new_client_is_admin}
                onCheckedChange={(checked) => set_new_client_is_admin(checked === true)}
                disabled={is_creating}
              />
              <Label htmlFor="new-is-admin" className="cursor-pointer">
                Grant admin privileges
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => set_add_dialog_open(false)} disabled={is_creating}>
              Cancel
            </Button>
            <Button 
              onClick={handle_add_client} 
              disabled={is_creating || !new_client_email || !new_client_password}
            >
              {is_creating ? 'Creating...' : 'Create Client'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
