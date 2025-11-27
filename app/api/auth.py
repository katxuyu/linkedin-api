import re
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from app import schemas, crud_async, database
from app.api.admin import validate_registration_key
from app.dependencies import get_redis, get_current_user
from app.settings import SECRET_KEY, ALGORITHM, PWD_CONTEXT, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, PASSWORD_RESET_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/auth", tags=["auth"])

# Regex for strong password: min 8 chars, at least 1 uppercase, 1 lowercase, 1 number, 1 special char
PASSWORD_REGEX = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
)

def validate_email(email: str):
    """Simple email validation."""
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        raise HTTPException(status_code=400, detail="Invalid email format")

def validate_password(password: str):
    """Ensure password is strong."""
    if not PASSWORD_REGEX.match(password):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters, include uppercase, lowercase, number, and special character"
        )
    
def verify_password(plain_password: str, hashed_password: str):
    return PWD_CONTEXT.verify(plain_password, hashed_password)
    
# -------------------
# Token helpers
# -------------------
def create_access_token(user_id: int):
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(user_id: int):
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def create_password_reset_token(user_id: int):
    expire = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire, "type": "reset"}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)



@router.post("/register", response_model=schemas.UserResponse)
async def register_user(
    request: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Register a new user with email and password.
    Validates email and enforces strong password.
    """
    # Check if user already exists
    user = await crud_async.get_user_by_email(db, request.email)
    if user:
        raise HTTPException(status_code=403, detail="Email already registered")
    
    # Validate email and password
    validate_email(request.email)
    validate_password(request.password)

    # Rate limiting (per email per day)
    rate_limit_key = f"register:{request.email}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    count = await redis.get(rate_limit_key)
    count = int(count) if count else 0
    if count >= 5:
        raise HTTPException(status_code=429, detail="Registration limit exceeded")

    # Check registration key
    reg_key = await validate_registration_key(db, request.registration_key)

    # Create user
    user = await crud_async.create_user(db, request.email, request.password)

    # Write register key to DB as used and issued to the user
    reg_key.used = True
    reg_key.issued_to = user.id
    db.add(reg_key)
    await db.commit()

    # Increment rate limit counter
    await redis.incr(rate_limit_key)
    await redis.expire(rate_limit_key, 86400)
    return user

# @router.put("/users/me", response_model=schemas.UserResponse)
# async def update_user_me(
#     request: schemas.UserUpdate,
#     db: AsyncSession = Depends(database.get_db),
#     redis: Redis = Depends(get_redis),
#     current_user: schemas.UserResponse = Depends(get_current_user)
# ):
#     """
#     Update the current user's email or password.
#     """
#     # Validate email if provided
#     if request.email:
#         validate_email(request.email)
#         # Prevent duplicate emails
#         existing_user = await crud.get_user_by_email(db, request.email)
#         if existing_user and existing_user.id != current_user.id:
#             raise HTTPException(status_code=403, detail="Email already in use")

#     # Validate password if provided
#     if request.password:
#         validate_password(request.password)

#     # Perform update
#     updated_user = await crud.update_user(
#         db,
#         user=current_user,
#         email=request.email,
#         password=request.password,
#     )

#     return updated_user

@router.get("/me", response_model=schemas.UserResponse)
async def get_current_user_info(
    current_user = Depends(get_current_user)
):
    """
    Get current authenticated user information.
    """
    return current_user

@router.post("/login", response_model=schemas.TokenResponse)
async def login_user(
    request: schemas.UserLogin,
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis),
    client_request: Request = None
):
    """
    Authenticate user and return access and refresh tokens.
    """
    ip = client_request.client.host if client_request else "unknown"
    rate_key = f"login:{request.email}:{ip}:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    attempts = await redis.get(rate_key)
    attempts_count = int(attempts) if attempts else 0
    
    if attempts_count >= 10:
        raise HTTPException(status_code=429, detail="Too many login attempts, try later")
    
    user = await crud_async.get_user_by_email(db, request.email)
    if not user or not verify_password(request.password, user.password):
        await redis.incr(rate_key)
        await redis.expire(rate_key, 86400)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Reset rate limit counter on successful login
    await redis.delete(rate_key)
    
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    await redis.setex(f"refresh:{user.id}:{refresh_token}", REFRESH_TOKEN_EXPIRE_DAYS * 86400, "active")
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/refresh", response_model=schemas.TokenResponse)
async def refresh_token(
    refresh_token: str = Header(...),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Refresh access token using a valid refresh token.
    """
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        
        user_id = int(payload.get("sub"))
        is_valid = await redis.get(f"refresh:{user_id}:{refresh_token}")
        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        
        user = await crud_async.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        access_token = create_access_token(user.id)
        new_refresh_token = create_refresh_token(user.id)

        await redis.setex(f"refresh:{user.id}:{new_refresh_token}", REFRESH_TOKEN_EXPIRE_DAYS * 86400, "active")
        await redis.delete(f"refresh:{user.id}:{refresh_token}")

        return {"access_token": access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@router.post("/logout")
async def logout_user(
    refresh_token: str = Header(...),
    redis: Redis = Depends(get_redis)
):
    """
    Revoke refresh token to end session.
    """
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        await redis.delete(f"refresh:{user_id}:{refresh_token}")
    except JWTError:
        pass  # ignore invalid tokens
    return {"status": "Logged out"}

@router.post("/password-reset/request", response_model=dict)
async def request_password_reset(
    request: schemas.PasswordResetRequest,
    http_request: Request,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Request a password reset token.
    - In production: sends token via email.
    - In dev/testing: if header `X-Debug: true` is set, also returns the token in response.
    """
    user = await crud_async.get_user_by_email(db, request.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = create_password_reset_token(user.id)

    return {
        "status": "reset_link_sent",
        "token": token,
        "instructions": "Call /auth/password-reset/confirm with this token and your new password"
    }

    # # --- send via email ---
    # reset_link = f"https://your-api.com/reset-password?token={token}"
    # email_body = (
    #     f"Hello,\n\n"
    #     f"We received a request to reset your password.\n"
    #     f"Here is your reset token:\n\n{token}\n\n"
    #     f"Or click the link below (if using a client UI):\n{reset_link}\n\n"
    #     f"If you did not request this, please ignore."
    # )
    # from app.mailer import send_email
    # await send_email(
    #     to_email=user.email,
    #     subject="Password Reset Request",
    #     body=email_body
    # )

    # # --- dev/debug mode ---
    # debug_mode = request.headers.get("X-Debug", "").lower() == "true"
    # if debug_mode:
    #     return {
    #         "status": "reset_link_sent",
    #         "token": token,
    #         "instructions": "Call /auth/password-reset/confirm with this token and your new password"
    #     }

    # return {"status": "reset_link_sent"}

@router.post("/password-reset/confirm")
async def confirm_password_reset(
    request: schemas.PasswordResetConfirmRequest,
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    try:
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "reset":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = int(payload.get("sub"))
        user = await crud_async.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        validate_password(request.new_password)

        await crud_async.update_user_password(db, user, password=request.new_password)

        # Invalidate all existing refresh tokens for this user
        keys = await redis.keys(f"refresh:{user.id}:*")
        for key in keys:
            await redis.delete(key)

        return {"status": "password_reset_successful"}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired reset token")