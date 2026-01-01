from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from app.models import UserCreate, User, Token, UserInDB
from app.auth import (
    get_password_hash,
    authenticate_user,
    create_access_token,
    get_user_by_email,
    get_current_active_user,
)
from app.database import get_database
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


@router.post("/register", response_model=User)
async def register(user: UserCreate):
    logger.info(f"Registration attempt for user: {user.email}, tenant: {user.tenant_id}")
    db = await get_database()

    existing_user = await get_user_by_email(user.email, user.tenant_id)
    if existing_user:
        logger.warning(f"Registration failed: User {user.email} already exists in tenant {user.tenant_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered for this tenant"
        )

    user_dict = user.model_dump()
    user_dict["hashed_password"] = get_password_hash(user_dict.pop("password"))

    user_in_db = UserInDB(**user_dict)
    result = await db.users.insert_one(user_in_db.model_dump(by_alias=True, exclude={"id"}))

    created_user = await db.users.find_one({"_id": result.inserted_id})
    logger.info(f"User registered successfully: {user.email}")

    return User(
        id=str(created_user["_id"]),
        email=created_user["email"],
        full_name=created_user["full_name"],
        tenant_id=created_user["tenant_id"],
        created_at=created_user["created_at"],
        is_active=created_user["is_active"]
    )


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    tenant_id = form_data.scopes[0] if form_data.scopes else "default"

    logger.info(f"Login attempt for user: {form_data.username}, tenant: {tenant_id}")

    user = await authenticate_user(form_data.username, form_data.password, tenant_id)
    if not user:
        logger.warning(f"Login failed for user: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email, "tenant_id": user.tenant_id},
        expires_delta=access_token_expires
    )

    logger.info(f"User logged in successfully: {form_data.username}")

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=User)
async def get_current_user_info(current_user: UserInDB = Depends(get_current_active_user)):
    """Get current user information"""
    return User(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        tenant_id=current_user.tenant_id,
        created_at=current_user.created_at,
        is_active=current_user.is_active
    )


@router.get("/users/search")
async def search_users(
    q: str = "",
    all_tenants: bool = False,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Search users by email. By default searches current tenant only, use all_tenants=true for cross-tenant search."""
    db = await get_database()

    # Build search query
    query = {
        "is_active": True
    }

    # Filter by tenant unless all_tenants is requested
    if not all_tenants:
        query["tenant_id"] = current_user.tenant_id

    # If search term provided, filter by email
    if q:
        query["email"] = {"$regex": q, "$options": "i"}

    # Find users (limit to 20 results for cross-tenant search)
    limit = 20 if all_tenants else 10
    users_cursor = db.users.find(query).limit(limit)
    users = await users_cursor.to_list(length=limit)

    # Return simplified user info (include tenant_id for cross-tenant results)
    return [
        {
            "id": str(user["_id"]),
            "email": user["email"],
            "full_name": user.get("full_name", ""),
            "tenant_id": user.get("tenant_id", "") if all_tenants else current_user.tenant_id
        }
        for user in users
    ]
