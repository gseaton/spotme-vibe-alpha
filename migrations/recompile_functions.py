#!/usr/bin/env python3
"""
Recompile all template-based functions to fix any ctx prefix issues.
Run this after updating the function_parser.py to strip ctx prefixes.
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from app.database import connect_to_mongo, close_mongo_connection, db
from app.services.function_parser import FunctionParser
from app.models import FunctionCreate, CodeSource
from app.config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


async def recompile_all_functions():
    """Recompile all template-based functions with updated parser."""
    # Initialize database connection
    await connect_to_mongo()

    client = db.client
    database = client[settings.database_name]
    parser = FunctionParser()

    # Find all functions with template code
    cursor = database.functions.find({"code_source": CodeSource.TEMPLATE})
    functions = await cursor.to_list(length=None)

    logger.info(f"Found {len(functions)} template-based functions to recompile")

    recompiled_count = 0
    error_count = 0

    for func in functions:
        function_id = str(func["_id"])
        function_name = func.get("name", "unknown")

        try:
            # Create FunctionCreate model from existing data
            func_create = FunctionCreate(
                name=func["name"],
                description=func.get("description"),
                function_type=func["function_type"],
                scope=func["scope"],
                return_type=func.get("return_type"),
                code_template=func.get("code_template"),
                tags=func.get("tags", [])
            )

            # Recompile with updated parser
            compilation_result = parser.parse_and_compile(func_create)

            # Update the function in database
            update_data = {
                "compiled_code": compilation_result["compiled_code"],
                "referenced_functions": compilation_result["referenced_functions"],
                "compilation_error": compilation_result.get("compilation_error")
            }

            result = await database.functions.update_one(
                {"_id": func["_id"]},
                {"$set": update_data}
            )

            if result.modified_count > 0:
                logger.info(f"✓ Recompiled: {function_name} ({function_id})")
                recompiled_count += 1
            else:
                logger.info(f"- No change: {function_name} ({function_id})")

        except Exception as e:
            logger.error(f"✗ Error recompiling {function_name} ({function_id}): {str(e)}")
            error_count += 1

    logger.info(f"\nRecompilation complete:")
    logger.info(f"  - Recompiled: {recompiled_count}")
    logger.info(f"  - Unchanged: {len(functions) - recompiled_count - error_count}")
    logger.info(f"  - Errors: {error_count}")

    # Close database connection
    await close_mongo_connection()


if __name__ == "__main__":
    print("=" * 60)
    print("Function Recompilation Script")
    print("=" * 60)
    print("\nThis will recompile all template-based functions with the")
    print("updated parser that fixes the double 'ctx' prefix issue.")
    print()

    response = input("Continue? [y/N]: ").strip().lower()
    if response != 'y':
        print("Aborted.")
        sys.exit(0)

    asyncio.run(recompile_all_functions())
    print("\nDone!")
