from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from app.models import (
    VoucherCreate, VoucherUpdate, Voucher, VoucherInDB, UserInDB,
    VoucherBalanceAdjustment, VoucherShareRequest, VoucherUnshareRequest,
    VoucherStatus, TransactionType, TransactionRecord
)
from app.auth import get_current_active_user
from app.database import get_database
from bson import ObjectId
from datetime import datetime
from decimal import Decimal
import logging
import secrets
import string

logger = logging.getLogger(__name__)
router = APIRouter()


# Helper functions
def generate_voucher_code() -> str:
    """Generate a unique voucher code"""
    prefix = "VOUCHER"
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    return f"{prefix}-{random_part}"


def check_voucher_access(voucher: dict, user_id: str, required_role: str = "viewer") -> str:
    """
    Check if user has access to voucher and return their role.
    required_role: 'viewer' (read), 'manager' (edit), 'owner' (full control)
    Returns: actual user role if authorized
    Raises: HTTPException if unauthorized
    """
    user_id_str = str(user_id)

    # Determine user's role
    if user_id_str in voucher.get("owners", []):
        user_role = "owner"
    elif user_id_str in voucher.get("managers", []):
        user_role = "manager"
    elif user_id_str in voucher.get("viewers", []):
        user_role = "viewer"
    else:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check if user's role meets requirement
    role_hierarchy = {"viewer": 0, "manager": 1, "owner": 2}
    if role_hierarchy[user_role] < role_hierarchy[required_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. {required_role.capitalize()} role required."
        )

    return user_role


async def execute_validation_function(
    function_id: str,
    context: dict,
    db
) -> tuple[bool, Optional[str]]:
    """
    Execute a validation function.
    Returns: (is_valid, error_message)
    """
    try:
        from app.services.function_executor import FunctionExecutor

        executor = FunctionExecutor()
        function = await db.functions.find_one({"_id": ObjectId(function_id)})
        if not function:
            return True, None  # Skip validation if function not found

        result = await executor.execute(
            function_id=function_id,
            function_doc=function,
            context=context,
            db=db
        )

        # Expect boolean result
        if isinstance(result, bool):
            return result, None if result else "Validation function returned False"
        elif isinstance(result, dict) and "valid" in result:
            return result["valid"], result.get("error")
        else:
            return True, None  # Default to valid if unclear
    except Exception as e:
        logger.error(f"Validation function error: {str(e)}")
        return False, f"Validation error: {str(e)}"


def _build_voucher_response(voucher_doc: dict, user_id: str) -> Voucher:
    """Build Voucher response from database document"""
    # Determine user's role
    user_role = None
    if user_id in voucher_doc.get("owners", []):
        user_role = "owner"
    elif user_id in voucher_doc.get("managers", []):
        user_role = "manager"
    elif user_id in voucher_doc.get("viewers", []):
        user_role = "viewer"

    return Voucher(
        id=str(voucher_doc["_id"]),
        name=voucher_doc["name"],
        description=voucher_doc.get("description", ""),
        code=voucher_doc["code"],
        starting_balance=Decimal(str(voucher_doc["starting_balance"])),
        balance=Decimal(str(voucher_doc["balance"])),
        currency=voucher_doc.get("currency", "USD"),
        status=voucher_doc["status"],
        owners=voucher_doc.get("owners", []),
        managers=voucher_doc.get("managers", []),
        viewers=voucher_doc.get("viewers", []),
        recipient_ids=voucher_doc.get("recipient_ids", []),
        funder_ids=voucher_doc.get("funder_ids", []),
        accepted_funder_ids=voucher_doc.get("accepted_funder_ids", []),
        tags=voucher_doc.get("tags", []),
        expires_at=voucher_doc.get("expires_at"),
        validation_function_id=voucher_doc.get("validation_function_id"),
        transaction_history=[
            TransactionRecord(**t) for t in voucher_doc.get("transaction_history", [])
        ],
        created_at=voucher_doc["created_at"],
        updated_at=voucher_doc["updated_at"],
        last_transaction_at=voucher_doc.get("last_transaction_at"),
        user_role=user_role
    )


