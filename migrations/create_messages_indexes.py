"""
Create Messages Collection Indexes Migration Script

This script creates MongoDB indexes for the messages collection to ensure
query performance for inbox, sent, and search operations.

Usage:
    python migrations/create_messages_indexes.py

Indexes created:
    - Index on recipient_ids array - for finding messages in inbox
    - Index on sender_id - for finding sent messages
    - Index on (tenant_id, created_at) - for sorting messages by date
    - Index on read_by array - for tracking read status
    - Index on related_voucher_id - for finding messages related to vouchers
    - Compound index on (recipient_ids, read_by) - for unread messages query
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


async def create_message_indexes():
    """
    Create indexes for the messages collection.
    """
    logger.info("Creating message indexes...")

    try:
        await connect_to_mongo()
        db = await get_database()

        # Create index on recipient_ids array for inbox queries
        await db.messages.create_index(
            [("recipient_ids", 1)],
            name="recipient_ids_idx"
        )
        logger.info("✓ Created index on recipient_ids")

        # Create index on sender_id for sent messages queries
        await db.messages.create_index(
            [("sender_id", 1)],
            name="sender_id_idx"
        )
        logger.info("✓ Created index on sender_id")

        # Create index on tenant_id + created_at for sorting
        await db.messages.create_index(
            [("tenant_id", 1), ("created_at", -1)],
            name="tenant_created"
        )
        logger.info("✓ Created index on (tenant_id, created_at)")

        # Create index on read_by array for read status tracking
        await db.messages.create_index(
            [("read_by", 1)],
            name="read_by_idx"
        )
        logger.info("✓ Created index on read_by")

        # Create index on related_voucher_id for voucher-related messages
        await db.messages.create_index(
            [("related_voucher_id", 1)],
            name="related_voucher_idx",
            sparse=True  # Only index documents with this field
        )
        logger.info("✓ Created index on related_voucher_id")

        # Note: Cannot create compound index on (recipient_ids, read_by)
        # because both are arrays (MongoDB limitation: cannot index parallel arrays)
        # Separate indexes on each array field are sufficient for queries

        # Create index on message_type for filtering by type
        await db.messages.create_index(
            [("message_type", 1)],
            name="message_type_idx"
        )
        logger.info("✓ Created index on message_type")

        logger.info("All message indexes created successfully!")

        # List all indexes
        indexes = await db.messages.index_information()
        logger.info(f"\nCurrent messages collection indexes:")
        for index_name, index_info in indexes.items():
            logger.info(f"  - {index_name}: {index_info['key']}")

    except Exception as e:
        logger.error(f"Error creating indexes: {str(e)}")
        raise
    finally:
        await close_mongo_connection()


async def drop_message_indexes():
    """
    Drop all custom message indexes (for rollback).
    Note: Does not drop the default _id index.
    """
    logger.info("Dropping message indexes...")

    try:
        await connect_to_mongo()
        db = await get_database()

        index_names = [
            "recipient_ids_idx",
            "sender_id_idx",
            "tenant_created",
            "read_by_idx",
            "related_voucher_idx",
            "message_type_idx"
        ]

        for index_name in index_names:
            try:
                await db.messages.drop_index(index_name)
                logger.info(f"✓ Dropped index: {index_name}")
            except Exception as e:
                logger.warning(f"Could not drop index {index_name}: {str(e)}")

        logger.info("Message indexes dropped successfully!")

    except Exception as e:
        logger.error(f"Error dropping indexes: {str(e)}")
        raise
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage message collection indexes")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop indexes instead of creating them"
    )

    args = parser.parse_args()

    if args.drop:
        asyncio.run(drop_message_indexes())
    else:
        asyncio.run(create_message_indexes())
