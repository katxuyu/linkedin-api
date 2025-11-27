#!/bin/bash

set -e

echo "Stopping existing containers..."
docker-compose -f docker-compose.prod.yml down

echo "Building Docker images..."
docker-compose -f docker-compose.prod.yml build --no-cache

echo "Starting services..."
docker-compose -f docker-compose.prod.yml up -d

echo "Waiting for services to start..."
sleep 30

echo "Checking service status..."
docker-compose -f docker-compose.prod.yml ps

echo "Performing health check..."

if curl -f http://localhost > /dev/null 2>&1; then
    echo "Frontend is reachable on port 80"
else
    echo "Frontend health check failed"
    exit 1
fi

if curl -f http://localhost/api/health > /dev/null 2>&1; then
    echo "Backend API is reachable"
else
    echo "Backend API health check failed"
    exit 1
fi

echo "Deployment completed successfully!"
echo "Frontend should be accessible at: http://your-server-ip"
echo "API endpoints available at: http://your-server-ip/api/"
