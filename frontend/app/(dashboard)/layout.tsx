'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/context/AuthContext'
import { Sidebar } from '@/components/dashboard/Sidebar'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const { is_authenticated, is_loading } = useAuth()

  useEffect(() => {
    if (!is_loading && !is_authenticated) {
      router.push('/login')
    }
  }, [is_authenticated, is_loading, router])

  if (is_loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  if (!is_authenticated) {
    return null
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <Sidebar />
      <main className="flex-1 lg:ml-64 transition-all duration-300">
        <div className="p-6 lg:p-10">
          {children}
        </div>
      </main>
    </div>
  )
}





