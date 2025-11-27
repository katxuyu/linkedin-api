# Campaign Setup UI - Setup Guide

This guide walks you through setting up and running the LinkedIn Campaign Manager frontend.

## Prerequisites

- Node.js 18+ installed
- Backend API running (see main project README)
- Docker (optional, for containerized deployment)

## Quick Start (Local Development)

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Configure Environment

Create `.env.local`:

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:8088" > .env.local
```

### 3. Start Development Server

```bash
npm run dev
```

The frontend will be available at `http://localhost:3000`.

### 4. Login

Navigate to `http://localhost:3000/login` and login with:
- Email: `admin@admin.com`
- Password: `ChangeMe123!`

## Docker Deployment

### Development Mode

From the project root:

```bash
docker-compose -f docker-compose.dev.yml up frontend nginx
```

This will start:
- Frontend at `http://localhost:3000`
- Backend API (via Nginx) at `http://localhost:8088`

### Production Mode

1. Build the production image:

```bash
cd frontend
docker build -f Dockerfile.prod -t linkedin-frontend:prod .
```

2. Run the container:

```bash
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_API_URL=http://your-api-url.com \
  linkedin-frontend:prod
```

## Full Stack Setup

To run the entire application stack:

```bash
# From project root
docker-compose -f docker-compose.dev.yml up
```

This starts:
- Backend API (FastAPI) - port 8000
- Frontend (Next.js) - port 3000
- Nginx (reverse proxy) - port 8088
- PostgreSQL - port 5435
- Redis - port 6380
- Celery workers
- Celery beat scheduler
- Flower (Celery monitoring) - port 5555
- Streamlit control panel - port 8501
- LinkedIn service - port 5001

### Access Points

- Frontend UI: `http://localhost:3000`
- Backend API (via Nginx): `http://localhost:8088`
- API Documentation: `http://localhost:8088/docs`
- Streamlit Control Panel: `http://localhost:8501`
- Flower (Celery): `http://localhost:5555`

## Using the Campaign Wizard

### Step 1: Select Client

- View list of existing clients
- Search by email
- Create new client with registration key
- Select a client to proceed

### Step 2: LinkedIn Profile

- Select existing LinkedIn profile
- Or add new profile with:
  - LinkedIn email
  - LinkedIn password
  - LinkedIn profile URL
  - Optional: GoHighLevel account ID

### Step 3: Campaign Template

- Select existing template or create new
- Add campaign steps:
  - Connection requests with notes
  - Follow-up messages
  - Set delays between steps
- System automatically detects variables in templates (e.g., `{{first_name}}`)

### Step 4: Contact Import

**Manual Entry:**
- Add targets one by one
- Provide required variables for each target
- Or paste CSV with format: `url,variable1,variable2`

**LinkedIn Search:**
- Paste LinkedIn search URL
- Set max results (1-100)
- Preview results
- Import targets

### Step 5: Review & Launch

- Review all campaign details
- Verify target count and template
- Launch campaign
- Redirects to campaign dashboard

## Troubleshooting

### Frontend won't start

Check:
```bash
# Ensure dependencies are installed
npm install

# Check for port conflicts
lsof -i :3000

# Check environment variables
cat .env.local
```

### Cannot connect to backend

Check:
1. Backend is running: `curl http://localhost:8088/`
2. CORS is configured in `app/main.py`
3. Environment variable is correct: `NEXT_PUBLIC_API_URL`

### Login fails

Check:
1. Backend API is accessible
2. Admin user exists (created automatically on startup)
3. Credentials are correct:
   - Default: `admin@admin.com` / `ChangeMe123!`

### Docker build fails

```bash
# Clean Docker cache
docker system prune -a

# Rebuild without cache
docker-compose -f docker-compose.dev.yml build --no-cache frontend
```

### Changes not reflecting

In development mode:
```bash
# Next.js has hot reload, but sometimes needs restart
npm run dev
```

In Docker:
```bash
# Volumes should sync changes automatically
# If not, restart the container
docker-compose -f docker-compose.dev.yml restart frontend
```

## Development Tips

### API Client

All API calls go through `lib/api/client.ts` which handles:
- Token management
- Automatic refresh
- Error handling

### Adding New API Endpoints

1. Add types to `types/index.ts`
2. Create API function in `lib/api/[module].ts`
3. Create React Query hook in `lib/hooks/[module].ts`
4. Use hook in components

### Adding New Wizard Steps

1. Create component in `components/wizard/steps/`
2. Add to wizard config in `app/(dashboard)/campaigns/new/page.tsx`
3. Update wizard state type in `types/index.ts`

### Styling

- Use Tailwind CSS classes
- Use shadcn/ui components from `components/ui/`
- Follow existing patterns for consistency

## Production Considerations

### Environment Variables

For production, set:
```
NEXT_PUBLIC_API_URL=https://your-production-api.com
```

### Security

- Use HTTPS in production
- Configure proper CORS origins
- Implement rate limiting
- Use secure cookie settings

### Performance

- Next.js automatically optimizes builds
- Images are optimized automatically
- Consider CDN for static assets
- Enable caching headers in Nginx

### Monitoring

- Add error tracking (e.g., Sentry)
- Monitor API response times
- Track user flows and conversions
- Set up health checks

## Support

For issues or questions:
1. Check the main project documentation
2. Review API documentation at `/docs`
3. Check backend logs for API errors
4. Enable verbose logging in development





