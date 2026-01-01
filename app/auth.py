from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.config import get_settings
from app.models import TokenData, UserInDB
from app.database import get_database
import logging
import hashlib
import base64

logger = logging.getLogger(__name__)

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


def _prepare_password(password: str) -> bytes:
    """
    Prepare password for bcrypt by hashing with SHA256 first.
    This ensures the password is always under 72 bytes regardless of length.
    Returns base64-encoded SHA256 hash as bytes.
    """
    # Hash the password with SHA256
    password_hash = hashlib.sha256(password.encode('utf-8')).digest()
    # Encode as base64 for bcrypt (44 characters, well under 72 bytes)
    return base64.b64encode(password_hash)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    prepared_password = _prepare_password(plain_password)
    return bcrypt.checkpw(prepared_password, hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    prepared_password = _prepare_password(password)
    hashed = bcrypt.hashpw(prepared_password, bcrypt.gensalt())
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


async def get_user_by_email(email: str, tenant_id: str):
    db = await get_database()
    user_dict = await db.users.find_one({"email": email, "tenant_id": tenant_id})
    if user_dict:
        return UserInDB(**user_dict)
    return None


async def authenticate_user(email: str, password: str, tenant_id: str):
    user = await get_user_by_email(email, tenant_id)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        email: str = payload.get("sub")
        tenant_id: str = payload.get("tenant_id")
        if email is None or tenant_id is None:
            raise credentials_exception
        token_data = TokenData(email=email, tenant_id=tenant_id)
    except JWTError:
        raise credentials_exception

    user = await get_user_by_email(email=token_data.email, tenant_id=token_data.tenant_id)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user: UserInDB = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
