"""CLI entry point for the COBOL-to-Python safe translator.

Usage:
    cobol2py translate <path> [--output ./translated] [--recursive]
    cobol2py map <path> [--output ./report] [--recursive]
    cobol2py prompt <path> [--output /path/to/brief.md] [--recursive]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import batch as _batch
from .analyzer import analyze
from .exporters import export_json, export_markdown
from .mapper import generate_python
from .parser import parse_cobol_file
from .prompt_generator import generate_prompt
from .validation import validate_generated_python


# --- ANSI color helpers (no rich dependency) ---

_COLOR_SUPPORTED: bool | None = None


def _supports_color() -> bool:
    """Check if the terminal supports ANSI colors (cached)."""
    global _COLOR_SUPPORTED
    if _COLOR_SUPPORTED is None:
        _COLOR_SUPPORTED = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    return _COLOR_SUPPORTED


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

def _parse_and_analyze(args: argparse.Namespace, label: str) -> tuple:
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
    config_path = args.config or None
    smap = analyze(program, config_path=config_path)

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
    from .utils import _to_python_name
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


# --- Subcommands ---

def cmd_translate(args: argparse.Namespace) -> int:
    """Parse, analyze, and generate Python translation."""
    p = Path(args.path)
    config = args.config or None
    copy_paths = args.copybook_path
    recursive = args.recursive
    validate = args.validate

    if p.is_dir():
        base_out = Path(args.output)

        def process(src: Path, out_dir: Path) -> int:
            return _translate_single(src, out_dir, config, copy_paths, validate)

        return _batch.run_batch(p, base_out, recursive, process)

    return _translate_single(p, Path(args.output), config, copy_paths, validate)


def cmd_map(args: argparse.Namespace) -> int:
    """Parse, analyze, and export reports."""
    p = Path(args.path)
    config = args.config or None
    copy_paths = args.copybook_path
    recursive = args.recursive

    if p.is_dir():
        base_out = Path(args.output)

        def process(src: Path, out_dir: Path) -> int:
            return _map_single(src, out_dir, config, copy_paths)

        return _batch.run_batch(p, base_out, recursive, process)

    return _map_single(p, Path(args.output), config, copy_paths)


def cmd_prompt(args: argparse.Namespace) -> int:
    """Generate an LLM translation brief (stdout or file)."""
    p = Path(args.path)
    config = args.config or None
    copy_paths = args.copybook_path
    recursive = args.recursive
    output = args.output

    if p.is_dir():
        if output is None:
            print(red("Error: --output is required for directory prompt mode"), file=sys.stderr)
            return 1
        base_out = Path(output)

        def process(src: Path, out_dir: Path) -> int:
            brief_path = out_dir / f"{src.stem}_brief.md"
            return _prompt_single(src, brief_path, config, copy_paths)

        return _batch.run_batch(p, base_out, recursive, process)

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

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # translate subcommand
    tr = subparsers.add_parser(
        "translate",
        help="Translate COBOL source to Python skeleton",
    )
    tr.add_argument("path", help="Path to COBOL source file or directory")
    tr.add_argument(
        "--output", "-o", default="./translated",
        help="Output directory (default: ./translated)",
    )
    tr.add_argument(
        "--config", "-c", default=None,
        help="Path to protected.json config file",
    )
    tr.add_argument(
        "--recursive", "-r", action="store_true",
        help="Recurse into subdirectories (directory mode only)",
    )
    tr.add_argument(
        "--copybook-path", "-I", action="append", default=[],
        help="Directory to search for COPY copybooks (can be repeated)",
    )
    tr.add_argument(
        "--validate", action="store_true", default=False,
        help="Run import validation on generated Python (syntax + compile + import)",
    )

    # map subcommand
    mp = subparsers.add_parser(
        "map",
        help="Generate analysis reports (Markdown + JSON)",
    )
    mp.add_argument("path", help="Path to COBOL source file or directory")
    mp.add_argument(
        "--output", "-o", default="./report",
        help="Output directory (default: ./report)",
    )
    mp.add_argument(
        "--config", "-c", default=None,
        help="Path to protected.json config file",
    )
    mp.add_argument(
        "--recursive", "-r", action="store_true",
        help="Recurse into subdirectories (directory mode only)",
    )
    mp.add_argument(
        "--copybook-path", "-I", action="append", default=[],
        help="Directory to search for COPY copybooks (can be repeated)",
    )

    # prompt subcommand
    pr = subparsers.add_parser(
        "prompt",
        help="Generate a compact LLM translation brief",
    )
    pr.add_argument("path", help="Path to COBOL source file or directory")
    pr.add_argument(
        "--output", "-o", default=None,
        help="Output file or directory (default: stdout for single file)",
    )
    pr.add_argument(
        "--config", "-c", default=None,
        help="Path to protected.json config file",
    )
    pr.add_argument(
        "--recursive", "-r", action="store_true",
        help="Recurse into subdirectories (directory mode only)",
    )
    pr.add_argument(
        "--copybook-path", "-I", action="append", default=[],
        help="Directory to search for COPY copybooks (can be repeated)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "translate":
        return cmd_translate(args)
    elif args.command == "map":
        return cmd_map(args)
    elif args.command == "prompt":
        return cmd_prompt(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
