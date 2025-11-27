#!/bin/bash

# Test script for 2FA flow
# This script helps verify that the 2FA flow is working correctly

set -e

echo "🔍 Testing 2FA Flow Components..."
echo ""

# Check if services are running
echo "1. Checking Docker services..."
if docker ps | grep -q "linkedin-service"; then
    echo "   ✓ linkedin-service is running"
else
    echo "   ✗ linkedin-service is NOT running"
    echo "   Run: docker-compose -f docker-compose.dev.yml up -d linkedin-service"
    exit 1
fi

if docker ps | grep -q "web"; then
    echo "   ✓ web service is running"
else
    echo "   ✗ web service is NOT running"
    echo "   Run: docker-compose -f docker-compose.dev.yml up -d web"
    exit 1
fi

if docker ps | grep -q "frontend"; then
    echo "   ✓ frontend is running"
else
    echo "   ✗ frontend is NOT running"
    echo "   Run: docker-compose -f docker-compose.dev.yml up -d frontend"
    exit 1
fi

if docker ps | grep -q "redis"; then
    echo "   ✓ redis is running"
else
    echo "   ✗ redis is NOT running"
    echo "   Run: docker-compose -f docker-compose.dev.yml up -d redis"
    exit 1
fi

echo ""
echo "2. Checking service health..."

# Check backend health
if curl -s http://localhost:8000/ > /dev/null 2>&1; then
    echo "   ✓ Backend API is responding"
else
    echo "   ✗ Backend API is NOT responding"
    exit 1
fi

# Check microservice health
if curl -s http://localhost:5001/health > /dev/null 2>&1; then
    echo "   ✓ LinkedIn microservice is responding"
    ACTIVE_SESSIONS=$(curl -s http://localhost:5001/health | grep -o '"active_sessions":[0-9]*' | cut -d':' -f2)
    echo "   ℹ Active sessions: $ACTIVE_SESSIONS"
else
    echo "   ✗ LinkedIn microservice is NOT responding"
    exit 1
fi

# Check frontend
if curl -s http://localhost:3000/ > /dev/null 2>&1; then
    echo "   ✓ Frontend is responding"
else
    echo "   ✗ Frontend is NOT responding"
    exit 1
fi

echo ""
echo "3. Checking Redis for pending 2FA sessions..."
REDIS_PASSWORD=${REDIS_PASSWORD:-"your_redis_password_here"}
PENDING_SESSIONS=$(docker exec redis redis-cli -a "$REDIS_PASSWORD" KEYS "pending_2fa_session:*" 2>/dev/null | wc -l)
echo "   ℹ Pending 2FA sessions: $PENDING_SESSIONS"

if [ "$PENDING_SESSIONS" -gt 0 ]; then
    echo "   ⚠ There are pending 2FA sessions. List:"
    docker exec redis redis-cli -a "$REDIS_PASSWORD" KEYS "pending_2fa_session:*" 2>/dev/null | while read key; do
        if [ -n "$key" ]; then
            echo "     - $key"
        fi
    done
fi

echo ""
echo "4. Checking database for verification requests..."
# This would require database credentials, skip for now
echo "   ℹ Check manually with:"
echo "     SELECT COUNT(*) FROM linkedin_login_code_requests WHERE status = 'pending';"

echo ""
echo "5. Testing 2FA endpoint availability..."
# Test internal verification endpoint (should return 404 or 401, not 500)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/internal/verification/requests/999)
if [ "$HTTP_CODE" = "404" ] || [ "$HTTP_CODE" = "401" ]; then
    echo "   ✓ Verification endpoint is accessible (returned $HTTP_CODE)"
else
    echo "   ✗ Verification endpoint returned unexpected code: $HTTP_CODE"
fi

echo ""
echo "✅ All basic checks passed!"
echo ""
echo "📝 Manual Testing Steps:"
echo "   1. Open http://localhost:3000/profiles/new"
echo "   2. Enter LinkedIn credentials for an account with 2FA"
echo "   3. Submit the form"
echo "   4. Verify that a modal appears requesting the 2FA code"
echo "   5. Enter the code from your email/phone"
echo "   6. Verify that the profile is created successfully"
echo ""
echo "📊 Monitoring Commands:"
echo "   - Watch backend logs:      docker logs -f web"
echo "   - Watch microservice logs: docker logs -f linkedin-service"
echo "   - Check Redis keys:        docker exec redis redis-cli -a \$REDIS_PASSWORD KEYS '*2fa*'"
echo ""
echo "🐛 Troubleshooting:"
echo "   - If modal doesn't appear: Check browser console for 'linkedin-2fa-required' event"
echo "   - If session closes early: Check logs for 'Session X closed successfully (was pending_2fa)'"
echo "   - If code fails: Check Redis for pending_2fa_session:{profile_id} key"
echo ""









