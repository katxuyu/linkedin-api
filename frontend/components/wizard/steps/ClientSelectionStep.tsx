"use client"

import React, { useEffect, useState } from "react"
import { useWizard } from '@/lib/context/WizardContext'
import { useClients } from '@/lib/hooks/useClients'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger } from '@/components/ui/dialog'
import { auth_api } from '@/lib/api/auth'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { useAuth } from '@/lib/context/AuthContext'

interface ClientSelectionStepProps {
  on_next: () => void
  on_back: () => void
}

export const ClientSelectionStep: React.FC<ClientSelectionStepProps> = ({
  on_next,
}) => {
  const { user, accessToken } = useAuth()
  const is_admin = !!user?.is_admin
  const { state, update_state } = useWizard()
  const { data: clients, isLoading, refetch } = useClients({ enabled: is_admin })
  const [search_query, set_search_query] = useState('')
  const [is_creating, set_is_creating] = useState(false)
  const [new_client_email, set_new_client_email] = useState('')
  const [new_client_password, set_new_client_password] = useState('')
  const [dialog_open, set_dialog_open] = useState(false)
  const [password_dialog_open, set_password_dialog_open] = useState(false)
  const [selected_client_for_auth, set_selected_client_for_auth] = useState<{id: number, email: string} | null>(null)
  const [client_password_input, set_client_password_input] = useState('')

  const filtered_clients = clients?.filter((client) =>
    client.email.toLowerCase().includes(search_query.toLowerCase())
  )

  const format_error_message = (error: unknown): string => {
    if (typeof error === 'string') {
      return error
    }
    
    if (error && typeof error === 'object') {
      const errObj = error as { response?: { data?: { detail?: unknown } }; message?: string }
      const detail = errObj.response?.data?.detail
      
      if (typeof detail === 'string') {
        return detail
      }
      
      if (Array.isArray(detail)) {
        return detail.map((err) => (typeof err === 'object' && err && 'msg' in err ? (err as { msg?: string }).msg : JSON.stringify(err))).join(', ')
      }
      
      if (detail && typeof detail === 'object' && 'msg' in detail) {
        return (detail as { msg?: string }).msg || JSON.stringify(detail)
      }

      if (errObj.message) {
        return errObj.message
      }
    }
    
    return 'An unexpected error occurred'
  }

  const handle_select_client = async (client_id: number, client_email: string, password?: string) => {
    const selecting_self = !is_admin && user && client_id === user.id
    if (selecting_self) {
      update_state({
        selectedClientId: client_id,
        clientEmail: client_email,
        clientAccessToken: accessToken || state.clientAccessToken || null,
      })
      toast.success(`Selected client: ${client_email}`)
      on_next()
      return
    }

    if (password) {
      try {
        const tokens = await auth_api.login(client_email, password)
        
        update_state({
          selectedClientId: client_id,
          clientEmail: client_email,
          clientAccessToken: tokens.access_token,
        })
        
        toast.success(`Selected client: ${client_email}`)
        set_password_dialog_open(false)
        set_client_password_input('')
        set_selected_client_for_auth(null)
        on_next()
        return
      } catch (error) {
        toast.error('Invalid password for client')
        return
      }
    }
    
    set_selected_client_for_auth({id: client_id, email: client_email})
    set_password_dialog_open(true)
  }

  const handle_password_submit = () => {
    if (!selected_client_for_auth || !client_password_input) {
      toast.error('Password required')
      return
    }
    handle_select_client(
      selected_client_for_auth.id,
      selected_client_for_auth.email,
      client_password_input
    )
  }

  const handle_create_client = async () => {
    if (!new_client_email || !new_client_password) {
      toast.error('Please provide email and password')
      return
    }

    set_is_creating(true)
    try {
      const key = await auth_api.generate_registration_key()
      const new_client = await auth_api.register_client(
        new_client_email,
        new_client_password,
        key.registration_key
      )
      
      toast.success('Client created successfully')
      await refetch()
      set_dialog_open(false)
      set_new_client_email('')
      set_new_client_password('')
      
      handle_select_client(new_client.id, new_client.email, new_client_password)
    } catch (error: unknown) {
      const error_message = format_error_message(error)
      toast.error(error_message)
    } finally {
      set_is_creating(false)
    }
  }

  useEffect(() => {
    if (!is_admin && user) {
      if (state.selectedClientId !== user.id || !state.clientAccessToken) {
        update_state({
          selectedClientId: user.id,
          clientEmail: user.email,
          clientAccessToken: state.clientAccessToken || accessToken || null,
        })
      }
    }
  }, [is_admin, user, state.selectedClientId, state.clientAccessToken, update_state, accessToken])

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end">
        <div className={`flex-1 ${is_admin ? 'mr-4' : ''}`}>
          {is_admin ? (
            <>
              <Label htmlFor="search">Search Clients</Label>
              <Input
                id="search"
                type="text"
                placeholder="Search by email..."
                value={search_query}
                onChange={(e) => set_search_query(e.target.value)}
                className="mt-2"
              />
            </>
          ) : (
            <div className="mt-2 text-gray-700">
              <p className="font-medium">Your account</p>
              <p className="text-sm text-gray-600">{user?.email}</p>
            </div>
          )}
        </div>
        {is_admin && (
        <Dialog open={dialog_open} onOpenChange={set_dialog_open}>
          <DialogTrigger asChild>
            <Button>Create New Client</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create New Client</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label htmlFor="new-email">Email</Label>
                <Input
                  id="new-email"
                  type="email"
                  value={new_client_email}
                  onChange={(e) => set_new_client_email(e.target.value)}
                  placeholder="client@example.com"
                  disabled={is_creating}
                />
              </div>
              <div>
                <Label htmlFor="new-password">Password</Label>
                <Input
                  id="new-password"
                  type="password"
                  value={new_client_password}
                  onChange={(e) => set_new_client_password(e.target.value)}
                  placeholder="Min 8 chars, 1 upper, 1 lower, 1 number, 1 special"
                  disabled={is_creating}
                />
              </div>
              <Button
                onClick={handle_create_client}
                disabled={is_creating}
                className="w-full"
              >
                {is_creating ? 'Creating...' : 'Create Client'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
        )}
      </div>

      {is_admin && (
        <>
          {isLoading ? (
            <div className="text-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
              <p className="mt-2 text-gray-600">Loading clients...</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filtered_clients?.map((client) => (
                <Card
                  key={client.id}
                  className={`cursor-pointer transition-all hover:shadow-lg ${
                    state.selectedClientId === client.id
                      ? 'ring-2 ring-blue-500'
                      : ''
                  }`}
                  onClick={() => handle_select_client(client.id, client.email)}
                >
                  <CardHeader>
                    <CardTitle className="text-lg flex items-center justify-between">
                      {client.email}
                      {client.is_admin && (
                        <Badge variant="secondary">Admin</Badge>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-gray-600">
                      Created: {new Date(client.created_at).toLocaleDateString()}
                    </p>
                    <p className="text-sm text-gray-600">ID: {client.id}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {!isLoading && filtered_clients?.length === 0 && (
            <div className="text-center py-8 text-gray-600">
              No clients found matching your search.
            </div>
          )}
        </>
      )}

      <Dialog open={password_dialog_open} onOpenChange={set_password_dialog_open}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enter Client Password</DialogTitle>
            <DialogDescription>
              Enter the password for {selected_client_for_auth?.email} to manage their LinkedIn profiles.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <Label htmlFor="client-password">Password</Label>
              <Input
                id="client-password"
                type="password"
                value={client_password_input}
                onChange={(e) => set_client_password_input(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handle_password_submit()
                  }
                }}
                placeholder="Enter client password"
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                set_password_dialog_open(false)
                set_client_password_input('')
                set_selected_client_for_auth(null)
              }}
            >
              Cancel
            </Button>
            <Button onClick={handle_password_submit}>
              Continue
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