# CRUD Endpoints

@router.post("/", response_model=Voucher, status_code=status.HTTP_201_CREATED)
async def create_voucher(
    voucher: VoucherCreate,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Create a new voucher. Creator becomes first owner."""
    logger.info(f"Creating voucher for user: {current_user.email}")
    db = await get_database()

    # Generate code if not provided
    code = voucher.code or generate_voucher_code()

    # Check for duplicate code in tenant
    existing = await db.vouchers.find_one({
        "tenant_id": current_user.tenant_id,
        "code": code
    })
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Voucher code '{code}' already exists"
        )

    # Build voucher document
    voucher_dict = voucher.model_dump(exclude={"code"})
    voucher_dict["code"] = code
    voucher_dict["balance"] = voucher.starting_balance
    voucher_dict["user_id"] = str(current_user.id)
    voucher_dict["tenant_id"] = current_user.tenant_id
    voucher_dict["owners"] = [str(current_user.id)]  # Creator is first owner

    # Validate and set initial recipients if provided
    if voucher.recipient_ids:
        # Validate user IDs exist (can be from any tenant)
        valid_user_ids = []
        invalid_user_ids = []
        for user_id in voucher.recipient_ids:
            if ObjectId.is_valid(user_id):
                user_exists = await db.users.find_one({
                    "_id": ObjectId(user_id)
                })
                if user_exists:
                    valid_user_ids.append(user_id)
                else:
                    invalid_user_ids.append(user_id)
            else:
                invalid_user_ids.append(user_id)

        voucher_dict["recipient_ids"] = valid_user_ids

        # Warn if some IDs were rejected
        if invalid_user_ids:
            logger.warning(f"Rejected invalid recipient IDs: {invalid_user_ids}")
            if not valid_user_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"All recipient IDs are invalid or don't exist: {invalid_user_ids}"
                )
    else:
        voucher_dict["recipient_ids"] = []

    # Validate and set initial funders if provided, otherwise default to owner
    if voucher.funder_ids:
        # Validate user IDs exist (can be from any tenant)
        valid_user_ids = []
        invalid_user_ids = []
        for user_id in voucher.funder_ids:
            if ObjectId.is_valid(user_id):
                user_exists = await db.users.find_one({
                    "_id": ObjectId(user_id)
                })
                if user_exists:
                    valid_user_ids.append(user_id)
                else:
                    invalid_user_ids.append(user_id)
            else:
                invalid_user_ids.append(user_id)

        voucher_dict["funder_ids"] = valid_user_ids

        # Warn if some IDs were rejected
        if invalid_user_ids:
            logger.warning(f"Rejected invalid funder IDs: {invalid_user_ids}")
            if not valid_user_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"All funder IDs are invalid or don't exist: {invalid_user_ids}"
                )
    else:
        # Default: Owner is the initial funder
        voucher_dict["funder_ids"] = [str(current_user.id)]

    # Initialize accepted_funder_ids as empty (funders must accept separately)
    voucher_dict["accepted_funder_ids"] = []

    voucher_in_db = VoucherInDB(**voucher_dict)
    # Convert Decimal fields to float for MongoDB storage
    voucher_doc = voucher_in_db.model_dump(by_alias=True, exclude={"id"})
    voucher_doc["starting_balance"] = float(voucher_doc["starting_balance"])
    voucher_doc["balance"] = float(voucher_doc["balance"])
    result = await db.vouchers.insert_one(voucher_doc)

    created_voucher = await db.vouchers.find_one({"_id": result.inserted_id})
    logger.info(f"Voucher created: {code}")

    return _build_voucher_response(created_voucher, str(current_user.id))


@router.get("/", response_model=List[Voucher])
async def list_vouchers(
    status_filter: Optional[VoucherStatus] = Query(None, alias="status"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """List all vouchers accessible to current user"""
    logger.info(f"Listing vouchers for user: {current_user.email}")
    db = await get_database()
    user_id = str(current_user.id)

    # Build query: vouchers where user is owner, manager, or viewer
    query = {
        "tenant_id": current_user.tenant_id,
        "$or": [
            {"owners": user_id},
            {"managers": user_id},
            {"viewers": user_id}
        ]
    }

    if status_filter:
        query["status"] = status_filter
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        query["tags"] = {"$in": tag_list}

    cursor = db.vouchers.find(query).sort("created_at", -1)
    vouchers = await cursor.to_list(length=1000)

    return [_build_voucher_response(v, user_id) for v in vouchers]


@router.get("/{voucher_id}", response_model=Voucher)
async def get_voucher(
    voucher_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get a specific voucher"""
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({
        "_id": ObjectId(voucher_id),
        "tenant_id": current_user.tenant_id
    })

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check access (viewer role minimum)
    user_role = check_voucher_access(voucher, str(current_user.id), "viewer")

    return _build_voucher_response(voucher, str(current_user.id))


@router.put("/{voucher_id}", response_model=Voucher)
async def update_voucher(
    voucher_id: str,
    voucher_update: VoucherUpdate,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Update voucher metadata. Requires manager or owner role."""
    logger.info(f"Updating voucher {voucher_id}")
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({
        "_id": ObjectId(voucher_id),
        "tenant_id": current_user.tenant_id
    })

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check access (manager role minimum)
    check_voucher_access(voucher, str(current_user.id), "manager")

    # Build update data
    update_data = voucher_update.model_dump(exclude_unset=True)
    update_data["updated_at"] = datetime.utcnow()

    # Validate and update recipients if provided
    if "recipient_ids" in update_data and update_data["recipient_ids"] is not None:
        # Validate user IDs exist (can be from any tenant)
        valid_user_ids = []
        invalid_user_ids = []
        for user_id in update_data["recipient_ids"]:
            if ObjectId.is_valid(user_id):
                user_exists = await db.users.find_one({
                    "_id": ObjectId(user_id)
                })
                if user_exists:
                    valid_user_ids.append(user_id)
                else:
                    invalid_user_ids.append(user_id)
            else:
                invalid_user_ids.append(user_id)

        update_data["recipient_ids"] = valid_user_ids

        # Warn if some IDs were rejected
        if invalid_user_ids:
            logger.warning(f"Rejected invalid recipient IDs during update: {invalid_user_ids}")
            if not valid_user_ids and update_data["recipient_ids"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"All recipient IDs are invalid or don't exist: {invalid_user_ids}"
                )

    # Validate and update funders if provided
    if "funder_ids" in update_data and update_data["funder_ids"] is not None:
        # Validate user IDs exist (can be from any tenant)
        valid_user_ids = []
        invalid_user_ids = []
        for user_id in update_data["funder_ids"]:
            if ObjectId.is_valid(user_id):
                user_exists = await db.users.find_one({
                    "_id": ObjectId(user_id)
                })
                if user_exists:
                    valid_user_ids.append(user_id)
                else:
                    invalid_user_ids.append(user_id)
            else:
                invalid_user_ids.append(user_id)

        update_data["funder_ids"] = valid_user_ids

        # Warn if some IDs were rejected
        if invalid_user_ids:
            logger.warning(f"Rejected invalid funder IDs during update: {invalid_user_ids}")
            if not valid_user_ids and update_data["funder_ids"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"All funder IDs are invalid or don't exist: {invalid_user_ids}"
                )

    result = await db.vouchers.update_one(
        {"_id": ObjectId(voucher_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Voucher not found")

    updated_voucher = await db.vouchers.find_one({"_id": ObjectId(voucher_id)})
    logger.info(f"Voucher {voucher_id} updated")

    return _build_voucher_response(updated_voucher, str(current_user.id))


@router.delete("/{voucher_id}")
async def delete_voucher(
    voucher_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Delete a voucher. Requires owner role."""
    logger.info(f"Deleting voucher {voucher_id}")
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({
        "_id": ObjectId(voucher_id),
        "tenant_id": current_user.tenant_id
    })

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check access (owner role required)
    check_voucher_access(voucher, str(current_user.id), "owner")

    result = await db.vouchers.delete_one({"_id": ObjectId(voucher_id)})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Voucher not found")

    logger.info(f"Voucher {voucher_id} deleted")
    return {"message": "Voucher deleted successfully"}


# Balance Management

@router.post("/{voucher_id}/adjust-balance", response_model=Voucher)
async def adjust_voucher_balance(
    voucher_id: str,
    adjustment: VoucherBalanceAdjustment,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Adjust voucher balance (credit or debit).
    Requires manager or owner role.
    Executes validation function if configured.
    """
    logger.info(f"Adjusting balance for voucher {voucher_id}")
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({
        "_id": ObjectId(voucher_id),
        "tenant_id": current_user.tenant_id
    })

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check access (manager role minimum)
    check_voucher_access(voucher, str(current_user.id), "manager")

    # Check if voucher is active
    if voucher["status"] != VoucherStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot adjust balance for {voucher['status']} voucher"
        )

    # Calculate new balance
    current_balance = Decimal(str(voucher["balance"]))
    if adjustment.type == TransactionType.CREDIT:
        new_balance = current_balance + adjustment.amount
    else:  # DEBIT
        new_balance = current_balance - adjustment.amount

    # Validate new balance
    if new_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient balance"
        )

    # Execute validation function if configured
    if voucher.get("validation_function_id"):
        context = {
            "voucher": {
                "id": str(voucher["_id"]),
                "code": voucher["code"],
                "current_balance": float(current_balance),
                "new_balance": float(new_balance),
                "starting_balance": float(Decimal(str(voucher["starting_balance"]))),
            },
            "transaction": {
                "amount": float(adjustment.amount),
                "type": adjustment.type,
                "description": adjustment.description
            },
            "user_id": str(current_user.id)
        }

        is_valid, error = await execute_validation_function(
            voucher["validation_function_id"],
            context,
            db
        )

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Validation failed: {error}"
            )

    # Create transaction record
    transaction = TransactionRecord(
        transaction_id=secrets.token_urlsafe(16),
        amount=adjustment.amount,
        type=adjustment.type,
        balance_after=new_balance,
        description=adjustment.description,
        performed_by=str(current_user.id)
    )

    # Update voucher
    update_data = {
        "balance": float(new_balance),  # Convert Decimal to float for MongoDB
        "last_transaction_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # Check if balance is depleted
    if new_balance == 0:
        update_data["status"] = VoucherStatus.DEPLETED

    # Convert transaction Decimal fields to float for MongoDB
    transaction_doc = transaction.model_dump()
    transaction_doc["amount"] = float(transaction_doc["amount"])
    transaction_doc["balance_after"] = float(transaction_doc["balance_after"])

    # Add transaction to history (keep last 50)
    await db.vouchers.update_one(
        {"_id": ObjectId(voucher_id)},
        {
            "$set": update_data,
            "$push": {
                "transaction_history": {
                    "$each": [transaction_doc],
                    "$slice": -50  # Keep only last 50 transactions
                }
            }
        }
    )

    updated_voucher = await db.vouchers.find_one({"_id": ObjectId(voucher_id)})
    logger.info(f"Balance adjusted for voucher {voucher_id}: {adjustment.type} {adjustment.amount}")

    return _build_voucher_response(updated_voucher, str(current_user.id))


# Sharing/Permissions Management

@router.post("/{voucher_id}/share")
async def share_voucher(
    voucher_id: str,
    share_request: VoucherShareRequest,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Share voucher with other users.
    Requires owner role.
    """
    logger.info(f"Sharing voucher {voucher_id}")
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({
        "_id": ObjectId(voucher_id),
        "tenant_id": current_user.tenant_id
    })

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check access (owner role required)
    check_voucher_access(voucher, str(current_user.id), "owner")

    # Validate users exist in tenant
    users_cursor = db.users.find({
        "tenant_id": current_user.tenant_id,
        "_id": {"$in": [ObjectId(uid) for uid in share_request.user_ids if ObjectId.is_valid(uid)]}
    })
    valid_users = await users_cursor.to_list(length=100)
    valid_user_ids = [str(u["_id"]) for u in valid_users]

    if len(valid_user_ids) != len(share_request.user_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some user IDs are invalid or not in tenant"
        )

    # Add users to appropriate role list
    # Special case: "recipient" -> "recipient_ids", others: "owner" -> "owners", etc.
    role_field = "recipient_ids" if share_request.role == "recipient" else f"{share_request.role}s"
    await db.vouchers.update_one(
        {"_id": ObjectId(voucher_id)},
        {
            "$addToSet": {role_field: {"$each": valid_user_ids}},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )

    logger.info(f"Voucher {voucher_id} shared with {len(valid_user_ids)} users as {share_request.role}")
    return {"message": f"Voucher shared with {len(valid_user_ids)} user(s)"}


@router.post("/{voucher_id}/unshare")
async def unshare_voucher(
    voucher_id: str,
    unshare_request: VoucherUnshareRequest,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Remove users from voucher sharing.
    Requires owner role.
    Cannot remove last owner.
    """
    logger.info(f"Unsharing voucher {voucher_id}")
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({
        "_id": ObjectId(voucher_id),
        "tenant_id": current_user.tenant_id
    })

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check access (owner role required)
    check_voucher_access(voucher, str(current_user.id), "owner")

    # Prevent removing last owner
    if unshare_request.role == "owner":
        remaining_owners = set(voucher.get("owners", [])) - set(unshare_request.user_ids)
        if len(remaining_owners) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove all owners. At least one owner must remain."
            )

    # Remove users from role list
    # Special case: "recipient" -> "recipient_ids", others: "owner" -> "owners", etc.
    role_field = "recipient_ids" if unshare_request.role == "recipient" else f"{unshare_request.role}s"
    await db.vouchers.update_one(
        {"_id": ObjectId(voucher_id)},
        {
            "$pull": {role_field: {"$in": unshare_request.user_ids}},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )

    logger.info(f"Removed {len(unshare_request.user_ids)} user(s) from voucher {voucher_id}")
    return {"message": f"Removed {len(unshare_request.user_ids)} user(s) from {unshare_request.role} role"}


# Search

@router.get("/search/query", response_model=List[Voucher])
async def search_vouchers(
    q: Optional[str] = Query(None, description="Search in code, name, description"),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Search vouchers by code, name, or description"""
    logger.info(f"Searching vouchers with query: {q}")
    db = await get_database()
    user_id = str(current_user.id)

    # Base query: accessible vouchers
    base_query = {
        "tenant_id": current_user.tenant_id,
        "$or": [
            {"owners": user_id},
            {"managers": user_id},
            {"viewers": user_id}
        ]
    }

    if q:
        # Add search criteria
        query = {
            "$and": [
                base_query,
                {
                    "$or": [
                        {"code": {"$regex": q, "$options": "i"}},
                        {"name": {"$regex": q, "$options": "i"}},
                        {"description": {"$regex": q, "$options": "i"}},
                    ]
                }
            ]
        }
    else:
        query = base_query

    cursor = db.vouchers.find(query).sort("created_at", -1)
    vouchers = await cursor.to_list(length=100)

    logger.info(f"Found {len(vouchers)} vouchers matching query")
    return [_build_voucher_response(v, user_id) for v in vouchers]


# Funder Invitation Integration

@router.post("/{voucher_id}/invite-funders")
async def invite_funders(
    voucher_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Send funder invitation messages to all funders who haven't accepted yet.
    Requires owner or manager role.
    """
    logger.info(f"Sending funder invitations for voucher {voucher_id}")
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({
        "_id": ObjectId(voucher_id),
        "tenant_id": current_user.tenant_id
    })

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    # Check access (manager+ role required)
    check_voucher_access(voucher, str(current_user.id), "manager")

    # Get funders who haven't accepted yet
    funder_ids = set(voucher.get("funder_ids", []))
    accepted_funder_ids = set(voucher.get("accepted_funder_ids", []))
    pending_funders = list(funder_ids - accepted_funder_ids)

    if not pending_funders:
        return {"message": "All funders have already accepted", "invitations_sent": 0}

    # Create invitation messages
    from app.models import MessageType

    invitation_subject = f"You've been invited to fund: {voucher['name']}"
    invitation_content = f"""You have been invited to be a funder for the voucher "{voucher['name']}" (Code: {voucher['code']}).

To accept this invitation and start funding this voucher, please visit the voucher page and click "Accept Funder Invitation".

Voucher Details:
- Name: {voucher['name']}
- Code: {voucher['code']}
- Description: {voucher.get('description', 'N/A')}
- Current Balance: {voucher.get('balance', 0)} {voucher.get('currency', 'USD')}

This is an automated message."""

    messages_sent = 0
    for funder_id in pending_funders:
        try:
            # Create invitation message
            message_doc = {
                "tenant_id": current_user.tenant_id,
                "sender_id": str(current_user.id),
                "subject": invitation_subject,
                "content": invitation_content,
                "message_type": MessageType.FUNDER_INVITATION,
                "recipient_ids": [funder_id],
                "read_by": [],
                "related_voucher_id": voucher_id,
                "created_at": datetime.utcnow()
            }

            await db.messages.insert_one(message_doc)
            messages_sent += 1
            logger.info(f"Sent funder invitation to {funder_id} for voucher {voucher_id}")
        except Exception as e:
            logger.error(f"Failed to send invitation to {funder_id}: {str(e)}")

    return {
        "message": f"Sent {messages_sent} funder invitation(s)",
        "invitations_sent": messages_sent,
        "pending_funders": len(pending_funders)
    }


@router.post("/{voucher_id}/accept-funder-invitation", response_model=Voucher)
async def accept_funder_invitation(
    voucher_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Accept a funder invitation.
    Adds current user to accepted_funder_ids if they are in funder_ids.
    """
    logger.info(f"User {current_user.email} accepting funder invitation for voucher {voucher_id}")
    db = await get_database()

    if not ObjectId.is_valid(voucher_id):
        raise HTTPException(status_code=400, detail="Invalid voucher ID")

    voucher = await db.vouchers.find_one({"_id": ObjectId(voucher_id)})

    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")

    user_id = str(current_user.id)

    # Check if user is in funder_ids
    if user_id not in voucher.get("funder_ids", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not invited as a funder for this voucher"
        )

    # Check if already accepted
    if user_id in voucher.get("accepted_funder_ids", []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already accepted this funder invitation"
        )

    # Add user to accepted_funder_ids
    await db.vouchers.update_one(
        {"_id": ObjectId(voucher_id)},
        {
            "$addToSet": {"accepted_funder_ids": user_id},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )

    # Send confirmation message to voucher owners
    from app.models import MessageType

    confirmation_subject = f"Funder accepted invitation: {voucher['name']}"
    confirmation_content = f"""Good news! {current_user.email} has accepted the invitation to be a funder for voucher "{voucher['name']}" (Code: {voucher['code']}).

They can now fund and send payments from this voucher.

This is an automated message."""

    try:
        message_doc = {
            "tenant_id": voucher["tenant_id"],
            "sender_id": "system",  # System-generated message
            "subject": confirmation_subject,
            "content": confirmation_content,
            "message_type": MessageType.SYSTEM,
            "recipient_ids": voucher.get("owners", []),
            "read_by": [],
            "related_voucher_id": voucher_id,
            "created_at": datetime.utcnow()
        }

        await db.messages.insert_one(message_doc)
        logger.info(f"Sent acceptance confirmation to voucher owners")
    except Exception as e:
        logger.error(f"Failed to send confirmation message: {str(e)}")

    # Fetch updated voucher
    updated_voucher = await db.vouchers.find_one({"_id": ObjectId(voucher_id)})

    logger.info(f"User {current_user.email} accepted funder invitation for voucher {voucher_id}")
    return _build_voucher_response(updated_voucher, user_id)
