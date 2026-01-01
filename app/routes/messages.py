from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
import logging

from app.models import (
    Message,
    MessageCreate,
    MessageInDB,
    UserInDB,
    MessageType
)
from app.auth import get_current_active_user
from app.database import get_database

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_message_response(message_doc: dict, current_user_id: str) -> Message:
    """Convert MongoDB document to Message response model"""
    return Message(
        id=str(message_doc["_id"]),
        subject=message_doc["subject"],
        content=message_doc["content"],
        message_type=message_doc["message_type"],
        sender_id=message_doc["sender_id"],
        sender_email=message_doc.get("sender_email"),  # Populated by aggregation
        recipient_ids=message_doc["recipient_ids"],
        read_by=message_doc.get("read_by", []),
        related_voucher_id=message_doc.get("related_voucher_id"),
        created_at=message_doc["created_at"],
        is_read=current_user_id in message_doc.get("read_by", [])
    )


@router.post("/", response_model=Message, status_code=status.HTTP_201_CREATED)
async def create_message(
    message: MessageCreate,
    current_user: UserInDB = Depends(get_current_active_user),
    db=Depends(get_database)
):
    """
    Create and send a new message.

    - Validates recipient user IDs exist
    - Supports cross-tenant messaging
    - Can link to vouchers via related_voucher_id
    """
    try:
        # Validate recipient user IDs exist
        valid_recipient_ids = []
        for user_id in message.recipient_ids:
            try:
                if not ObjectId.is_valid(user_id):
                    logger.warning(f"Invalid recipient ObjectId: {user_id}")
                    continue

                user_exists = await db.users.find_one({
                    "_id": ObjectId(user_id)
                })

                if user_exists:
                    valid_recipient_ids.append(user_id)
                else:
                    logger.warning(f"Recipient user not found: {user_id}")

            except Exception as e:
                logger.error(f"Error validating recipient {user_id}: {str(e)}")
                continue

        if not valid_recipient_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid recipient user IDs provided"
            )

        # Validate related voucher if provided
        if message.related_voucher_id:
            if not ObjectId.is_valid(message.related_voucher_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid voucher ID format"
                )

            voucher = await db.vouchers.find_one({
                "_id": ObjectId(message.related_voucher_id)
            })

            if not voucher:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Related voucher not found"
                )

        # Create message document
        message_dict = {
            "tenant_id": current_user.tenant_id,
            "sender_id": str(current_user.id),
            "subject": message.subject,
            "content": message.content,
            "message_type": message.message_type,
            "recipient_ids": valid_recipient_ids,
            "read_by": [],  # Empty initially
            "related_voucher_id": message.related_voucher_id,
            "created_at": datetime.utcnow()
        }

        result = await db.messages.insert_one(message_dict)
        message_dict["_id"] = result.inserted_id

        # Fetch sender email for response
        sender = await db.users.find_one({"_id": ObjectId(current_user.id)})
        message_dict["sender_email"] = sender.get("email") if sender else None

        logger.info(f"Message created: {result.inserted_id} from {current_user.email} to {len(valid_recipient_ids)} recipients")

        return _build_message_response(message_dict, str(current_user.id))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create message: {str(e)}"
        )


@router.get("/", response_model=List[Message])
async def list_messages(
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False,
    current_user: UserInDB = Depends(get_current_active_user),
    db=Depends(get_database)
):
    """
    List messages for current user (inbox).

    Returns messages where the current user is a recipient.
    Sorted by created_at descending (newest first).
    """
    try:
        # Build query - messages where user is a recipient
        query = {
            "recipient_ids": str(current_user.id)
        }

        # Filter for unread only if requested
        if unread_only:
            query["read_by"] = {"$ne": str(current_user.id)}

        # Aggregate to populate sender email
        pipeline = [
            {"$match": query},
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {
                "$lookup": {
                    "from": "users",
                    "let": {"sender_id": {"$toObjectId": "$sender_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$sender_id"]}}},
                        {"$project": {"email": 1}}
                    ],
                    "as": "sender_info"
                }
            },
            {
                "$addFields": {
                    "sender_email": {"$arrayElemAt": ["$sender_info.email", 0]}
                }
            },
            {"$project": {"sender_info": 0}}
        ]

        messages = await db.messages.aggregate(pipeline).to_list(length=limit)

        return [_build_message_response(msg, str(current_user.id)) for msg in messages]

    except Exception as e:
        logger.error(f"Error listing messages: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list messages: {str(e)}"
        )


