# LinkedIn Microservice

A Flask-based microservice that handles LinkedIn automation tasks using Playwright. This service runs separately from the main FastAPI backend to avoid async/sync conflicts.

## Features

- **Session Management**: Create, login, and manage LinkedIn sessions
- **Profile Operations**: Fetch LinkedIn profile information
- **Connection Requests**: Send connection requests with custom notes
- **Messaging**: Send messages to LinkedIn profiles
- **Chat History**: Retrieve all messages from conversations
- **Cookie Management**: Save and restore session cookies

## API Endpoints

### Health Check
- `GET /health` - Check service health

### Session Management
- `POST /session/create` - Create a new LinkedIn session
- `POST /session/{session_key}/login` - Login to LinkedIn
- `POST /session/{session_key}/logout` - Logout and close session
- `GET /sessions` - List all active sessions

### Profile Operations
- `GET /session/{session_key}/profile/{profile_url}` - Fetch profile information

### Connection Requests
- `POST /session/{session_key}/connection/{profile_url}` - Send connection request

### Messaging
- `POST /session/{session_key}/message/{profile_url}` - Send message
- `GET /session/{session_key}/messages/{profile_url}` - Get all messages

### Session Data
- `GET /session/{session_key}/cookies` - Get session cookies
- `GET /session/{session_key}/user-agent` - Get user agent

## Installation

### Prerequisites
- Python 3.11+
- Playwright browsers installed
- Access to main backend database

### Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
playwright install-deps chromium

# Set environment variables
export LINKEDIN_SERVICE_PORT=5001
export MAIN_BACKEND_URL=http://localhost:8000
export PYTHONPATH=/app:/path/to/main/backend

# Start the service
python app.py
```

### Docker Setup
```bash
# Build and run with Docker Compose
docker-compose up linkedin-microservice
```

## Configuration

### Environment Variables
- `LINKEDIN_SERVICE_PORT`: Port for the Flask service (default: 5001)
- `MAIN_BACKEND_URL`: URL of the main backend (default: http://localhost:8000)
- `PYTHONPATH`: Python path including main backend modules

### Session Management
- Sessions are stored in memory during runtime
- Session data (cookies, user agent) is saved to the main backend database
- Sessions are automatically cleaned up on logout

## Usage

### Creating a Session
```python
import requests

# Create session
response = requests.post('http://localhost:5001/session/create', json={
    'email': 'user@example.com',
    'password': 'password',
    'outreach_profile_id': 1,
    'cookies': None,  # Optional
    'user_agent': None  # Optional
})

session_key = response.json()['session_key']
```

### Login
```python
# Login to LinkedIn
response = requests.post(f'http://localhost:5001/session/{session_key}/login')
```

### Send Connection Request
```python
# Send connection request
response = requests.post(f'http://localhost:5001/session/{session_key}/connection/https://linkedin.com/in/profile', json={
    'note': 'Custom connection note'
})
```

### Send Message
```python
# Send message
response = requests.post(f'http://localhost:5001/session/{session_key}/message/https://linkedin.com/in/profile', json={
    'message': 'Hello, how are you?'
})
```

### Get Messages
```python
# Get all messages
response = requests.get(f'http://localhost:5001/session/{session_key}/messages/https://linkedin.com/in/profile')
messages = response.json()['messages']
```

## Integration with Main Backend

The main backend uses the `LinkedInMicroserviceClient` to communicate with this service:

```python
from app.services.session_manager_microservice import LinkedInSessionManager

# Initialize session manager
session_manager = LinkedInSessionManager("http://localhost:5001")

# Get LinkedIn service
linkedin_service = session_manager.get_service(outreach_profile_id)

# Use the service
linkedin_service.start()
profile_data = linkedin_service.fetch_profile_info(profile_url)
linkedin_service.close()
```

## Error Handling

All endpoints return JSON responses with a `status` field:
- `"success"`: Operation completed successfully
- `"error"`: Operation failed with error details

Example error response:
```json
{
    "status": "error",
    "error": "Session not found"
}
```

## Monitoring

### Health Check
The service provides a health check endpoint at `/health` that returns:
- Service status
- Number of active sessions
- Timestamp

### Logging
The service logs all operations with appropriate log levels:
- `INFO`: Normal operations
- `WARNING`: Non-critical issues
- `ERROR`: Critical errors

## Security Considerations

- Sessions are stored in memory only
- No persistent storage of passwords
- Session keys are used for authentication
- CORS is enabled for cross-origin requests

## Troubleshooting

### Common Issues

1. **Playwright Browser Not Found**
   ```bash
   playwright install chromium
   playwright install-deps chromium
   ```

2. **Import Errors**
   - Ensure `PYTHONPATH` includes the main backend directory
   - Check that all dependencies are installed

3. **Session Not Found**
   - Sessions are stored in memory and lost on restart
   - Recreate sessions after service restart

4. **Login Failures**
   - Check LinkedIn credentials
   - Verify network connectivity
   - Check for LinkedIn rate limiting

### Debug Mode
Set `FLASK_DEBUG=True` for detailed error messages and auto-reload.

## Performance

- Sessions are stored in memory for fast access
- Playwright browsers are reused within sessions
- Automatic cleanup of inactive sessions
- Configurable session timeout

## Future Enhancements

- [ ] Persistent session storage
- [ ] Session pooling
- [ ] Rate limiting
- [ ] Metrics and monitoring
- [ ] Horizontal scaling support
