"""Runtime import validation for generated Python code.

Goes beyond ast.parse() syntax checking to catch NameErrors, undefined
references, and import failures by actually loading the generated module
in an isolated environment.

Zero external dependencies — uses only Python 3.11+ stdlib.
"""

from __future__ import annotations

import ast
import importlib
import os
import shutil
import sys
import tempfile


def validate_generated_python(
    source_code: str, filename: str = "<generated>"
) -> tuple[bool, str]:
    """Validate generated Python beyond syntax.

    Performs two progressively deeper checks:
      1. ast.parse()  — syntax check
      2. Simulated import with real adapters — catches NameError, ImportError

    The generated code imports from cobol_safe_translator.adapters, which is
    part of this project (zero-dep), so the adapters are available at import
    time.  The module is loaded in an isolated temporary file and cleaned up
    afterwards.

    Args:
        source_code: The Python source code string to validate.
        filename: Filename used in error messages (default ``<generated>``).

    Returns:
        Tuple of (is_valid, error_message).
        *error_message* is ``""`` when the code is valid.
    """
    # Step 1: syntax check
    try:
        ast.parse(source_code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg} (line {e.lineno})"

    # Step 2: import test — write to temp dir, import, instantiate Program
    tmp_dir_obj = tempfile.mkdtemp()
    try:
        tmp_path = os.path.join(tmp_dir_obj, "generated_module.py")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(source_code)

        module_name = "generated_module"

        sys.path.insert(0, tmp_dir_obj)
        try:
            mod = importlib.import_module(module_name)

            # Instantiate any *Program class to catch runtime init errors
            for name in dir(mod):
                obj = getattr(mod, name)
                if isinstance(obj, type) and name.endswith("Program"):
                    obj()  # should not crash
                    break
        finally:
            sys.path.remove(tmp_dir_obj)
            if module_name in sys.modules:
                del sys.modules[module_name]
    except Exception as e:
        return False, f"ImportError: {type(e).__name__}: {e}"
    finally:
        shutil.rmtree(tmp_dir_obj, ignore_errors=True)

    return True, ""
