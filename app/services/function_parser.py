import re
from typing import Dict, Any, List, Tuple
from app.models import FunctionCreate, CodeSource
import logging

logger = logging.getLogger(__name__)


class FunctionParser:
    """
    Parses template syntax and converts to Python code.

    Template syntax:
    - Variables: $[variable.path]$ → ctx["variable"]["path"]
    - Function calls: ^[function_id]^(args) → call to another function
    - Predicates: Standard Python operators (AND, OR, <=, >=, etc.)
    """

    # Regex patterns
    VARIABLE_PATTERN = re.compile(r'\$\[([^\]]+)\]\$')
    FUNCTION_CALL_PATTERN = re.compile(r'\^\[([^\]]+)\]\^\(([^)]*)\)')

    def parse_and_compile(self, function: FunctionCreate) -> Dict[str, Any]:
        """
        Parse function input and return compilation result.

        Args:
            function: FunctionCreate model with either code_template or code_python

        Returns:
            Dict with keys:
            - code_source: "template" or "python"
            - compiled_code: Python code string
            - referenced_functions: List of function IDs
            - compilation_error: Error message if any
        """
        result = {
            "referenced_functions": [],
            "compilation_error": None
        }

        if function.code_template:
            result["code_source"] = CodeSource.TEMPLATE
            try:
                compiled_code, referenced_funcs = self._parse_template(function.code_template)
                result["compiled_code"] = compiled_code
                result["referenced_functions"] = referenced_funcs
            except Exception as e:
                result["compilation_error"] = f"Template parsing error: {str(e)}"
                result["compiled_code"] = ""

        elif function.code_python:
            result["code_source"] = CodeSource.PYTHON
            result["compiled_code"] = function.code_python
            # Extract function references from Python code
            result["referenced_functions"] = self._extract_function_refs(function.code_python)
        else:
            raise ValueError("No code provided")

        return result

    def _parse_template(self, template: str) -> Tuple[str, List[str]]:
        """
        Parse template syntax and convert to Python code.

        Args:
            template: Template string with $[var]$ and ^[func]^ syntax

        Returns:
            Tuple of (python_code, referenced_function_ids)
        """
        code = template
        referenced_functions = []

        # Step 1: Extract and replace function calls
        # ^[function_id]^(arg1, arg2) → __func_call__('function_id', arg1, arg2)
        def replace_function_call(match):
            func_id = match.group(1)
            args = match.group(2)
            referenced_functions.append(func_id)
            return f"__func_call__('{func_id}', {args})"

        code = self.FUNCTION_CALL_PATTERN.sub(replace_function_call, code)

        # Step 2: Replace variable references
        # $[variable.path]$ → ctx["variable"]["path"]
        def replace_variable(match):
            path = match.group(1)
            parts = path.split('.')

            # Strip leading 'ctx' if present to avoid ctx["ctx"]["..."]
            # Users might write $[ctx.n]$ when they should write $[n]$
            if parts and parts[0] == 'ctx':
                parts = parts[1:]
                if not parts:
                    # Edge case: just $[ctx]$ with no property
                    return "ctx"

            # Build nested dictionary access
            access = "ctx"
            for part in parts:
                access += f'["{part}"]'
            return access

        code = self.VARIABLE_PATTERN.sub(replace_variable, code)

        # Step 3: Handle common template patterns
        # Replace AND/OR with Python equivalents
        code = code.replace(' AND ', ' and ')
        code = code.replace(' OR ', ' or ')
        code = code.replace(' NOT ', ' not ')

        # Step 4: Wrap in function definition
        # Determine if this is an expression or statement
        if '\n' in code or code.strip().startswith('if ') or code.strip().startswith('for '):
            # Multi-line or statement - wrap as-is
            python_code = f"def execute(ctx):\n    {code}"
        else:
            # Single expression - wrap with return
            python_code = f"def execute(ctx):\n    return {code}"

        logger.debug(f"Template parsed to Python:\n{python_code}")
        return python_code, referenced_functions

    def _extract_function_refs(self, python_code: str) -> List[str]:
        """
        Extract function IDs from __func_call__ in Python code.

        Args:
            python_code: Python code string

        Returns:
            List of referenced function IDs (deduplicated)
        """
        matches = re.findall(r'__func_call__\([\'"]([^\'"]+)[\'"]', python_code)
        return list(set(matches))  # Deduplicate
