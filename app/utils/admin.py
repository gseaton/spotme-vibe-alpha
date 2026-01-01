from fastapi import HTTPException, status
from app.models import UserInDB
from bson import ObjectId


def require_admin(user: UserInDB):
    """
    Dependency to require admin privileges.
    Raises 403 if user is not admin.

    Usage:
        @router.post("/admin-only-endpoint")
        async def admin_endpoint(current_user: UserInDB = Depends(require_admin)):
            # Only admins can access this
            pass
    """
    if not getattr(user, 'is_admin', False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required"
        )
    return user


async def make_user_admin(db, user_id: str):
    """
    Helper function to grant admin privileges to a user.
    Use this in a migration script or admin panel.

    Args:
        db: Motor database instance
        user_id: User ID string or ObjectId

    Returns:
        bool: True if user was updated, False otherwise
    """
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"is_admin": True}}
    )
    return result.modified_count > 0
