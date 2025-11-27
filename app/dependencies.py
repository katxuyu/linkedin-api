from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis as RedisAsync
from app import crud_async, database
from app import redis
from app.schemas import UserResponse
from app.settings import SECRET_KEY, ALGORITHM

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(database.get_db)
) -> UserResponse:
    """
    Extract and validate JWT from the Authorization header.
    Returns a Pydantic UserResponse to avoid SQLAlchemy lazy loading issues.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    user = await crud_async.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    # Convert ORM model to Pydantic to avoid lazy loading issues
    return UserResponse.model_validate(user)
    
# Admin check is now handled directly in admin endpoints
# This provides more flexibility and clearer error messages

# Dependency for FastAPI
async def get_redis() -> RedisAsync:
    if not redis.redis_client_async:
        raise RuntimeError("Redis asynchronous client is not initialized")
    return redis.redis_client_async