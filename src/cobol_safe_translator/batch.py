"""Batch/directory processing for the COBOL-to-Python translator.

Discovers COBOL files in a directory and runs a processing function on each,
collecting errors and continuing on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

# Extensions treated as COBOL source files (.cpy copybooks are excluded)
COBOL_EXTENSIONS = frozenset({".cob", ".cbl", ".cobol"})


def discover_cobol_files(directory: Path, recursive: bool = False) -> list[Path]:
    """Return sorted list of COBOL source files in *directory*.

    Args:
        directory: Directory to search.
        recursive: If True, descend into subdirectories.

    Returns:
        Sorted list of Path objects with COBOL extensions.
    """
    if not directory.is_dir():
        return []
    if recursive:
        candidates = directory.rglob("*")
    else:
        candidates = directory.glob("*")

    files = [
        p for p in candidates
        if p.is_file() and p.suffix.lower() in COBOL_EXTENSIONS
    ]
    return sorted(files)


def run_batch(
    source_dir: Path,
    base_output: Path,
    recursive: bool,
    process_fn: Callable[[Path, Path], int],
    print_fn: Callable[..., None] | None = None,
) -> int:
    """Process all COBOL files in *source_dir*.

    Each source file is processed into its own subdirectory under *base_output*:
        base_output / <stem> /

    Errors are collected and reported at the end; processing continues on failure.

    Args:
        source_dir:  Directory containing COBOL source files.
        base_output: Root output directory.
        recursive:   Whether to search subdirectories.
        process_fn:  Callable(src, out_dir) -> int (0 = success).
        print_fn:    Output function (defaults to print). Called with (msg,) for
                     normal output and (msg, file=stderr) for errors.

    Returns:
        0 if all files succeeded, 1 if any failed or no files found.
    """
    if print_fn is None:
        print_fn = print

    files = discover_cobol_files(source_dir, recursive=recursive)

    if not files:
        print_fn(
            f"Error: no COBOL files found in {source_dir}",
            file=sys.stderr,
        )
        return 1

    print_fn(f"Batch: {len(files)} file(s) in {source_dir}")

    errors: list[tuple[Path, int]] = []
    for src in files:
        out_dir = base_output / src.stem
        try:
            rc = process_fn(src, out_dir)
        except Exception as exc:  # noqa: BLE001
            print_fn(f"  ERROR: {src}: {exc}", file=sys.stderr)
            rc = 1
        if rc != 0:
            errors.append((src, rc))

    if errors:
        print_fn(f"\nBatch complete: {len(files) - len(errors)}/{len(files)} succeeded.")
        for path, code in errors:
            print_fn(f"  FAILED (exit {code}): {path}", file=sys.stderr)
        return 1

    print_fn(f"\nBatch complete: {len(files)}/{len(files)} succeeded.")
    return 0
