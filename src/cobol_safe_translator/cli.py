"""CLI entry point for the COBOL-to-Python safe translator.

Usage:
    cobol2py translate <path> --output ./translated
    cobol2py map <path> --output ./report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze
from .exporters import export_json, export_markdown
from .mapper import generate_python
from .parser import parse_cobol_file


# --- ANSI color helpers (no rich dependency) ---

def _supports_color() -> bool:
    """Check if the terminal supports ANSI colors."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


def _color_enabled() -> bool:
    """Check color support lazily (not at import time)."""
    return _supports_color()


def _c(code: str, text: str) -> str:
    if not _color_enabled():
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


def cyan(text: str) -> str:
    return _c("36", text)


# --- Shared helpers ---

def _parse_and_analyze(args: argparse.Namespace, label: str) -> tuple[int, object, object] | tuple[int, None, None]:
    """Parse and analyze a COBOL source file. Returns (exit_code, program, smap)."""
    source_path = Path(args.path)

    if not source_path.exists() or not source_path.is_file():
        print(red(f"Error: file not found: {source_path}"), file=sys.stderr)
        return 1, None, None

    print(bold(f"{label}: {source_path}"))

    # Parse
    program = parse_cobol_file(source_path)
    print(green(f"  Parsed: {program.program_id} ({len(program.paragraphs)} paragraphs)"))

    # Analyze
    config_path = args.config if args.config else None
    smap = analyze(program, config_path=config_path)

    if smap.sensitivities:
        high = sum(1 for s in smap.sensitivities if s.level.value == "high")
        med = sum(1 for s in smap.sensitivities if s.level.value == "medium")
        low = sum(1 for s in smap.sensitivities if s.level.value == "low")
        print(yellow(f"  Sensitivities: {high} high, {med} medium, {low} low"))

    for w in smap.warnings:
        print(yellow(f"  Warning: {w}"))

    return 0, program, smap


# --- Subcommands ---

def cmd_translate(args: argparse.Namespace) -> int:
    """Parse, analyze, and generate Python translation."""
    output_dir = Path(args.output)

    rc, program, smap = _parse_and_analyze(args, "Translating")
    if rc != 0 or program is None or smap is None:
        return rc

    # Generate Python
    python_source = generate_python(smap)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_name = _to_python_filename(program.program_id)
        out_path = output_dir / out_name
        out_path.write_text(python_source, encoding="utf-8")
    except OSError as e:
        print(red(f"Error: could not write output: {e}"), file=sys.stderr)
        return 1
    print(green(f"  Output: {out_path}"))

    print(bold(green("Done.")))
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """Parse, analyze, and export reports."""
    output_dir = Path(args.output)

    rc, program, smap = _parse_and_analyze(args, "Mapping")
    if rc != 0 or program is None or smap is None:
        return rc

    # Export reports
    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        md_report = export_markdown(smap)
        md_path = output_dir / "software-map.md"
        md_path.write_text(md_report, encoding="utf-8")
        print(green(f"  Markdown: {md_path}"))

        json_report = export_json(smap)
        json_path = output_dir / "software-map.json"
        json_path.write_text(json_report, encoding="utf-8")
        print(green(f"  JSON: {json_path}"))
    except OSError as e:
        print(red(f"Error: could not write output: {e}"), file=sys.stderr)
        return 1

    print(bold(green("Done.")))
    return 0


def _to_python_filename(program_id: str) -> str:
    """Convert COBOL program ID to a safe Python filename."""
    import re as _re
    name = program_id.lower().replace("-", "_")
    name = _re.sub(r"[^\w]", "_", name)
    return (name or "unnamed") + ".py"


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
    tr.add_argument("path", help="Path to COBOL source file")
    tr.add_argument(
        "--output", "-o", default="./translated",
        help="Output directory (default: ./translated)",
    )
    tr.add_argument(
        "--config", "-c", default=None,
        help="Path to protected.json config file",
    )

    # map subcommand
    mp = subparsers.add_parser(
        "map",
        help="Generate analysis reports (Markdown + JSON)",
    )
    mp.add_argument("path", help="Path to COBOL source file")
    mp.add_argument(
        "--output", "-o", default="./report",
        help="Output directory (default: ./report)",
    )
    mp.add_argument(
        "--config", "-c", default=None,
        help="Path to protected.json config file",
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
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
