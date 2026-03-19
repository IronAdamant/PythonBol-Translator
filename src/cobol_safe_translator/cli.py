"""CLI entry point for the COBOL-to-Python safe translator.

Usage:
    cobol2py translate <path> [--output ./translated] [--recursive]
    cobol2py map <path> [--output ./report] [--recursive]
    cobol2py prompt <path> [--output /path/to/brief.md] [--recursive]
    cobol2py test <path> [--output ./test-output] [--timeout 10] [--no-execute]
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from . import __version__
from . import batch as _batch
from .analyzer import analyze
from .exporters import export_json, export_markdown
from .mapper import generate_python
from .parser import parse_cobol_file
from .prompt_generator import generate_prompt
from .models import CobolProgram, SoftwareMap
from .utils import _to_python_name
from .validation import validate_generated_python


# --- ANSI color helpers (no rich dependency) ---

@lru_cache(maxsize=1)
def _supports_color() -> bool:
    """Check if the terminal supports ANSI colors (cached)."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return _c("32", text)


def yellow(text: str) -> str:
    return _c("33", text)


def red(text: str) -> str:
    return _c("31", text)


def bold(text: str) -> str:
    return _c("1", text)


# --- Shared helpers ---

def _parse_and_analyze(args: argparse.Namespace, label: str) -> tuple[int, CobolProgram | None, SoftwareMap | None]:
    """Parse and analyze a COBOL source file. Returns (exit_code, program, smap)."""
    source_path = Path(args.path)

    if not source_path.exists() or not source_path.is_file():
        print(red(f"Error: file not found: {source_path}"), file=sys.stderr)
        return 1, None, None

    print(bold(f"{label}: {source_path}"))

    copy_paths = args.copybook_path

    # Parse
    try:
        program = parse_cobol_file(source_path, copy_paths=copy_paths)
    except OSError as e:
        print(red(f"Error: could not read file: {e}"), file=sys.stderr)
        return 1, None, None
    print(green(f"  Parsed: {program.program_id} ({len(program.paragraphs)} paragraphs)"))

    # Analyze
    smap = analyze(program, config_path=args.config)

    if smap.sensitivities:
        high = sum(1 for s in smap.sensitivities if s.level.value == "high")
        med = sum(1 for s in smap.sensitivities if s.level.value == "medium")
        low = sum(1 for s in smap.sensitivities if s.level.value == "low")
        print(yellow(f"  Sensitivities: {high} high, {med} medium, {low} low"))

    for w in smap.warnings:
        print(yellow(f"  Warning: {w}"))

    return 0, program, smap


def _to_python_filename(program_id: str) -> str:
    """Convert COBOL program ID to a safe Python filename."""
    return (_to_python_name(program_id) or "unnamed") + ".py"


# --- Single-file workers ---

def _translate_single(src: Path, out_dir: Path, config: str | None,
                      copy_paths: list[str] | None = None,
                      validate: bool = False) -> int:
    """Translate one COBOL file to Python; write to out_dir."""
    args = argparse.Namespace(path=str(src), config=config,
                              copybook_path=copy_paths or [])
    rc, program, smap = _parse_and_analyze(args, "Translating")
    if rc != 0 or program is None or smap is None:
        return rc

    python_source = generate_python(smap)

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        pid = program.program_id or src.stem
        out_name = _to_python_filename(pid)
        out_path = out_dir / out_name
        out_path.write_text(python_source, encoding="utf-8")
    except OSError as e:
        print(red(f"Error: could not write output: {e}"), file=sys.stderr)
        return 1

    print(green(f"  Output: {out_path}"))

    if validate:
        is_valid, err_msg = validate_generated_python(python_source, str(out_path))
        if is_valid:
            print(green("  Validation: passed (syntax + compile + import)"))
        else:
            print(red(f"  Validation FAILED: {err_msg}"), file=sys.stderr)
            return 1

    print(bold(green("Done.")))
    return 0


def _map_single(src: Path, out_dir: Path, config: str | None,
                 copy_paths: list[str] | None = None) -> int:
    """Generate analysis reports for one COBOL file; write to out_dir."""
    args = argparse.Namespace(path=str(src), config=config,
                              copybook_path=copy_paths or [])
    rc, program, smap = _parse_and_analyze(args, "Mapping")
    if rc != 0 or program is None or smap is None:
        return rc

    try:
        out_dir.mkdir(parents=True, exist_ok=True)

        md_report = export_markdown(smap)
        md_path = out_dir / "software-map.md"
        md_path.write_text(md_report, encoding="utf-8")
        print(green(f"  Markdown: {md_path}"))

        json_report = export_json(smap)
        json_path = out_dir / "software-map.json"
        json_path.write_text(json_report, encoding="utf-8")
        print(green(f"  JSON: {json_path}"))
    except OSError as e:
        print(red(f"Error: could not write output: {e}"), file=sys.stderr)
        return 1

    print(bold(green("Done.")))
    return 0


