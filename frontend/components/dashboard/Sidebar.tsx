'use client'

import { useState, useEffect } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { LayoutDashboard, Users, UserCircle, Menu, X, ShieldCheck, Link2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/context/AuthContext'

export function Sidebar() {
  const [is_mobile_open, set_is_mobile_open] = useState(false)
  const [is_mobile, set_is_mobile] = useState(false)
  const pathname = usePathname()
  const { user, logout } = useAuth()

  useEffect(() => {
    const check_mobile = () => {
      const mobile = window.innerWidth < 1024
      set_is_mobile(mobile)
      if (!mobile) {
        set_is_mobile_open(false)
      }
    }
    
    check_mobile()
    window.addEventListener('resize', check_mobile)
    return () => window.removeEventListener('resize', check_mobile)
  }, [])

  const toggle_mobile = () => {
    set_is_mobile_open(!is_mobile_open)
  }

  const nav_items = [
    {
      href: '/campaigns',
      label: 'Campaigns',
      icon: LayoutDashboard,
    },
    {
      href: '/profiles',
      label: 'Profiles',
      icon: UserCircle,
    },
    {
      href: '/verification',
      label: 'Verification',
      icon: ShieldCheck,
    },
  ]

  if (user?.is_admin) {
    nav_items.push({
      href: '/clients',
      label: 'Clients',
      icon: Users,
    })
    nav_items.push({
      href: '/settings/ghl',
      label: 'GoHighLevel',
      icon: Link2,
    })
  }

  const is_active = (href: string) => {
    if (href === '/campaigns' || href === '/profiles' || href === '/clients' || href === '/verification' || href === '/settings/ghl') {
      return pathname?.startsWith(href) ?? false
    }
    return pathname === href
  }

  const is_collapsed = is_mobile && !is_mobile_open

  return (
    <>
      {is_mobile && (
        <div
          className={cn(
            'fixed inset-0 bg-black/50 z-40 transition-opacity',
            is_mobile_open ? 'opacity-100' : 'opacity-0 pointer-events-none'
          )}
          onClick={() => set_is_mobile_open(false)}
        />
      )}
      <div
        className={cn(
          'fixed left-0 top-0 z-50 h-screen bg-white border-r border-gray-200 transition-all duration-300',
          is_mobile
            ? is_mobile_open
              ? 'w-64 translate-x-0'
              : '-translate-x-full w-64'
            : 'w-64'
        )}
      >
        <div className="flex flex-col h-full">
          <div className="flex items-center justify-between p-4 border-b border-gray-200">
            <Link href="/campaigns" className="text-xl font-bold text-gray-900">
              LinkedIn Manager
            </Link>
            {is_mobile && (
              <Button
                variant="ghost"
                size="icon"
                onClick={toggle_mobile}
              >
                <X className="h-5 w-5" />
              </Button>
            )}
          </div>

          <nav className="flex-1 p-4 space-y-2">
            {nav_items.map((item) => {
              const Icon = item.icon
              const active = is_active(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => is_mobile && set_is_mobile_open(false)}
                  className={cn(
                    'flex items-center gap-3 px-3 py-2 rounded-lg transition-colors',
                    active
                      ? 'bg-gray-100 text-gray-900 font-medium'
                      : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  )}
                >
                  <Icon className="h-5 w-5 flex-shrink-0" />
                  <span>{item.label}</span>
                </Link>
              )
            })}
          </nav>

          {user && (
            <div className="p-4 border-t border-gray-200">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-700 truncate">{user.email}</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={logout}
                className="w-full"
              >
                Logout
              </Button>
            </div>
          )}
        </div>
      </div>
      {is_mobile && !is_mobile_open && (
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle_mobile}
          className="fixed left-2 top-2 z-50 bg-white shadow-md"
        >
          <Menu className="h-5 w-5" />
        </Button>
      )}
    </>
  )
}