@router.get("/sent", response_model=List[Message])
async def list_sent_messages(
    skip: int = 0,
    limit: int = 50,
    current_user: UserInDB = Depends(get_current_active_user),
    db=Depends(get_database)
):
    """
    List messages sent by current user.

    Sorted by created_at descending (newest first).
    """
    try:
        # Build query - messages where user is the sender
        query = {
            "sender_id": str(current_user.id)
        }

        # Aggregate to populate sender email
        pipeline = [
            {"$match": query},
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {
                "$lookup": {
                    "from": "users",
                    "let": {"sender_id": {"$toObjectId": "$sender_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$sender_id"]}}},
                        {"$project": {"email": 1}}
                    ],
                    "as": "sender_info"
                }
            },
            {
                "$addFields": {
                    "sender_email": {"$arrayElemAt": ["$sender_info.email", 0]}
                }
            },
            {"$project": {"sender_info": 0}}
        ]

        messages = await db.messages.aggregate(pipeline).to_list(length=limit)

        return [_build_message_response(msg, str(current_user.id)) for msg in messages]

    except Exception as e:
        logger.error(f"Error listing sent messages: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list sent messages: {str(e)}"
        )


@router.get("/{message_id}", response_model=Message)
async def get_message(
    message_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
    db=Depends(get_database)
):
    """
    Get a specific message by ID.

    Only accessible if user is sender or recipient.
    """
    try:
        if not ObjectId.is_valid(message_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid message ID format"
            )

        # Aggregate to populate sender email
        pipeline = [
            {"$match": {"_id": ObjectId(message_id)}},
            {
                "$lookup": {
                    "from": "users",
                    "let": {"sender_id": {"$toObjectId": "$sender_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$sender_id"]}}},
                        {"$project": {"email": 1}}
                    ],
                    "as": "sender_info"
                }
            },
            {
                "$addFields": {
                    "sender_email": {"$arrayElemAt": ["$sender_info.email", 0]}
                }
            },
            {"$project": {"sender_info": 0}}
        ]

        result = await db.messages.aggregate(pipeline).to_list(length=1)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )

        message = result[0]

        # Check access - user must be sender or recipient
        user_id = str(current_user.id)
        if message["sender_id"] != user_id and user_id not in message["recipient_ids"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this message"
            )

        return _build_message_response(message, user_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting message {message_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get message: {str(e)}"
        )


@router.post("/{message_id}/read", response_model=Message)
async def mark_message_read(
    message_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
    db=Depends(get_database)
):
    """
    Mark a message as read by the current user.

    Adds current user ID to the read_by array if not already present.
    """
    try:
        if not ObjectId.is_valid(message_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid message ID format"
            )

        user_id = str(current_user.id)

        # Check message exists and user is a recipient
        message = await db.messages.find_one({"_id": ObjectId(message_id)})

        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )

        if user_id not in message["recipient_ids"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a recipient of this message"
            )

        # Add user to read_by array if not already present
        await db.messages.update_one(
            {"_id": ObjectId(message_id)},
            {"$addToSet": {"read_by": user_id}}
        )

        # Fetch updated message with sender email
        pipeline = [
            {"$match": {"_id": ObjectId(message_id)}},
            {
                "$lookup": {
                    "from": "users",
                    "let": {"sender_id": {"$toObjectId": "$sender_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$sender_id"]}}},
                        {"$project": {"email": 1}}
                    ],
                    "as": "sender_info"
                }
            },
            {
                "$addFields": {
                    "sender_email": {"$arrayElemAt": ["$sender_info.email", 0]}
                }
            },
            {"$project": {"sender_info": 0}}
        ]

        result = await db.messages.aggregate(pipeline).to_list(length=1)
        updated_message = result[0] if result else message

        logger.info(f"Message {message_id} marked as read by user {current_user.email}")

        return _build_message_response(updated_message, user_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking message {message_id} as read: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark message as read: {str(e)}"
        )


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: str,
    current_user: UserInDB = Depends(get_current_active_user),
    db=Depends(get_database)
):
    """
    Delete a message.

    Only the sender can delete a message.
    """
    try:
        if not ObjectId.is_valid(message_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid message ID format"
            )

        user_id = str(current_user.id)

        # Check message exists and user is the sender
        message = await db.messages.find_one({"_id": ObjectId(message_id)})

        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )

        if message["sender_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the sender can delete a message"
            )

        # Delete the message
        await db.messages.delete_one({"_id": ObjectId(message_id)})

        logger.info(f"Message {message_id} deleted by user {current_user.email}")

        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting message {message_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete message: {str(e)}"
        )


@router.get("/unread/count", response_model=dict)
async def get_unread_count(
    current_user: UserInDB = Depends(get_current_active_user),
    db=Depends(get_database)
):
    """
    Get count of unread messages for current user.

    Returns: {"unread_count": <number>}
    """
    try:
        user_id = str(current_user.id)

        count = await db.messages.count_documents({
            "recipient_ids": user_id,
            "read_by": {"$ne": user_id}
        })

        return {"unread_count": count}

    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get unread count: {str(e)}"
        )
