import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// Routes that don't require authentication
const PUBLIC_ROUTES = ['/login', '/register']

// Routes that should redirect to dashboard if already authenticated
const AUTH_ROUTES = ['/login', '/register']

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  
  // Get the auth token from cookie
  const token = request.cookies.get('access_token')?.value
  const isAuthenticated = !!token
  
  // Debug logging
  console.log(`[Middleware] ${pathname} | auth: ${isAuthenticated} | token: ${token ? 'yes' : 'no'}`)
  
  // Check if this is a public route
  const isPublicRoute = PUBLIC_ROUTES.some(route => pathname.startsWith(route))
  
  // Check if this is an auth route (login/register)
  const isAuthRoute = AUTH_ROUTES.some(route => pathname.startsWith(route))
  
  // Skip middleware for static files and API routes
  if (
    pathname.startsWith('/_next') ||
    pathname.startsWith('/api') ||
    pathname.includes('.') // static files
  ) {
    return NextResponse.next()
  }
  
  // If user is authenticated and trying to access auth routes, redirect to dashboard
  if (isAuthenticated && isAuthRoute) {
    return NextResponse.redirect(new URL('/campaigns', request.url))
  }
  
  // If user is not authenticated and trying to access protected routes
  if (!isAuthenticated && !isPublicRoute) {
    // Store the original URL to redirect back after login
    const loginUrl = new URL('/login', request.url)
    if (pathname !== '/') {
      loginUrl.searchParams.set('redirect', pathname)
    }
    return NextResponse.redirect(loginUrl)
  }
  
  return NextResponse.next()
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder
     */
    '/((?!_next/static|_next/image|favicon.ico|public).*)',
  ],
}

