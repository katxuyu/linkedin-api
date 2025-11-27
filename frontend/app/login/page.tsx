"use client"

import { Suspense, useState } from "react"
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from 'sonner'

function LoginPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { login, is_loading } = useAuth()
  const [email, set_email] = useState('')
  const [password, set_password] = useState('')
  const [is_submitting, set_is_submitting] = useState(false)

  const handle_submit = async (e: React.FormEvent) => {
    e.preventDefault()
    set_is_submitting(true)

    try {
      await login(email, password)
      toast.success('Login successful')
      
      // Redirect to the original page or default to campaigns
      const redirect = searchParams.get('redirect') || '/campaigns'
      router.push(redirect)
    } catch (error: unknown) {
      console.error('Login error:', error)
      const message =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        (error instanceof Error ? error.message : 'Login failed. Please check your credentials.')
      toast.error(message)
    } finally {
      set_is_submitting(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Admin Login</CardTitle>
          <CardDescription>
            Sign in to manage LinkedIn campaigns
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handle_submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="admin@example.com"
                value={email}
                onChange={(e) => set_email(e.target.value)}
                required
                disabled={is_submitting}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => set_password(e.target.value)}
                required
                disabled={is_submitting}
              />
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={is_submitting || is_loading}
            >
              {is_submitting ? 'Signing in...' : 'Sign In'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center">Loading…</div>}>
      <LoginPageContent />
    </Suspense>
  )
}




