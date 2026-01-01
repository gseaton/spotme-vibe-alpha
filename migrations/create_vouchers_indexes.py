"""
Create Vouchers Collection Indexes Migration Script

This script creates MongoDB indexes for the vouchers collection to ensure
data integrity and query performance.

Usage:
    python migrations/create_vouchers_indexes.py

Indexes created:
    - Unique index on (tenant_id, code) - prevent duplicate codes per tenant
    - Index on (tenant_id, status) - for filtering by status
    - Index on (tenant_id, created_at) - for sorting by creation date
    - Index on owners array - for finding vouchers by owner
    - Index on managers array - for finding vouchers by manager
    - Index on viewers array - for finding vouchers by viewer
"""

import asyncio
import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_database, connect_to_mongo, close_mongo_connection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_voucher_indexes():
    """
    Create indexes for the vouchers collection.
    """
    logger.info("Creating voucher indexes...")

    try:
        await connect_to_mongo()
        db = await get_database()

        # Create unique index on tenant_id + code
        await db.vouchers.create_index(
            [("tenant_id", 1), ("code", 1)],
            unique=True,
            name="tenant_code_unique"
        )
        logger.info("✓ Created unique index on (tenant_id, code)")

        # Create index on tenant_id + status for filtering
        await db.vouchers.create_index(
            [("tenant_id", 1), ("status", 1)],
            name="tenant_status"
        )
        logger.info("✓ Created index on (tenant_id, status)")

        # Create index on tenant_id + created_at for sorting
        await db.vouchers.create_index(
            [("tenant_id", 1), ("created_at", -1)],
            name="tenant_created"
        )
        logger.info("✓ Created index on (tenant_id, created_at)")

        # Create index on owners array
        await db.vouchers.create_index(
            [("owners", 1)],
            name="owners_idx"
        )
        logger.info("✓ Created index on owners")

        # Create index on managers array
        await db.vouchers.create_index(
            [("managers", 1)],
            name="managers_idx"
        )
        logger.info("✓ Created index on managers")

        # Create index on viewers array
        await db.vouchers.create_index(
            [("viewers", 1)],
            name="viewers_idx"
        )
        logger.info("✓ Created index on viewers")

        logger.info("All voucher indexes created successfully!")

        # List all indexes
        indexes = await db.vouchers.index_information()
        logger.info(f"\nCurrent vouchers collection indexes:")
        for index_name, index_info in indexes.items():
            logger.info(f"  - {index_name}: {index_info['key']}")

    except Exception as e:
        logger.error(f"Error creating indexes: {str(e)}")
        raise
    finally:
        await close_mongo_connection()


async def drop_voucher_indexes():
    """
    Drop all custom voucher indexes (for rollback).
    Note: Does not drop the default _id index.
    """
    logger.info("Dropping voucher indexes...")

    try:
        await connect_to_mongo()
        db = await get_database()

        index_names = [
            "tenant_code_unique",
            "tenant_status",
            "tenant_created",
            "owners_idx",
            "managers_idx",
            "viewers_idx"
        ]

        for index_name in index_names:
            try:
                await db.vouchers.drop_index(index_name)
                logger.info(f"✓ Dropped index: {index_name}")
            except Exception as e:
                logger.warning(f"Could not drop index {index_name}: {str(e)}")

        logger.info("Voucher indexes dropped successfully!")

    except Exception as e:
        logger.error(f"Error dropping indexes: {str(e)}")
        raise
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage voucher collection indexes")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop indexes instead of creating them"
    )

    args = parser.parse_args()

    if args.drop:
        asyncio.run(drop_voucher_indexes())
    else:
        asyncio.run(create_voucher_indexes())