def _prompt_single(src: Path, out_path: Path | None, config: str | None,
                    copy_paths: list[str] | None = None) -> int:
    """Generate LLM brief for one COBOL file; write to out_path or stdout."""
    args = argparse.Namespace(path=str(src), config=config,
                              copybook_path=copy_paths or [])
    rc, program, smap = _parse_and_analyze(args, "Prompting")
    if rc != 0 or program is None or smap is None:
        return rc

    python_source = generate_python(smap)
    brief = generate_prompt(smap, python_source)

    if out_path is None:
        print(brief)
    else:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(brief, encoding="utf-8")
            print(green(f"  Brief: {out_path}"))
        except OSError as e:
            print(red(f"Error: could not write output: {e}"), file=sys.stderr)
            return 1

    print(bold(green("Done.")))
    return 0


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


# --- Subcommands ---

def cmd_translate(args: argparse.Namespace) -> int:
    """Parse, analyze, and generate Python translation."""
    p = Path(args.path)
    config = args.config
    copy_paths = args.copybook_path
    validate = args.validate

    if p.is_dir():
        base_out = Path(args.output)

        def process(src: Path, out_dir: Path) -> int:
            return _translate_single(src, out_dir, config, copy_paths, validate)

        return _batch.run_batch(p, base_out, args.recursive, process)

    return _translate_single(p, Path(args.output), config, copy_paths, validate)


def cmd_map(args: argparse.Namespace) -> int:
    """Parse, analyze, and export reports."""
    p = Path(args.path)
    config = args.config
    copy_paths = args.copybook_path

    if p.is_dir():
        base_out = Path(args.output)

        def process(src: Path, out_dir: Path) -> int:
            return _map_single(src, out_dir, config, copy_paths)

        return _batch.run_batch(p, base_out, args.recursive, process)

    return _map_single(p, Path(args.output), config, copy_paths)


def cmd_prompt(args: argparse.Namespace) -> int:
    """Generate an LLM translation brief (stdout or file)."""
    p = Path(args.path)
    config = args.config
    copy_paths = args.copybook_path
    output = args.output

    if p.is_dir():
        if output is None:
            print(red("Error: --output is required for directory prompt mode"), file=sys.stderr)
            return 1
        base_out = Path(output)

        def process(src: Path, out_dir: Path) -> int:
            brief_path = out_dir / f"{src.stem}_brief.md"
            return _prompt_single(src, brief_path, config, copy_paths)

        return _batch.run_batch(p, base_out, args.recursive, process)

    out_path = Path(output) if output else None
    return _prompt_single(p, out_path, config, copy_paths)


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


# --- Main CLI setup ---

def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser."""
    parser = argparse.ArgumentParser(
        prog="cobol2py",
        description="COBOL-to-Python safe translator — generates Python skeletons and analysis reports",
    )
    parser.add_argument(
        "--version", action="version", version=f"cobol2py {__version__}"
    )

    # Shared arguments for all subcommands
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("path", help="Path to COBOL source file or directory")
    common.add_argument(
        "--config", "-c", default=None,
        help="Path to protected.json config file",
    )
    common.add_argument(
        "--recursive", "-r", action="store_true",
        help="Recurse into subdirectories (directory mode only)",
    )
    common.add_argument(
        "--copybook-path", "-I", action="append", default=[],
        help="Directory to search for COPY copybooks (can be repeated)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # translate subcommand
    tr = subparsers.add_parser(
        "translate", parents=[common],
        help="Translate COBOL source to Python skeleton",
    )
    tr.add_argument(
        "--output", "-o", default="./translated",
        help="Output directory (default: ./translated)",
    )
    tr.add_argument(
        "--validate", action="store_true", default=False,
        help="Run import validation on generated Python (syntax + compile + import)",
    )

    # map subcommand
    mp = subparsers.add_parser(
        "map", parents=[common],
        help="Generate analysis reports (Markdown + JSON)",
    )
    mp.add_argument(
        "--output", "-o", default="./report",
        help="Output directory (default: ./report)",
    )

    # prompt subcommand
    pr = subparsers.add_parser(
        "prompt", parents=[common],
        help="Generate a compact LLM translation brief",
    )
    pr.add_argument(
        "--output", "-o", default=None,
        help="Output file or directory (default: stdout for single file)",
    )

    # test subcommand
    ts = subparsers.add_parser(
        "test", parents=[common],
        help="Translate, validate, and test-run COBOL programs",
    )
    ts.add_argument(
        "--output", "-o", default="./test-output",
        help="Output directory for generated Python (default: ./test-output)",
    )
    ts.add_argument(
        "--timeout", type=int, default=10,
        help="Execution timeout in seconds (default: 10)",
    )
    ts.add_argument(
        "--no-execute", action="store_true",
        help="Skip execution test (only validate syntax and imports)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    dispatch = {"translate": cmd_translate, "map": cmd_map, "prompt": cmd_prompt, "test": cmd_test}
    handler = dispatch.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
