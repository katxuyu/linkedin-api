# LinkedIn Campaign Manager - Frontend

React/Next.js frontend application for managing LinkedIn outreach campaigns.

## Features

- **Campaign Wizard**: Step-by-step guided flow for creating campaigns
  - Client selection
  - LinkedIn profile setup
  - Campaign template builder
  - Contact import (manual CSV or LinkedIn search)
  - Review and launch

- **Campaign Dashboard**: View and manage all campaigns with filtering

- **Campaign Editor**: Edit campaign details and monitor progress

- **Verification Modal**: Handle LinkedIn 2FA verification
- **Verification Requests Tab**: Real-time monitor for pending/errored LinkedIn code requests with inline submission

## Getting Started

### Development Mode

```bash
npm install
npm run dev
```

The application will be available at `http://localhost:3000`.

### Docker Development

```bash
cd ..
docker-compose -f docker-compose.dev.yml up frontend
```

The frontend container now defaults to `http://localhost:8088` for API calls (via `NEXT_PUBLIC_API_URL`). Override the value when you need to point at a different backend:

```bash
NEXT_PUBLIC_API_URL=https://your-backend.example.com docker-compose -f docker-compose.dev.yml up frontend
```

### Environment Variables

Create a `.env.local` file:

```
NEXT_PUBLIC_API_URL=http://localhost:8088
```

## Project Structure

```
frontend/
├── app/                          # Next.js App Router
│   ├── (dashboard)/             # Protected dashboard routes
│   │   ├── campaigns/           # Campaign management
│   │   │   ├── page.tsx        # Campaign list
│   │   │   ├── new/page.tsx    # Campaign wizard
│   │   │   └── [id]/page.tsx   # Campaign details
│   │   └── layout.tsx          # Dashboard layout
│   ├── login/                   # Login page
│   └── layout.tsx              # Root layout
├── components/
│   ├── wizard/                  # Wizard components
│   │   ├── WizardContainer.tsx
│   │   └── steps/              # Wizard steps
│   ├── dashboard/              # Dashboard components
│   ├── forms/                  # Form components
│   └── ui/                     # shadcn/ui components
├── lib/
│   ├── api/                    # API client functions
│   ├── context/                # React Context providers
│   ├── hooks/                  # Custom React hooks
│   └── utils/                  # Utility functions
└── types/                      # TypeScript type definitions
```

## Technology Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **UI Components**: shadcn/ui
- **State Management**: React Context + React Query
- **Forms**: React Hook Form + Zod
- **HTTP Client**: Axios

## Key Components

### Wizard Steps

1. **Client Selection**: Choose or create a client
2. **LinkedIn Profile**: Select or add LinkedIn outreach profile
3. **Campaign Template**: Build campaign with multiple steps and messages
4. **Contact Import**: Add targets manually or import from LinkedIn search
5. **Review & Launch**: Review and launch the campaign

### API Integration

All API calls are made through the centralized API client (`lib/api/client.ts`) which handles:
- Authentication token management
- Automatic token refresh
- Request/response interceptors
- Error handling

### Authentication

The app uses JWT-based authentication with:
- Login page for admin users
- Protected routes via middleware
- Automatic token refresh
- Logout functionality

## Verification Requests Tab

- Located under **Verification** in the sidebar (protected dashboard routes)
- Polls the backend every 8 seconds for:
  - Pending login code requests that belong to the logged-in user
  - Recently errored/expired requests with full attempt history
- Allows operators to:
  - Store their initials/name locally (persisted via `localStorage`)
  - Submit verification codes inline; submissions are tagged with the operator metadata
  - Inspect attempts, metadata, and error details for troubleshooting
- Requires the backend endpoints added under `/internal/verification/code-requests`

## Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run start` - Start production server
- `npm run lint` - Run ESLint

## Production Deployment

Build the production image:

```bash
docker build -f Dockerfile.prod -t linkedin-frontend:prod .
```

Run the production container:

```bash
docker run -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://api.example.com linkedin-frontend:prod
```

## Notes

- The frontend expects the backend API to be running at the URL specified in `NEXT_PUBLIC_API_URL`
- CORS must be configured on the backend to allow requests from the frontend origin
- Admin credentials default to `admin@admin.com` / `ChangeMe123!`
