'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { useClientById, useClientProfiles, useClientCampaigns, useUpdateClient } from '@/lib/hooks/useClients'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ArrowLeft, Edit, User, Calendar, Mail, Shield, Link2, CheckCircle, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { AxiosError } from 'axios'
import { useGHLAccountsForUser } from '@/lib/hooks/useGHL'

export default function ClientDetailPage() {
  const router = useRouter()
  const params = useParams()
  const { user, accessToken } = useAuth()
  const client_id = params?.id ? parseInt(params.id as string) : null
  
  const { data: client, isLoading } = useClientById(client_id)
  const { data: profiles, isLoading: profiles_loading } = useClientProfiles(client_id)
  const { data: campaigns, isLoading: campaigns_loading } = useClientCampaigns(client_id)
  const { data: ghl_accounts, isLoading: ghl_loading } = useGHLAccountsForUser(accessToken, client_id)
  const update_client = useUpdateClient()
  
  const [edit_open, set_edit_open] = useState(false)
  const [edit_email, set_edit_email] = useState('')
  const [edit_is_admin, set_edit_is_admin] = useState(false)

  useEffect(() => {
    if (user && !user.is_admin) {
      router.push('/campaigns')
      return
    }
  }, [user, router])

  const open_edit_dialog = () => {
    if (client) {
      set_edit_email(client.email)
      set_edit_is_admin(client.is_admin)
    }
    set_edit_open(true)
  }

  const handle_edit = async () => {
    if (!client_id) return
    try {
      await update_client.mutateAsync({
        id: client_id,
        data: {
          email: edit_email !== client?.email ? edit_email : undefined,
          is_admin: edit_is_admin !== client?.is_admin ? edit_is_admin : undefined,
        }
      })
      set_edit_open(false)
    } catch (err: unknown) {
      const axios_error = err as AxiosError
      toast.error(axios_error.message || 'Failed to update client')
    }
  }

  const format_date = (date_string: string) => {
    const date = new Date(date_string)
    return date.toLocaleDateString('en-US', { 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const get_status_badge = (status: string) => {
    const status_colors: Record<string, string> = {
      active: 'bg-green-100 text-green-700 border-green-200',
      completed: 'bg-blue-100 text-blue-700 border-blue-200',
      failed: 'bg-red-100 text-red-700 border-red-200',
      paused: 'bg-yellow-100 text-yellow-700 border-yellow-200',
      cancelled: 'bg-gray-100 text-gray-700 border-gray-200',
    }
    return status_colors[status] || 'bg-gray-100 text-gray-700 border-gray-200'
  }

  if (!user?.is_admin) {
    return null
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  if (!client) {
    return (
      <div className="text-center py-20">
        <h3 className="text-lg font-medium text-gray-900">Client not found</h3>
        <Button onClick={() => router.push('/clients')} className="mt-4">
          Back to Clients
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => router.push('/clients')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-3xl font-bold text-gray-900">{client.email}</h1>
          <p className="text-gray-600 mt-1">Client Details</p>
        </div>
        <Button onClick={open_edit_dialog}>
          <Edit className="mr-2 h-4 w-4" />
          Edit Client
        </Button>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="profiles">Profiles ({profiles?.length || 0})</TabsTrigger>
          <TabsTrigger value="campaigns">Campaigns ({campaigns?.length || 0})</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Client Information</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-2">
                  <Mail className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-sm text-muted-foreground">Email</p>
                    <p className="font-medium">{client.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Shield className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-sm text-muted-foreground">Role</p>
                    {client.is_admin ? (
                      <Badge variant="default" className="bg-blue-600">Admin</Badge>
                    ) : (
                      <Badge variant="outline">Regular User</Badge>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="text-sm text-muted-foreground">Joined</p>
                    <p className="font-medium">{format_date(client.created_at)}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Statistics</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <User className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm text-muted-foreground">LinkedIn Profiles</span>
                  </div>
                  <span className="text-2xl font-bold">{client.profile_count}</span>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Calendar className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm text-muted-foreground">Campaigns</span>
                  </div>
                  <span className="text-2xl font-bold">{client.campaign_count}</span>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* GHL Accounts Section */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Link2 className="h-5 w-5" />
                GoHighLevel Accounts
              </CardTitle>
            </CardHeader>
            <CardContent>
              {ghl_loading ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-900"></div>
                  <span>Loading GHL accounts...</span>
                </div>
              ) : ghl_accounts && ghl_accounts.length > 0 ? (
                <div className="space-y-3">
                  {ghl_accounts.map((account) => (
                    <div 
                      key={account.id}
                      className="flex items-center justify-between p-3 bg-green-50 border border-green-200 rounded-md"
                    >
                      <div className="flex items-center gap-3">
                        <CheckCircle className="h-5 w-5 text-green-600" />
                        <div>
                          <p className="font-medium text-green-800">
                            {account.display_name || 'GHL Location'}
                          </p>
                          <p className="text-sm text-green-700 font-mono">
                            {account.location_id}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {account.is_default && (
                          <Badge variant="secondary" className="text-xs">Default</Badge>
                        )}
                        {account.is_active ? (
                          <Badge variant="default" className="bg-green-600 text-xs">Active</Badge>
                        ) : (
                          <Badge variant="destructive" className="text-xs">Expired</Badge>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex items-center gap-3 p-4 bg-amber-50 border border-amber-200 rounded-md">
                  <AlertCircle className="h-5 w-5 text-amber-600" />
                  <div>
                    <p className="font-medium text-amber-800">No GHL account connected</p>
                    <p className="text-sm text-amber-700">
                      Connect a GoHighLevel account when creating this client to enable contact sync.
                    </p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="profiles" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>LinkedIn Profiles</CardTitle>
            </CardHeader>
            <CardContent>
              {profiles_loading ? (
                <div className="text-center py-10">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
                </div>
              ) : !profiles || profiles.length === 0 ? (
                <div className="text-center py-10 text-muted-foreground">
                  No profiles found for this client.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Account Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>LinkedIn URL</TableHead>
                      <TableHead>Added At</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {profiles.map((profile) => (
                      <TableRow key={profile.id}>
                        <TableCell className="font-medium">
                          {profile.account_name || 'N/A'}
                        </TableCell>
                        <TableCell>{profile.linkedin_email}</TableCell>
                        <TableCell>
                          <a 
                            href={profile.linkedin_url} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline"
                          >
                            View Profile
                          </a>
                        </TableCell>
                        <TableCell>{format_date(profile.added_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="campaigns" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Campaigns</CardTitle>
            </CardHeader>
            <CardContent>
              {campaigns_loading ? (
                <div className="text-center py-10">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 mx-auto"></div>
                </div>
              ) : !campaigns || campaigns.length === 0 ? (
                <div className="text-center py-10 text-muted-foreground">
                  No campaigns found for this client.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Runtime ID</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Steps</TableHead>
                      <TableHead>Started At</TableHead>
                      <TableHead>Last Modified</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {campaigns.map((campaign) => (
                      <TableRow 
                        key={campaign.campaign_history_id}
                        className="cursor-pointer hover:bg-gray-50"
                        onClick={() => router.push(`/campaigns/${campaign.campaign_history_id}`)}
                      >
                        <TableCell className="font-medium font-mono text-xs">
                          {campaign.runtime_id.substring(0, 8)}...
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={get_status_badge(campaign.status)}>
                            {campaign.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {campaign.finished_on_step_number || 0} / {campaign.number_of_steps}
                        </TableCell>
                        <TableCell>{format_date(campaign.started_at)}</TableCell>
                        <TableCell>{format_date(campaign.modified_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={edit_open} onOpenChange={set_edit_open}>
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
            <Button variant="outline" onClick={() => set_edit_open(false)}>
              Cancel
            </Button>
            <Button onClick={handle_edit} disabled={update_client.isPending}>
              {update_client.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
