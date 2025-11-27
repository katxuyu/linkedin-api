import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import { AuthProvider } from "@/lib/context/AuthContext"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "@/components/ui/sonner"
import Providers from "./providers"
import { GlobalTwoFactorModal } from "@/components/forms/GlobalTwoFactorModal"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "LinkedIn Campaign Manager",
  description: "Manage your LinkedIn outreach campaigns",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          {children}
          <GlobalTwoFactorModal />
          <Toaster />
        </Providers>
      </body>
    </html>
  )
}
