from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Guards import guarded_iter_unpack_sequence, safe_builtins
from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
import logging
from typing import Any, Dict, Tuple, Optional

logger = logging.getLogger(__name__)


class RestrictedExecutor:
    """
    Safely compiles and executes Python code using RestrictedPython.

    RestrictedPython prevents:
    - File system access
    - Network access
    - Import of dangerous modules
    - Access to private attributes
    - Infinite loops (via timeout wrapper)
    """

    def __init__(self):
        # Define safe globals with restricted builtins
        self.safe_globals = {
            '__builtins__': self._get_safe_builtins(),
            '_getiter_': default_guarded_getiter,
            '_iter_unpack_sequence_': guarded_iter_unpack_sequence,
            '_getitem_': default_guarded_getitem,
        }

    def _get_safe_builtins(self) -> Dict[str, Any]:
        """
        Define allowed built-in functions.
        Start with safe_builtins and add carefully selected functions.
        """
        allowed = safe_builtins.copy()

        # Add safe mathematical and utility functions
        allowed.update({
            'abs': abs,
            'max': max,
            'min': min,
            'round': round,
            'len': len,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'set': set,
            'tuple': tuple,
            'sum': sum,
            'any': any,
            'all': all,
            'sorted': sorted,
            'enumerate': enumerate,
            'zip': zip,
            'map': map,
            'filter': filter,
            'range': range,
        })

        # Explicitly BLOCKED (already restricted by RestrictedPython):
        # - open, exec, eval, compile, __import__
        # - file, input, raw_input
        # - reload, vars, dir, locals, globals

        return allowed

    def compile(self, code: str, filename: str = "<string>") -> Tuple[Optional[Any], Optional[str]]:
        """
        Compile Python code with RestrictedPython.

        Args:
            code: Python code string to compile
            filename: Optional filename for error messages

        Returns:
            Tuple of (compiled_code_object, error_message)
            If compilation succeeds: (code_object, None)
            If compilation fails: (None, error_message)
        """
        try:
            byte_code = compile_restricted(
                code,
                filename=filename,
                mode='exec'
            )

            # Check if byte_code is a CompileResult object or direct code object
            if hasattr(byte_code, 'errors'):
                # CompileResult object
                if byte_code.errors:
                    error_msg = "; ".join(byte_code.errors)
                    logger.error(f"RestrictedPython compilation errors: {error_msg}")
                    return None, error_msg
                return byte_code.code, None
            else:
                # Direct code object (older API or successful compilation)
                return byte_code, None

        except SyntaxError as e:
            error_msg = f"Syntax error: {str(e)}"
            logger.error(f"Syntax error in code compilation: {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = f"Compilation error: {str(e)}"
            logger.error(f"Unexpected compilation error: {error_msg}")
            return None, error_msg

    def execute(self, compiled_code: Any, local_vars: Dict[str, Any]) -> Any:
        """
        Execute compiled RestrictedPython code.

        Args:
            compiled_code: Compiled code object from compile()
            local_vars: Local variables to make available (e.g., {'ctx': context_dict})

        Returns:
            Result of the execute() function defined in the code

        Raises:
            Exception: Any runtime error from the executed code
        """
        # Create execution namespace with safe globals + local vars
        exec_globals = self.safe_globals.copy()
        exec_locals = local_vars.copy()

        try:
            # Execute the code (defines the 'execute' function)
            exec(compiled_code, exec_globals, exec_locals)

            # Call the execute() function
            if 'execute' not in exec_locals:
                raise ValueError("Code must define an 'execute(ctx)' function")

            execute_func = exec_locals['execute']

            # If ctx is in local_vars, pass it to execute
            if 'ctx' in local_vars:
                result = execute_func(local_vars['ctx'])
            else:
                result = execute_func({})

            return result

        except Exception as e:
            logger.error(f"Runtime error during execution: {str(e)}")
            raise
