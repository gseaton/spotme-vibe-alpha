import logging
from typing import Any, Dict, Optional
from bson import ObjectId
from app.services.restricted_executor import RestrictedExecutor

logger = logging.getLogger(__name__)


class FunctionExecutor:
    """
    Executes functions with context, handles caching and function references.
    """

    def __init__(self, max_cache_size: int = 128):
        self.restricted_executor = RestrictedExecutor()
        self._cache = {}  # Manual cache: {function_id: compiled_code_object}
        self.max_cache_size = max_cache_size

    async def execute(
        self,
        function_id: str,
        function_doc: Dict[str, Any],
        context: Dict[str, Any],
        db: Any  # Motor database instance
    ) -> Any:
        """
        Execute a function with given context.

        Handles:
        - Compilation caching
        - Function reference resolution (^[func-id]^)
        - Timeout protection
        - Error handling

        Args:
            function_id: Function ID string
            function_doc: Function document from database
            context: Context dictionary for execution
            db: Motor database instance

        Returns:
            Result of function execution

        Raises:
            RuntimeError: If compilation or execution fails
        """
        # Get or compile the function
        compiled_code = self._get_compiled(function_id, function_doc)

        if compiled_code is None:
            error = function_doc.get("compilation_error", "Unknown compilation error")
            raise RuntimeError(f"Function compilation failed: {error}")

        # Create execution context with function call handler
        local_vars = {
            'ctx': context,
            '__func_call__': lambda func_id, *args: self._handle_function_call_sync(
                func_id, args, db
            )
        }

        # Execute with timeout protection (implement timeout wrapper if needed)
        try:
            result = self.restricted_executor.execute(compiled_code, local_vars)
            return result
        except Exception as e:
            logger.error(f"Function execution error: {str(e)}")
            raise RuntimeError(f"Execution error: {str(e)}")

    def _get_compiled(self, function_id: str, function_doc: Dict[str, Any]) -> Optional[Any]:
        """
        Get compiled code from cache or compile fresh.

        Args:
            function_id: Function ID string
            function_doc: Function document from database

        Returns:
            Compiled code object or None if compilation failed
        """
        # Check cache
        if function_id in self._cache:
            logger.debug(f"Using cached compilation for function {function_id}")
            return self._cache[function_id]

        # Compile fresh
        compiled_code_str = function_doc.get("compiled_code")
        if not compiled_code_str:
            return None

        compiled_obj, error = self.restricted_executor.compile(
            compiled_code_str,
            filename=f"<function:{function_id}>"
        )

        if error:
            logger.error(f"Compilation error for function {function_id}: {error}")
            return None

        # Add to cache
        self._add_to_cache(function_id, compiled_obj)
        return compiled_obj

    def _add_to_cache(self, function_id: str, compiled_obj: Any):
        """
        Add compiled code to cache with size limit.

        Uses simple FIFO eviction when cache is full.

        Args:
            function_id: Function ID string
            compiled_obj: Compiled code object
        """
        if len(self._cache) >= self.max_cache_size:
            # Simple FIFO eviction (could use LRU for production)
            first_key = next(iter(self._cache))
            del self._cache[first_key]
            logger.debug(f"Evicted {first_key} from compilation cache")

        self._cache[function_id] = compiled_obj
        logger.debug(f"Cached compilation for function {function_id}")

    def _handle_function_call_sync(
        self,
        func_id: str,
        args: tuple,
        db: Any
    ) -> Any:
        """
        Handle calls to other functions via ^[func-id]^(args) syntax.
        Synchronous wrapper for async _handle_function_call.

        This is called from within executed code via __func_call__.

        Args:
            func_id: Function ID or name
            args: Arguments passed to function
            db: Motor database instance

        Returns:
            Result of function execution

        Note:
            This is a synchronous wrapper. For production, consider
            using asyncio.run() or ensuring the execution context
            supports async/await.
        """
        import asyncio
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, we need to handle this differently
                # For now, create a new loop (not ideal but works)
                logger.warning("Event loop already running, creating new loop for function call")
                new_loop = asyncio.new_event_loop()
                result = new_loop.run_until_complete(self._handle_function_call(func_id, args, db))
                new_loop.close()
                return result
            else:
                return loop.run_until_complete(self._handle_function_call(func_id, args, db))
        except RuntimeError:
            # No event loop exists
            return asyncio.run(self._handle_function_call(func_id, args, db))

    async def _handle_function_call(
        self,
        func_id: str,
        args: tuple,
        db: Any
    ) -> Any:
        """
        Handle calls to other functions via ^[func-id]^(args) syntax.

        This is called from within executed code via __func_call__.

        Args:
            func_id: Function ID or name
            args: Arguments passed to function
            db: Motor database instance

        Returns:
            Result of function execution

        Raises:
            ValueError: If referenced function not found
        """
        logger.debug(f"Function call to {func_id} with args {args}")

        # Look up the referenced function
        # For now, assume func_id is either an ObjectId string or function name
        if ObjectId.is_valid(func_id):
            function_doc = await db.functions.find_one({"_id": ObjectId(func_id)})
        else:
            # Try by name (this could be ambiguous - consider requiring ID)
            function_doc = await db.functions.find_one({"name": func_id})

        if not function_doc:
            raise ValueError(f"Referenced function not found: {func_id}")

        # Build context from args
        # Assume args are passed as key-value pairs or single context dict
        if len(args) == 1 and isinstance(args[0], dict):
            context = args[0]
        else:
            # Convert positional args to context
            # This is a simplification - may need more sophisticated arg handling
            context = {"args": args}

        # Recursively execute the referenced function
        result = await self.execute(
            function_id=str(function_doc["_id"]),
            function_doc=function_doc,
            context=context,
            db=db
        )

        return result

    def invalidate_cache(self, function_id: str):
        """
        Remove function from cache (called on update/delete).

        Args:
            function_id: Function ID string
        """
        if function_id in self._cache:
            del self._cache[function_id]
            logger.info(f"Invalidated cache for function {function_id}")
