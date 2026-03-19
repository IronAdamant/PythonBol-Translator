#!/usr/bin/env python3
"""Extract COBOL programs from GnuCOBOL Autotest (.at) files.

Parses AT_SETUP/AT_DATA/AT_CLEANUP blocks and writes each embedded
COBOL file into a structured output directory grouped by test name.

Usage:
    python tools/extract_gnucobol_tests.py <source_dir> <output_dir>

Source dir should contain .at files (e.g. gnucobol/tests/testsuite.src/).
"""

import argparse
import re
import sys
from enum import Enum, auto
from pathlib import Path

COBOL_EXTENSIONS = frozenset({".cob", ".COB", ".cbl", ".cpy", ".CPY", ".inc", ".copy"})

AUTOTEST_ESCAPES = {
    "@%:@": "#",
    "@<:@": "[",
    "@:>@": "]",
}


class State(Enum):
    IDLE = auto()
    IN_TEST = auto()
    IN_DATA = auto()
    AWAIT_BRACKET = auto()  # split-line: AT_DATA([file],\n[content


def slugify(name: str) -> str:
    """Convert a test name to a filesystem-safe directory name."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def unescape(line: str) -> str:
    """Replace Autotest escape sequences with their literal characters."""
    for esc, repl in AUTOTEST_ESCAPES.items():
        line = line.replace(esc, repl)
    return line


def extract_at_files(at_path: Path) -> list[dict]:
    """Parse a single .at file and return extracted file records.

    Returns a list of dicts: {test_name, filename, content}
    """
    results = []
    state = State.IDLE
    test_name = ""
    data_filename = ""
    data_lines: list[str] = []
    test_index = 0

    for line in at_path.read_text(errors="replace").splitlines(keepends=True):
        stripped = line.rstrip("\n\r")

        if state == State.IDLE:
            m = re.match(r"AT_SETUP\(\[(.+?)\]\)", stripped)
            if m:
                test_index += 1
                test_name = m.group(1)
                state = State.IN_TEST

        elif state == State.IN_TEST:
            if stripped.startswith("AT_CLEANUP"):
                state = State.IDLE
                continue
            # Match AT_DATA with content bracket on same line
            m = re.match(r"AT_DATA\(\[(.+?)\],\s*\[", stripped)
            if m:
                data_filename = m.group(1)
                data_lines = []
                rest = stripped[m.end():]
                if rest == "])" or rest == "]])":
                    # Single-line empty block: AT_DATA([file], [])
                    ext = Path(data_filename).suffix
                    if ext in COBOL_EXTENSIONS:
                        results.append({
                            "test_name": test_name,
                            "test_index": test_index,
                            "filename": data_filename,
                            "content": "",
                        })
                elif rest.endswith("])") or rest.endswith("]])"):
                    # Single-line block with inline content
                    trim = 3 if rest.endswith("]])") else 2
                    ext = Path(data_filename).suffix
                    if ext in COBOL_EXTENSIONS:
                        content = unescape(rest[:-trim])
                        results.append({
                            "test_name": test_name,
                            "test_index": test_index,
                            "filename": data_filename,
                            "content": content + "\n" if content else "",
                        })
                else:
                    # Normal multiline — capture any inline content after [
                    if rest:
                        data_lines.append(rest + "\n")
                    state = State.IN_DATA
                continue
            # Match split-line AT_DATA: AT_DATA([file],\n on next line
            m = re.match(r"AT_DATA\(\[(.+?)\],\s*$", stripped)
            if m:
                data_filename = m.group(1)
                data_lines = []
                state = State.AWAIT_BRACKET

        elif state == State.AWAIT_BRACKET:
            # Expect opening bracket on this line
            if stripped.startswith("["):
                rest = stripped[1:]
                if rest == "])" or rest == "]])":
                    # Empty block
                    ext = Path(data_filename).suffix
                    if ext in COBOL_EXTENSIONS:
                        results.append({
                            "test_name": test_name,
                            "test_index": test_index,
                            "filename": data_filename,
                            "content": "",
                        })
                    state = State.IN_TEST
                else:
                    if rest:
                        data_lines.append(rest + "\n")
                    state = State.IN_DATA
            else:
                # Unexpected — abort this block
                state = State.IN_TEST

        elif state == State.IN_DATA:
            if stripped in ("])", "]])"):
                ext = Path(data_filename).suffix
                if ext in COBOL_EXTENSIONS:
                    content = "".join(unescape(l) for l in data_lines)
                    results.append({
                        "test_name": test_name,
                        "test_index": test_index,
                        "filename": data_filename,
                        "content": content,
                    })
                state = State.IN_TEST
            else:
                data_lines.append(line)

    return results


def write_extracted(records: list[dict], at_stem: str, output_dir: Path) -> int:
    """Write extracted records to output_dir/at_stem/NNN_test_name/filename."""
    written = 0
    for rec in records:
        test_slug = f"{rec['test_index']:03d}_{slugify(rec['test_name'])}"
        dest_dir = output_dir / at_stem / test_slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / rec["filename"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rec["content"])
        written += 1
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extract COBOL programs from GnuCOBOL Autotest .at files."
    )
    parser.add_argument("source_dir", type=Path, help="Directory containing .at files")
    parser.add_argument("output_dir", type=Path, help="Output directory for extracted files")
    args = parser.parse_args(argv)

    if not args.source_dir.is_dir():
        print(f"Error: {args.source_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    at_files = sorted(args.source_dir.rglob("*.at"))
    if not at_files:
        print(f"No .at files found in {args.source_dir}", file=sys.stderr)
        sys.exit(1)

    total_files = 0
    total_tests = 0
    for at_path in at_files:
        records = extract_at_files(at_path)
        if not records:
            continue
        test_names = {r["test_name"] for r in records}
        count = write_extracted(records, at_path.stem, args.output_dir)
        total_files += count
        total_tests += len(test_names)
        print(f"  {at_path.name}: {len(test_names)} tests, {count} COBOL files")

    print(f"\nTotal: {total_files} COBOL files from {total_tests} tests across {len(at_files)} .at files")
    print(f"Output: {args.output_dir}")


if __name__ == "__main__":
    main()
