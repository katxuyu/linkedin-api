'use client'

import { AuthProvider } from "@/lib/context/AuthContext"
import { TwoFactorProvider } from "@/lib/context/TwoFactorContext"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState } from "react"

export default function Providers({ children }: { children: React.ReactNode }) {
  const [query_client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
        refetchOnWindowFocus: false,
      },
    },
  }))

  return (
    <QueryClientProvider client={query_client}>
      <AuthProvider>
        <TwoFactorProvider>
          {children}
        </TwoFactorProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}





