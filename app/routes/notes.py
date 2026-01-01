from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from app.models import NoteCreate, NoteUpdate, Note, NoteInDB, UserInDB
from app.auth import get_current_active_user
from app.database import get_database
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=Note)
async def create_note(
    note: NoteCreate,
    current_user: UserInDB = Depends(get_current_active_user)
):
    logger.info(f"Creating note for user: {current_user.email}, tenant: {current_user.tenant_id}")
    db = await get_database()

    note_dict = note.model_dump()
    note_dict["user_id"] = str(current_user.id)
    note_dict["tenant_id"] = current_user.tenant_id

    note_in_db = NoteInDB(**note_dict)
    result = await db.notes.insert_one(note_in_db.model_dump(by_alias=True, exclude={"id"}))

    created_note = await db.notes.find_one({"_id": result.inserted_id})
    logger.info(f"Note created successfully with ID: {result.inserted_id}")

    return Note(
        id=str(created_note["_id"]),
        title=created_note["title"],
        content=created_note["content"],
        tags=created_note.get("tags", []),
        created_at=created_note["created_at"],
        updated_at=created_note["updated_at"]
    )


@router.get("/", response_model=List[Note])
async def get_notes(current_user: UserInDB = Depends(get_current_active_user)):
    logger.info(f"Fetching notes for user: {current_user.email}, tenant: {current_user.tenant_id}")
    db = await get_database()

    cursor = db.notes.find({
        "user_id": str(current_user.id),
        "tenant_id": current_user.tenant_id
    }).sort("created_at", -1)

    notes = await cursor.to_list(length=100)

    return [
        Note(
            id=str(note["_id"]),
            title=note["title"],
            content=note["content"],
            tags=note.get("tags", []),
            created_at=note["created_at"],
            updated_at=note["updated_at"]
        )
        for note in notes
    ]


@router.get("/{note_id}", response_model=Note)
async def get_note(
    note_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    logger.info(f"Fetching note {note_id} for user: {current_user.email}")
    db = await get_database()

    if not ObjectId.is_valid(note_id):
        raise HTTPException(status_code=400, detail="Invalid note ID")

    note = await db.notes.find_one({
        "_id": ObjectId(note_id),
        "user_id": str(current_user.id),
        "tenant_id": current_user.tenant_id
    })

    if not note:
        logger.warning(f"Note {note_id} not found for user {current_user.email}")
        raise HTTPException(status_code=404, detail="Note not found")

    return Note(
        id=str(note["_id"]),
        title=note["title"],
        content=note["content"],
        tags=note.get("tags", []),
        created_at=note["created_at"],
        updated_at=note["updated_at"]
    )


@router.put("/{note_id}", response_model=Note)
async def update_note(
    note_id: str,
    note_update: NoteUpdate,
    current_user: UserInDB = Depends(get_current_active_user)
):
    logger.info(f"Updating note {note_id} for user: {current_user.email}")
    db = await get_database()

    if not ObjectId.is_valid(note_id):
        raise HTTPException(status_code=400, detail="Invalid note ID")

    update_data = note_update.model_dump()
    update_data["updated_at"] = datetime.utcnow()

    result = await db.notes.update_one(
        {
            "_id": ObjectId(note_id),
            "user_id": str(current_user.id),
            "tenant_id": current_user.tenant_id
        },
        {"$set": update_data}
    )

    if result.matched_count == 0:
        logger.warning(f"Note {note_id} not found for update")
        raise HTTPException(status_code=404, detail="Note not found")

    updated_note = await db.notes.find_one({"_id": ObjectId(note_id)})
    logger.info(f"Note {note_id} updated successfully")

    return Note(
        id=str(updated_note["_id"]),
        title=updated_note["title"],
        content=updated_note["content"],
        tags=updated_note.get("tags", []),
        created_at=updated_note["created_at"],
        updated_at=updated_note["updated_at"]
    )


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    logger.info(f"Deleting note {note_id} for user: {current_user.email}")
    db = await get_database()

    if not ObjectId.is_valid(note_id):
        raise HTTPException(status_code=400, detail="Invalid note ID")

    result = await db.notes.delete_one({
        "_id": ObjectId(note_id),
        "user_id": str(current_user.id),
        "tenant_id": current_user.tenant_id
    })

    if result.deleted_count == 0:
        logger.warning(f"Note {note_id} not found for deletion")
        raise HTTPException(status_code=404, detail="Note not found")

    logger.info(f"Note {note_id} deleted successfully")
    return {"message": "Note deleted successfully"}


@router.get("/search/query", response_model=List[Note])
async def search_notes(
    q: Optional[str] = Query(None, description="Search query for title, content, or tags"),
    current_user: UserInDB = Depends(get_current_active_user)
):
    logger.info(f"Searching notes for user: {current_user.email}, query: {q}")
    db = await get_database()

    if not q:
        # If no query, return all notes
        cursor = db.notes.find({
            "user_id": str(current_user.id),
            "tenant_id": current_user.tenant_id
        }).sort("created_at", -1)
    else:
        # Search in title, content, and tags
        cursor = db.notes.find({
            "user_id": str(current_user.id),
            "tenant_id": current_user.tenant_id,
            "$or": [
                {"title": {"$regex": q, "$options": "i"}},
                {"content": {"$regex": q, "$options": "i"}},
                {"tags": {"$regex": q, "$options": "i"}}
            ]
        }).sort("created_at", -1)

    notes = await cursor.to_list(length=100)
    logger.info(f"Found {len(notes)} notes matching query")

    return [
        Note(
            id=str(note["_id"]),
            title=note["title"],
            content=note["content"],
            tags=note.get("tags", []),
            created_at=note["created_at"],
            updated_at=note["updated_at"]
        )
        for note in notes
    ]
