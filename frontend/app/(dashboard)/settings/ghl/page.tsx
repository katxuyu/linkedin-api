'use client'

import React, { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { GHLConnectionManager } from '@/components/ghl/GHLConnectionManager'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Link2 } from 'lucide-react'

export default function GHLSettingsPage() {
  const { accessToken, user } = useAuth()
  const router = useRouter()

  // Admin-only page
  useEffect(() => {
    if (user && !user.is_admin) {
      router.push('/campaigns')
    }
  }, [user, router])

  if (!user?.is_admin) {
    return null
  }

  if (!accessToken) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Link2 className="h-8 w-8" />
          GoHighLevel Integration
        </h1>
        <p className="text-muted-foreground mt-2">
          Connect your GoHighLevel accounts to automatically sync LinkedIn contacts.
        </p>
      </div>

      <GHLConnectionManager 
        client_token={accessToken}
        compact={false}
      />

      <Card>
        <CardHeader>
          <CardTitle>How It Works</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <h4 className="font-medium">1. Connect Your Account</h4>
            <p className="text-sm text-muted-foreground">
              Click &quot;Get Authorization URL&quot; to initiate the OAuth flow with GoHighLevel.
            </p>
          </div>
          
          <div className="space-y-2">
            <h4 className="font-medium">2. Authorize Access</h4>
            <p className="text-sm text-muted-foreground">
              Follow the link to GoHighLevel and authorize the application. You&apos;ll be asked to select
              a location to connect.
            </p>
          </div>
          
          <div className="space-y-2">
            <h4 className="font-medium">3. Copy the Authorization Code</h4>
            <p className="text-sm text-muted-foreground">
              After authorization, you&apos;ll be redirected. Copy the <code className="bg-muted px-1 rounded">code</code> parameter from the
              URL and paste it in the field above.
            </p>
          </div>
          
          <div className="space-y-2">
            <h4 className="font-medium">4. Start Syncing</h4>
            <p className="text-sm text-muted-foreground">
              Once connected, your LinkedIn profiles can sync accepted connections directly to your
              GoHighLevel contacts.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

