'use client'

import React, { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogFooter, 
  DialogHeader, 
  DialogTitle 
} from '@/components/ui/dialog'
import { toast } from 'sonner'
import { 
  ExternalLink, 
  RefreshCw, 
  CheckCircle, 
  AlertCircle, 
  Link2, 
  Loader2,
  Copy,
  Star
} from 'lucide-react'
import { 
  useGHLStatus, 
  useGHLAccounts, 
  useGHLAuthUrl, 
  useGHLExchangeCode,
  useSetDefaultGHLAccount 
} from '@/lib/hooks/useGHL'
import { GHLAccount } from '@/lib/api/ghl'

interface GHLConnectionManagerProps {
  client_token: string
  on_account_selected?: (account: GHLAccount) => void
  selected_location_id?: string | null
  compact?: boolean
}

export function GHLConnectionManager({
  client_token,
  on_account_selected,
  selected_location_id,
  compact = false
}: GHLConnectionManagerProps) {
  const [auth_code, set_auth_code] = useState('')
  const [auth_url, set_auth_url] = useState<string | null>(null)
  const [client_state, set_client_state] = useState<string | null>(null)
  const [connect_dialog_open, set_connect_dialog_open] = useState(false)
  
  const { data: status, isLoading: status_loading, error: status_error } = useGHLStatus(client_token)
  const { data: accounts, isLoading: accounts_loading, refetch: refetch_accounts } = useGHLAccounts(client_token)
  const get_auth_url = useGHLAuthUrl(client_token)
  const exchange_code = useGHLExchangeCode(client_token)
  const set_default = useSetDefaultGHLAccount(client_token)

  const is_configured = status?.ghl_integration?.configured ?? false
  const default_account = accounts?.find(a => a.is_default)
  // Note: selected_account available for future use
  const _selected_account = accounts?.find(a => a.location_id === selected_location_id) || default_account

  // Generate a unique client state for this session (initialized once)
  const [initialized_client_state] = useState(() => 
    `ghl_${Date.now()}_${Math.random().toString(36).substring(7)}`
  )
  
  // Only set client_state if not already set
  if (!client_state && initialized_client_state) {
    set_client_state(initialized_client_state)
  }

  const handle_get_auth_url = async () => {
    try {
      const result = await get_auth_url.mutateAsync({ 
        client_state: client_state || undefined,
        make_default: true 
      })
      set_auth_url(result.authorization_url)
      toast.success('Authorization URL generated!')
    } catch (error) {
      toast.error('Failed to generate authorization URL')
    }
  }

  const handle_exchange_code = async () => {
    if (!auth_code.trim()) {
      toast.error('Please enter the authorization code')
      return
    }

    try {
      const result = await exchange_code.mutateAsync({
        code: auth_code.trim(),
        client_state: client_state || undefined,
        make_default: true
      })
      
      toast.success(`GoHighLevel account connected! Location ID: ${result.location_id}`)
      set_auth_code('')
      set_auth_url(null)
      set_connect_dialog_open(false)
      
      // Refresh accounts list
      await refetch_accounts()
      
      // Notify parent
      const new_account = accounts?.find(a => a.id === result.account_id)
      if (new_account && on_account_selected) {
        on_account_selected(new_account)
      }
    } catch (error) {
      toast.error('Failed to exchange authorization code. Make sure you copied the full code.')
    }
  }

  const handle_select_account = (location_id: string) => {
    const account = accounts?.find(a => a.location_id === location_id)
    if (account && on_account_selected) {
      on_account_selected(account)
    }
  }

  const handle_set_default = async (account_id: number) => {
    try {
      await set_default.mutateAsync(account_id)
      toast.success('Default account updated')
    } catch (error) {
      toast.error('Failed to set default account')
    }
  }

  const copy_to_clipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    toast.success('Copied to clipboard!')
  }

  // Loading state
  if (status_loading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Checking GoHighLevel configuration...</span>
      </div>
    )
  }

  // Error or not configured
  if (status_error || !is_configured) {
    if (compact) {
      return (
        <div className="flex items-center gap-2 text-amber-600">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm">GHL not configured</span>
        </div>
      )
    }
    
    return (
      <Alert variant="default" className="border-amber-200 bg-amber-50">
        <AlertCircle className="h-4 w-4 text-amber-600" />
        <AlertTitle className="text-amber-800">GoHighLevel Not Configured</AlertTitle>
        <AlertDescription className="text-amber-700">
          GoHighLevel integration is not configured on the server. 
          Contact your administrator to set up GHL credentials.
        </AlertDescription>
      </Alert>
    )
  }

  // Compact mode - just show account selector
  if (compact) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Select 
            value={selected_location_id || ''} 
            onValueChange={handle_select_account}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select GHL Location" />
            </SelectTrigger>
            <SelectContent>
              {accounts?.map((account) => (
                <SelectItem key={account.id} value={account.location_id}>
                  <div className="flex items-center gap-2">
                    {account.display_name || account.location_id}
                    {account.is_default && <Star className="h-3 w-3 text-amber-500" />}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          
          <Button 
            variant="outline" 
            size="icon"
            onClick={() => set_connect_dialog_open(true)}
            title="Connect new GHL account"
          >
            <Link2 className="h-4 w-4" />
          </Button>
          
          <Button 
            variant="ghost" 
            size="icon"
            onClick={() => refetch_accounts()}
            disabled={accounts_loading}
            title="Refresh accounts"
          >
            <RefreshCw className={`h-4 w-4 ${accounts_loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
        
        {/* Connect Dialog */}
        <Dialog open={connect_dialog_open} onOpenChange={set_connect_dialog_open}>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>Connect GoHighLevel Account</DialogTitle>
              <DialogDescription>
                Follow these steps to connect your GoHighLevel location.
              </DialogDescription>
            </DialogHeader>
            
            <div className="space-y-4 py-4">
              {/* Step 1: Get Auth URL */}
              <div className="space-y-2">
                <Label className="font-medium">Step 1: Get Authorization URL</Label>
                <Button 
                  onClick={handle_get_auth_url} 
                  disabled={get_auth_url.isPending}
                  className="w-full"
                >
                  {get_auth_url.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Link2 className="mr-2 h-4 w-4" />
                      Generate Authorization URL
                    </>
                  )}
                </Button>
                
                {auth_url && (
                  <div className="space-y-2 p-3 bg-muted rounded-md">
                    <div className="flex items-center gap-2">
                      <a 
                        href={auth_url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline flex items-center gap-1 text-sm"
                      >
                        <ExternalLink className="h-3 w-3" />
                        Open GoHighLevel Authorization
                      </a>
                      <Button 
                        variant="ghost" 
                        size="sm"
                        onClick={() => copy_to_clipboard(auth_url)}
                      >
                        <Copy className="h-3 w-3" />
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Click the link, authorize the app, then copy the <code>code</code> parameter from the redirect URL.
                    </p>
                  </div>
                )}
              </div>
              
              {/* Step 2: Enter Code */}
              <div className="space-y-2">
                <Label htmlFor="auth-code" className="font-medium">Step 2: Enter Authorization Code</Label>
                <Input
                  id="auth-code"
                  value={auth_code}
                  onChange={(e) => set_auth_code(e.target.value)}
                  placeholder="Paste the code from the redirect URL"
                />
                <p className="text-xs text-muted-foreground">
                  After authorizing, you&apos;ll be redirected. Copy the <code>code=...</code> value from the URL.
                </p>
              </div>
            </div>
            
            <DialogFooter>
              <Button variant="outline" onClick={() => set_connect_dialog_open(false)}>
                Cancel
              </Button>
              <Button 
                onClick={handle_exchange_code}
                disabled={!auth_code.trim() || exchange_code.isPending}
              >
                {exchange_code.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>
                    <CheckCircle className="mr-2 h-4 w-4" />
                    Connect Account
                  </>
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    )
  }

  // Full mode - show card with all details
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Link2 className="h-5 w-5" />
          GoHighLevel Integration
        </CardTitle>
        <CardDescription>
          Connect your GoHighLevel account to sync contacts automatically.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Connected Accounts */}
        {accounts && accounts.length > 0 ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label className="font-medium">Connected Accounts</Label>
              <Button 
                variant="ghost" 
                size="sm"
                onClick={() => refetch_accounts()}
                disabled={accounts_loading}
              >
                <RefreshCw className={`h-4 w-4 mr-1 ${accounts_loading ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
            
            <div className="space-y-2">
              {accounts.map((account) => (
                <div 
                  key={account.id}
                  className={`p-3 rounded-md border ${
                    selected_location_id === account.location_id 
                      ? 'border-blue-500 bg-blue-50' 
                      : 'border-gray-200'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">
                          {account.display_name || account.location_id}
                        </span>
                        {account.is_default && (
                          <Badge variant="secondary" className="text-xs">
                            <Star className="h-3 w-3 mr-1" />
                            Default
                          </Badge>
                        )}
                        {account.is_active ? (
                          <Badge variant="default" className="bg-green-600 text-xs">Active</Badge>
                        ) : (
                          <Badge variant="destructive" className="text-xs">Expired</Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        Location: {account.location_id}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {!account.is_default && (
                        <Button 
                          variant="ghost" 
                          size="sm"
                          onClick={() => handle_set_default(account.id)}
                          disabled={set_default.isPending}
                        >
                          Set Default
                        </Button>
                      )}
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => {
                          if (on_account_selected) {
                            on_account_selected(account)
                          }
                        }}
                      >
                        Select
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>No Accounts Connected</AlertTitle>
            <AlertDescription>
              Connect a GoHighLevel account to enable contact synchronization.
            </AlertDescription>
          </Alert>
        )}

        {/* Connect New Account */}
        <div className="pt-4 border-t">
          <Label className="font-medium">Connect New Account</Label>
          <p className="text-sm text-muted-foreground mb-3">
            Generate an authorization URL, complete the OAuth flow, then paste the code below.
          </p>
          
          <div className="space-y-3">
            {/* Step 1 */}
            <div className="flex gap-2">
              <Button 
                onClick={handle_get_auth_url} 
                disabled={get_auth_url.isPending}
                className="flex-1"
              >
                {get_auth_url.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <ExternalLink className="mr-2 h-4 w-4" />
                    1. Get Authorization URL
                  </>
                )}
              </Button>
            </div>
            
            {auth_url && (
              <div className="p-3 bg-muted rounded-md">
                <div className="flex items-center gap-2 mb-2">
                  <a 
                    href={auth_url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline flex items-center gap-1"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Open GoHighLevel Authorization
                  </a>
                  <Button 
                    variant="ghost" 
                    size="sm"
                    onClick={() => copy_to_clipboard(auth_url)}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Complete authorization, then copy the <code>code</code> from the redirect URL.
                </p>
              </div>
            )}
            
            {/* Step 2 */}
            <div className="flex gap-2">
              <Input
                value={auth_code}
                onChange={(e) => set_auth_code(e.target.value)}
                placeholder="2. Paste authorization code here"
                className="flex-1"
              />
              <Button 
                onClick={handle_exchange_code}
                disabled={!auth_code.trim() || exchange_code.isPending}
              >
                {exchange_code.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    <CheckCircle className="mr-2 h-4 w-4" />
                    Connect
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

