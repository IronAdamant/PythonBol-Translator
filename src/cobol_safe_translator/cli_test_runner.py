"""Test runner for the COBOL-to-Python CLI.

Provides the ``test`` subcommand: translate, validate, and optionally
execute generated Python for one or more COBOL source files.
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import batch as _batch
from .analyzer import analyze
from .cli import bold, green, red, _to_python_filename
from .mapper import generate_python
from .parser import parse_cobol_file
from .validation import validate_generated_python


# --- Test helpers ---

def _test_execute(source: str, timeout: int = 10) -> tuple[bool, str, str]:
    """Run generated Python in a subprocess. Returns (success, stdout, stderr)."""
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(source)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"TIMEOUT after {timeout}s"
    finally:
        os.unlink(tmp_path)


def _test_single(
    src: Path,
    out_dir: Path,
    config: str | None,
    copy_paths: list[str] | None = None,
    timeout: int = 10,
    no_execute: bool = False,
) -> tuple[int, list[tuple[str, bool, str]]]:
    """Test one COBOL file through the full pipeline.

    Returns (exit_code, checks) where checks is a list of (name, passed, detail).
    """
    checks: list[tuple[str, bool, str]] = []
    source_path = src

    if not source_path.exists() or not source_path.is_file():
        checks.append(("Parse", False, f"file not found: {source_path}"))
        return 1, checks

    print(bold(f"Testing: {source_path}"))

    # 1. Parse
    t0 = time.monotonic()
    try:
        program = parse_cobol_file(
            source_path, copy_paths=copy_paths or []
        )
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        checks.append(("Parse", False, detail))
        print(f"  Parse:      {red('FAIL')} -- {detail}")
        return 1, checks
    elapsed = time.monotonic() - t0
    n_para = len(program.paragraphs)
    pid = program.program_id or src.stem
    checks.append(("Parse", True, f"{pid}, {n_para} paragraphs, {elapsed:.2f}s"))
    print(f"  Parse:      {green('OK')}  ({pid}, {n_para} paragraphs, {elapsed:.2f}s)")

    # 2. Analyze
    t0 = time.monotonic()
    try:
        smap = analyze(program, config_path=config)
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        checks.append(("Analyze", False, detail))
        print(f"  Analyze:    {red('FAIL')} -- {detail}")
        return 1, checks
    elapsed = time.monotonic() - t0
    n_sens = len(smap.sensitivities)
    n_deps = len(smap.dependencies)
    checks.append(("Analyze", True, f"{n_sens} sensitivities, {n_deps} dependencies"))
    print(f"  Analyze:    {green('OK')}  ({n_sens} sensitivities, {n_deps} dependencies)")

    # 3. Generate Python
    t0 = time.monotonic()
    try:
        python_source = generate_python(smap)
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        checks.append(("Generate", False, detail))
        print(f"  Generate:   {red('FAIL')} -- {detail}")
        return 1, checks
    elapsed = time.monotonic() - t0
    n_lines = python_source.count("\n")
    checks.append(("Generate", True, f"{n_lines} lines"))
    print(f"  Generate:   {green('OK')}  ({n_lines} lines)")

    # Write output file
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = _to_python_filename(pid)
        out_path = out_dir / out_name
        out_path.write_text(python_source, encoding="utf-8")
    except OSError:
        pass  # non-fatal for test mode

    # 4. Syntax check
    try:
        ast.parse(python_source)
    except SyntaxError as e:
        detail = f"SyntaxError: {e.msg} (line {e.lineno})"
        checks.append(("Syntax", False, detail))
        print(f"  Syntax:     {red('FAIL')} -- {detail}")
        return 1, checks
    checks.append(("Syntax", True, "ast.parse passed"))
    print(f"  Syntax:     {green('OK')}  (ast.parse passed)")

    # 5. Import validation
    is_valid, err_msg = validate_generated_python(python_source, str(src))
    if not is_valid:
        checks.append(("Validate", False, err_msg))
        print(f"  Validate:   {red('FAIL')} -- {err_msg}")
        return 1, checks
    checks.append(("Validate", True, "import + instantiate passed"))
    print(f"  Validate:   {green('OK')}  (import + instantiate passed)")

    # 6. Execution test (optional)
    if not no_execute:
        t0 = time.monotonic()
        success, stdout, stderr = _test_execute(python_source, timeout=timeout)
        elapsed = time.monotonic() - t0
        if success:
            checks.append(("Execute", True, f"exit 0, {elapsed:.2f}s"))
            print(f"  Execute:    {green('OK')}  (exit 0, {elapsed:.2f}s)")
            output_preview = stdout.strip()
            if output_preview:
                # Show first line of output, truncated
                first_line = output_preview.split("\n")[0]
                if len(first_line) > 60:
                    first_line = first_line[:57] + "..."
                print(f"  Output:     \"{first_line}\"")
        else:
            err_detail = stderr.strip().split("\n")[-1] if stderr.strip() else "non-zero exit"
            checks.append(("Execute", False, err_detail))
            print(f"  Execute:    {red('FAIL')} -- {err_detail}")
            return 1, checks

    total = len(checks)
    passed = sum(1 for _, ok, _ in checks if ok)
    if passed == total:
        print(f"\n  Result: {green(f'{passed}/{total} checks passed')} {green(chr(10003))}")
    else:
        failed_at = next(name for name, ok, _ in checks if not ok)
        print(f"\n  Result: {red(f'{passed}/{total} checks passed, stopped at {failed_at}')} {red(chr(10007))}")

    return 0 if passed == total else 1, checks


# --- Subcommand entry point ---

def cmd_test(args: argparse.Namespace) -> int:
    """Translate, validate, and test-run COBOL programs."""
    p = Path(args.path)
    config = args.config
    copy_paths = args.copybook_path
    timeout = args.timeout
    no_execute = args.no_execute
    out_dir = Path(args.output)

    if p.is_dir():
        files = _batch.discover_cobol_files(p, recursive=args.recursive)
        if not files:
            print(red(f"Error: no COBOL files found in {p}"), file=sys.stderr)
            return 1

        print(bold(f"Testing {len(files)} files in {p}...\n"))

        all_results: list[tuple[Path, list[tuple[str, bool, str]]]] = []
        n_passed = 0

        for src in files:
            file_out_dir = out_dir / src.stem
            rc, checks = _test_single(
                src, file_out_dir, config, copy_paths, timeout, no_execute
            )
            all_results.append((src, checks))
            if rc == 0:
                n_passed += 1
            print()  # blank line between files

        # Summary
        n_total = len(files)
        n_failed = n_total - n_passed
        print(bold("=" * 60))
        if n_failed == 0:
            print(bold(green(f"Summary: {n_passed}/{n_total} passed all checks")))
        else:
            print(bold(f"Summary: {green(f'{n_passed}/{n_total}')} passed all checks, "
                        f"{red(f'{n_failed} failed')}"))
            for src, checks in all_results:
                failed = [name for name, ok, _ in checks if not ok]
                if failed:
                    print(f"  {red('FAIL')}  {src.name}: stopped at {failed[0]}")

        return 0 if n_failed == 0 else 1

    # Single file mode
    if not p.exists() or not p.is_file():
        print(red(f"Error: file not found: {p}"), file=sys.stderr)
        return 1

    rc, _checks = _test_single(p, out_dir, config, copy_paths, timeout, no_execute)
    return rc
