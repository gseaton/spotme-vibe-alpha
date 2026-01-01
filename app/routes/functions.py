from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from app.models import (
    FunctionCreate, FunctionUpdate, Function, FunctionInDB,
    UserInDB, FunctionExecuteRequest, FunctionExecuteResponse,
    FunctionScope, FunctionType
)
from app.auth import get_current_active_user
from app.database import get_database
from app.services.function_parser import FunctionParser
from app.services.function_executor import FunctionExecutor
from bson import ObjectId
from datetime import datetime
import logging
import time

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize services (singleton instances)
function_parser = FunctionParser()
function_executor = FunctionExecutor()


@router.post("/", response_model=Function, status_code=status.HTTP_201_CREATED)
async def create_function(
    function: FunctionCreate,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Create a new function.
    - Tenant-scoped functions: Any authenticated user
    - Global functions: Admin only
    """
    logger.info(f"Creating function '{function.name}' for user: {current_user.email}")

    # Authorization: Global functions require admin
    if function.scope == FunctionScope.GLOBAL:
        if not getattr(current_user, 'is_admin', False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can create global functions"
            )

    db = await get_database()

    # Check for duplicate name within tenant/global scope
    existing_query = {"name": function.name}
    if function.scope == FunctionScope.TENANT:
        existing_query["tenant_id"] = current_user.tenant_id
    else:
        existing_query["scope"] = FunctionScope.GLOBAL

    existing = await db.functions.find_one(existing_query)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Function with name '{function.name}' already exists in this scope"
        )

    # Parse and compile the function
    try:
        compilation_result = function_parser.parse_and_compile(function)
    except Exception as e:
        logger.error(f"Function compilation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Function compilation failed: {str(e)}"
        )

    # Build function document
    function_dict = function.model_dump(exclude_unset=True)
    function_dict["user_id"] = str(current_user.id)
    function_dict["created_by_user_id"] = str(current_user.id)

    # Set tenant_id based on scope
    if function.scope == FunctionScope.TENANT:
        function_dict["tenant_id"] = current_user.tenant_id
    else:
        function_dict["tenant_id"] = None

    # Add compilation results
    function_dict.update(compilation_result)

    function_in_db = FunctionInDB(**function_dict)
    result = await db.functions.insert_one(
        function_in_db.model_dump(by_alias=True, exclude={"id"})
    )

    created_function = await db.functions.find_one({"_id": result.inserted_id})
    logger.info(f"Function created successfully with ID: {result.inserted_id}")

    return _build_function_response(created_function)


@router.get("/", response_model=List[Function])
async def list_functions(
    function_type: Optional[FunctionType] = Query(None),
    scope: Optional[FunctionScope] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    is_active: Optional[bool] = Query(None),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    List functions accessible to the current user.
    Returns: Tenant functions + Global functions
    """
    logger.info(f"Listing functions for user: {current_user.email}")
    db = await get_database()

    # Build query: user's tenant functions OR global functions
    query = {
        "$or": [
            {"tenant_id": current_user.tenant_id, "scope": FunctionScope.TENANT},
            {"scope": FunctionScope.GLOBAL}
        ]
    }

    # Apply filters
    if function_type:
        query["function_type"] = function_type
    if scope:
        # Override the $or if scope filter is specified
        if scope == FunctionScope.TENANT:
            query = {"tenant_id": current_user.tenant_id, "scope": FunctionScope.TENANT}
        else:
            query = {"scope": FunctionScope.GLOBAL}
    if is_active is not None:
        query["is_active"] = is_active
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        query["tags"] = {"$in": tag_list}

    cursor = db.functions.find(query).sort("created_at", -1)
    functions = await cursor.to_list(length=1000)

    logger.info(f"Found {len(functions)} functions")
    return [_build_function_response(func) for func in functions]


@router.get("/{function_id}", response_model=Function)
async def get_function(
    function_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get a specific function by ID"""
    logger.info(f"Fetching function {function_id}")
    db = await get_database()

    if not ObjectId.is_valid(function_id):
        raise HTTPException(status_code=400, detail="Invalid function ID")

    function = await db.functions.find_one({"_id": ObjectId(function_id)})

    if not function:
        raise HTTPException(status_code=404, detail="Function not found")

    # Authorization: Must be tenant function OR global function
    if function.get("scope") == FunctionScope.TENANT:
        if function.get("tenant_id") != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Function not found")

    return _build_function_response(function)


@router.put("/{function_id}", response_model=Function)
async def update_function(
    function_id: str,
    function_update: FunctionUpdate,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Update a function.
    - Tenant functions: Owner only
    - Global functions: Admin only
    """
    logger.info(f"Updating function {function_id}")
    db = await get_database()

    if not ObjectId.is_valid(function_id):
        raise HTTPException(status_code=400, detail="Invalid function ID")

    existing = await db.functions.find_one({"_id": ObjectId(function_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Function not found")

    # Authorization
    if existing.get("scope") == FunctionScope.GLOBAL:
        if not getattr(current_user, 'is_admin', False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can update global functions"
            )
    else:
        if existing.get("tenant_id") != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Function not found")
        if existing.get("user_id") != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only update your own functions"
            )

    # Build update data
    update_data = function_update.model_dump(exclude_unset=True)

    # If code is being updated, recompile
    if function_update.code_template or function_update.code_python:
        # Merge update with existing to create full function for compilation
        merged = {**existing, **update_data}
        # Only keep fields that exist in FunctionCreate
        temp_function_dict = {
            "name": merged.get("name"),
            "description": merged.get("description", ""),
            "function_type": merged.get("function_type"),
            "scope": merged.get("scope", FunctionScope.TENANT),
            "tags": merged.get("tags", []),
            "code_template": merged.get("code_template"),
            "code_python": merged.get("code_python"),
            "parameter_schema": merged.get("parameter_schema"),
            "return_type": merged.get("return_type", "any"),
            "is_active": merged.get("is_active", True)
        }
        temp_function = FunctionCreate(**temp_function_dict)

        try:
            compilation_result = function_parser.parse_and_compile(temp_function)
            update_data.update(compilation_result)

            # Invalidate cache for this function
            function_executor.invalidate_cache(function_id)
        except Exception as e:
            logger.error(f"Function recompilation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Function compilation failed: {str(e)}"
            )

    update_data["updated_at"] = datetime.utcnow()

    result = await db.functions.update_one(
        {"_id": ObjectId(function_id)},
        {"$set": update_data}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Function not found")

    updated_function = await db.functions.find_one({"_id": ObjectId(function_id)})
    logger.info(f"Function {function_id} updated successfully")

    return _build_function_response(updated_function)


@router.delete("/{function_id}")
async def delete_function(
    function_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Delete a function.
    - Tenant functions: Owner only
    - Global functions: Admin only
    """
    logger.info(f"Deleting function {function_id}")
    db = await get_database()

    if not ObjectId.is_valid(function_id):
        raise HTTPException(status_code=400, detail="Invalid function ID")

    existing = await db.functions.find_one({"_id": ObjectId(function_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Function not found")

    # Authorization (same as update)
    if existing.get("scope") == FunctionScope.GLOBAL:
        if not getattr(current_user, 'is_admin', False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can delete global functions"
            )
    else:
        if existing.get("tenant_id") != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Function not found")
        if existing.get("user_id") != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own functions"
            )

    result = await db.functions.delete_one({"_id": ObjectId(function_id)})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Function not found")

    # Invalidate cache
    function_executor.invalidate_cache(function_id)

    logger.info(f"Function {function_id} deleted successfully")
    return {"message": "Function deleted successfully"}


@router.post("/{function_id}/execute", response_model=FunctionExecuteResponse)
async def execute_function(
    function_id: str,
    request: FunctionExecuteRequest,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """
    Execute a function with provided context.
    Available to all users who can access the function.
    """
    logger.info(f"Executing function {function_id}")
    db = await get_database()

    if not ObjectId.is_valid(function_id):
        raise HTTPException(status_code=400, detail="Invalid function ID")

    function = await db.functions.find_one({"_id": ObjectId(function_id)})

    if not function:
        raise HTTPException(status_code=404, detail="Function not found")

    # Authorization check
    if function.get("scope") == FunctionScope.TENANT:
        if function.get("tenant_id") != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Function not found")

    # Check if function is active
    if not function.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Function is not active"
        )

    # Execute the function
    start_time = time.time()
    try:
        result = await function_executor.execute(
            function_id=function_id,
            function_doc=function,
            context=request.context,
            db=db
        )
        execution_time_ms = (time.time() - start_time) * 1000

        # Update execution stats (async, non-blocking)
        await db.functions.update_one(
            {"_id": ObjectId(function_id)},
            {
                "$set": {"last_executed_at": datetime.utcnow()},
                "$inc": {"execution_count": 1}
            }
        )

        return FunctionExecuteResponse(
            result=result,
            execution_time_ms=execution_time_ms,
            error=None
        )
    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000
        logger.error(f"Function execution failed: {str(e)}")
        return FunctionExecuteResponse(
            result=None,
            execution_time_ms=execution_time_ms,
            error=str(e)
        )


@router.get("/search/query", response_model=List[Function])
async def search_functions(
    q: Optional[str] = Query(None, description="Search in name, description"),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Search functions by name or description"""
    logger.info(f"Searching functions with query: {q}")
    db = await get_database()

    # Base query: accessible functions
    base_query = {
        "$or": [
            {"tenant_id": current_user.tenant_id, "scope": FunctionScope.TENANT},
            {"scope": FunctionScope.GLOBAL}
        ]
    }

    if q:
        # Combine base access control with search
        query = {
            "$and": [
                base_query,
                {
                    "$or": [
                        {"name": {"$regex": q, "$options": "i"}},
                        {"description": {"$regex": q, "$options": "i"}},
                    ]
                }
            ]
        }
    else:
        query = base_query

    cursor = db.functions.find(query).sort("created_at", -1)
    functions = await cursor.to_list(length=100)

    logger.info(f"Found {len(functions)} functions matching query")
    return [_build_function_response(func) for func in functions]


def _build_function_response(function_doc: dict) -> Function:
    """Helper to build Function response from database document"""
    return Function(
        id=str(function_doc["_id"]),
        name=function_doc["name"],
        description=function_doc.get("description", ""),
        function_type=function_doc["function_type"],
        scope=function_doc["scope"],
        tenant_id=function_doc.get("tenant_id"),
        user_id=function_doc["user_id"],
        tags=function_doc.get("tags", []),
        code_template=function_doc.get("code_template"),
        code_python=function_doc.get("code_python"),
        code_source=function_doc["code_source"],
        compiled_code=function_doc["compiled_code"],
        compilation_error=function_doc.get("compilation_error"),
        referenced_functions=function_doc.get("referenced_functions", []),
        parameter_schema=function_doc.get("parameter_schema"),
        return_type=function_doc.get("return_type", "any"),
        is_active=function_doc.get("is_active", True),
        created_at=function_doc["created_at"],
        updated_at=function_doc["updated_at"],
        created_by_user_id=function_doc["created_by_user_id"],
        last_executed_at=function_doc.get("last_executed_at"),
        execution_count=function_doc.get("execution_count", 0)
    )
