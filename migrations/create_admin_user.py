"""
Create Admin User Migration Script

This script creates an admin user in the database.

Usage:
    python -c "import asyncio; from migrations.create_admin_user import create_admin; asyncio.run(create_admin())"

Or run directly:
    python migrations/create_admin_user.py
"""

import asyncio
import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_database, connect_to_mongo, close_mongo_connection
from app.auth import get_password_hash
from app.models import UserInDB
from bson import ObjectId


async def create_admin(
    email: str = "admin@example.com",
    password: str = "admin123",
    full_name: str = "System Administrator",
    tenant_id: str = "default"
):
    """
    Create an admin user.

    Args:
        email: Admin email address
        password: Admin password (will be hashed)
        full_name: Admin full name
        tenant_id: Tenant ID for the admin user

    Returns:
        str: User ID of created admin, or None if user already exists
    """
    # Connect to database
    await connect_to_mongo()
    db = await get_database()

    try:
        # Check if user already exists
        existing_user = await db.users.find_one({"email": email, "tenant_id": tenant_id})
        if existing_user:
            print(f"User with email {email} already exists in tenant {tenant_id}")

            # Check if user is already admin
            if existing_user.get("is_admin", False):
                print(f"User is already an admin")
                return str(existing_user["_id"])
            else:
                # Make existing user admin
                result = await db.users.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": {"is_admin": True}}
                )
                print(f"Updated existing user to admin: {existing_user['_id']}")
                return str(existing_user["_id"])

        # Create new admin user
        admin_user = UserInDB(
            email=email,
            full_name=full_name,
            tenant_id=tenant_id,
            hashed_password=get_password_hash(password),
            is_admin=True,
            is_active=True
        )

        result = await db.users.insert_one(
            admin_user.model_dump(by_alias=True, exclude={"id"})
        )

        print(f"Admin user created successfully!")
        print(f"User ID: {result.inserted_id}")
        print(f"Email: {email}")
        print(f"Password: {password}")
        print(f"Tenant ID: {tenant_id}")
        print(f"\nIMPORTANT: Change the password after first login!")

        return str(result.inserted_id)

    except Exception as e:
        print(f"Error creating admin user: {str(e)}")
        raise
    finally:
        await close_mongo_connection()


async def interactive_create_admin():
    """
    Interactive version that prompts for admin details.
    """
    print("=== Create Admin User ===\n")

    email = input("Admin email [admin@example.com]: ").strip() or "admin@example.com"
    password = input("Admin password [admin123]: ").strip() or "admin123"
    full_name = input("Full name [System Administrator]: ").strip() or "System Administrator"
    tenant_id = input("Tenant ID [default]: ").strip() or "default"

    print(f"\nCreating admin user with:")
    print(f"  Email: {email}")
    print(f"  Full Name: {full_name}")
    print(f"  Tenant ID: {tenant_id}")

    confirm = input("\nProceed? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("Cancelled")
        return

    await create_admin(
        email=email,
        password=password,
        full_name=full_name,
        tenant_id=tenant_id
    )


if __name__ == "__main__":
    # Run interactive version when executed directly
    asyncio.run(interactive_create_admin())
