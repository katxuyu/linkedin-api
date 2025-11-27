'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'

export default function Home() {
  const router = useRouter()
  const { is_authenticated, is_loading } = useAuth()

  useEffect(() => {
    if (!is_loading) {
      if (is_authenticated) {
        router.push('/campaigns')
      } else {
        router.push('/login')
      }
    }
  }, [is_authenticated, is_loading, router])

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900 mx-auto"></div>
        <p className="mt-4 text-gray-600">Loading...</p>
      </div>
    </div>
  )
}
