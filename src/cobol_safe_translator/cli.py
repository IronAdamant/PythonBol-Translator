"""CLI entry point for the COBOL-to-Python safe translator.

Usage:
    cobol2py translate <path> [--output ./translated] [--recursive]
    cobol2py map <path> [--output ./report] [--recursive]
    cobol2py prompt <path> [--output /path/to/brief.md] [--recursive]
    cobol2py test <path> [--output ./test-output] [--timeout 10] [--no-execute]
"""

from __future__ import annotations

import argparse
import sys
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
                      validate: bool = False,
                      tests: bool = False,
                      incremental: bool = False) -> int:
    """Translate one COBOL file to Python; write to out_dir."""
    if incremental:
        return _translate_single_incremental(
            src, out_dir, config, copy_paths, validate, tests,
        )

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

    # Generate CICS Flask template as a separate file if applicable
    from .cics_translator import has_cics, generate_cics_template
    if has_cics(smap.program):
        cics_template = generate_cics_template(smap.program)
        if cics_template:
            flask_name = out_name.replace(".py", "") + "_flask.py"
            flask_path = out_dir / flask_name
            try:
                flask_path.write_text(cics_template, encoding="utf-8")
                print(green(f"  CICS template: {flask_path}"))
            except OSError:
                pass  # non-fatal

    # Generate pytest regression tests alongside translation
    if tests:
        from .test_generator import generate_tests
        module_stem = out_name.replace('.py', '')
        test_source = generate_tests(smap, module_stem)
        test_path = out_dir / f"{module_stem}_test.py"
        try:
            test_path.write_text(test_source, encoding="utf-8")
            print(green(f"  Tests: {test_path}"))
        except OSError:
            pass  # non-fatal

    if validate:
        is_valid, err_msg = validate_generated_python(python_source, str(out_path))
        if is_valid:
            print(green("  Validation: passed (syntax + compile + import)"))
        else:
            print(red(f"  Validation FAILED: {err_msg}"), file=sys.stderr)
            return 1

    print(bold(green("Done.")))
    return 0


def _translate_single_incremental(
    src: Path, out_dir: Path, config: str | None,
    copy_paths: list[str] | None = None,
    validate: bool = False,
    tests: bool = False,
) -> int:
    """Translate one COBOL file using incremental (diff-based) strategy."""
    from .incremental import incremental_translate

    source_path = Path(src)
    if not source_path.exists() or not source_path.is_file():
        print(red(f"Error: file not found: {source_path}"), file=sys.stderr)
        return 1

    print(bold(f"Translating (incremental): {source_path}"))

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Need to determine output filename -- parse minimally for program_id
        from .parser import parse_cobol_file as _pcf
        prog = _pcf(source_path, copy_paths=copy_paths)
        pid = prog.program_id or src.stem
    except OSError as e:
        print(red(f"Error: could not read file: {e}"), file=sys.stderr)
        return 1

    out_name = _to_python_filename(pid)
    out_path = out_dir / out_name

    try:
        python_source, diff = incremental_translate(
            source_path, out_path,
            copy_paths=copy_paths, config_path=config,
        )
    except Exception as e:
        print(red(f"Error: translation failed: {e}"), file=sys.stderr)
        return 1

    # Report what happened
    if diff.get("full_retranslation_needed"):
        print(yellow(f"  Full retranslation: {diff.get('reason', 'structural changes')}"))
    else:
        modified = diff.get("paragraphs_modified", [])
        if modified:
            print(green(f"  Incremental: patched {len(modified)} paragraphs"))
        else:
            print(green(f"  No changes detected"))

    # Write output
    try:
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


# --- Subcommands ---

def cmd_translate(args: argparse.Namespace) -> int:
    """Parse, analyze, and generate Python translation."""
    p = Path(args.path)
    config = args.config
    copy_paths = args.copybook_path
    validate = args.validate
    tests = args.tests
    incremental = args.incremental

    if p.is_dir():
        # Package mode: unified Python package with cross-program imports
        if args.package:
            from .project_analyzer import analyze_project, generate_package
            project_map = analyze_project(
                p, recursive=args.recursive,
                copy_paths=copy_paths, config_path=config,
            )
            if not project_map.programs:
                print(red(f"Error: no COBOL files found in {p}"), file=sys.stderr)
                return 1
            files = generate_package(project_map, Path(args.output))
            print(green(f"Generated package with {len(files)} files"))
            if project_map.entry_points:
                print(f"  Entry points: {', '.join(project_map.entry_points)}")
            if project_map.unresolved_calls:
                for prog, targets in sorted(project_map.unresolved_calls.items()):
                    for t in targets:
                        print(yellow(f"  Unresolved CALL: {prog} -> {t}"))
            return 0

        base_out = Path(args.output)

        def process(src: Path, out_dir: Path) -> int:
            return _translate_single(
                src, out_dir, config, copy_paths, validate, tests, incremental,
            )

        return _batch.run_batch(p, base_out, args.recursive, process)

    return _translate_single(
        p, Path(args.output), config, copy_paths, validate, tests, incremental,
    )


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

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("path", help="COBOL source file or directory")
    common.add_argument("--config", "-c", default=None, help="Path to protected.json config")
    common.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories")
    common.add_argument("--copybook-path", "-I", action="append", default=[], help="COPY copybook search dir (repeatable)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # translate subcommand
    tr = subparsers.add_parser(
        "translate", parents=[common],
        help="Translate COBOL source to Python skeleton",
    )
    tr.add_argument("--output", "-o", default="./translated", help="Output directory")
    tr.add_argument("--validate", action="store_true", default=False, help="Validate generated Python")
    tr.add_argument("--incremental", action="store_true", default=False, help="Incremental re-translation")
    tr.add_argument("--tests", action="store_true", default=False, help="Generate pytest tests alongside")
    tr.add_argument("--package", action="store_true", default=False, help="Unified package with cross-program imports")

    # map subcommand
    mp = subparsers.add_parser(
        "map", parents=[common],
        help="Generate analysis reports (Markdown + JSON)",
    )
    mp.add_argument("--output", "-o", default="./report", help="Output directory")

    # prompt subcommand
    pr = subparsers.add_parser(
        "prompt", parents=[common],
        help="Generate a compact LLM translation brief",
    )
    pr.add_argument("--output", "-o", default=None, help="Output file/dir (default: stdout)")

    # test subcommand
    ts = subparsers.add_parser(
        "test", parents=[common],
        help="Translate, validate, and test-run COBOL programs",
    )
    ts.add_argument("--output", "-o", default="./test-output", help="Output directory")
    ts.add_argument("--timeout", type=int, default=10, help="Execution timeout in seconds")
    ts.add_argument("--no-execute", action="store_true", help="Skip execution (validate only)")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    from .cli_test_runner import cmd_test  # lazy to avoid circular import
    dispatch = {"translate": cmd_translate, "map": cmd_map, "prompt": cmd_prompt, "test": cmd_test}
    handler = dispatch.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 1


def __getattr__(name: str):  # noqa: N807
    """Lazy re-export of cmd_test to avoid circular import with cli_test_runner."""
    if name == "cmd_test":
        from .cli_test_runner import cmd_test
        return cmd_test
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
