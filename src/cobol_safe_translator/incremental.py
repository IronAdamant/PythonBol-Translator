"""Incremental (diff-based) re-translation for COBOL programs.

Compares a new parse of a COBOL source against a previous translation's
metadata to identify which paragraphs, data items, or sections changed.
Only regenerates the changed portions, preserving any manual edits to
unchanged paragraphs in the existing Python output.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from .models import CobolProgram, DataItem, Paragraph
from .analyzer import analyze
from .mapper import generate_python, PythonMapper
from .parser import parse_cobol_file
from .utils import _to_method_name


def _hash_paragraph(para: Paragraph) -> str:
    """Compute a content hash for a paragraph's statements."""
    content = "|".join(
        f"{s.verb}:{s.raw_text}" for s in para.statements
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _hash_data_items(items: list[DataItem]) -> str:
    """Compute a content hash for a list of data items."""
    def _item_str(item: DataItem) -> str:
        parts = [str(item.level), item.name]
        if item.pic:
            parts.append(item.pic.raw)
        if item.value:
            parts.append(item.value)
        if item.occurs:
            parts.append(str(item.occurs))
        if item.usage:
            parts.append(item.usage)
        for child in item.children:
            parts.append(_item_str(child))
        return "|".join(parts)

    content = "||".join(_item_str(i) for i in items)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_fingerprint(program: CobolProgram) -> dict:
    """Compute a fingerprint of a COBOL program for change detection.

    Returns a dict mapping section/paragraph names to content hashes.
    """
    fp = {
        "_data_division": _hash_data_items(program.all_data_items),
        "_file_controls": hashlib.sha256(
            str([(fc.select_name, fc.assign_to) for fc in program.file_controls]).encode()
        ).hexdigest()[:16],
        "_program_id": program.program_id or "",
    }

    for para in program.paragraphs:
        fp[f"para:{para.name}"] = _hash_paragraph(para)

    return fp


def save_fingerprint(fingerprint: dict, path: Path) -> None:
    """Save a fingerprint to a JSON file alongside the translation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")


def load_fingerprint(path: Path) -> dict | None:
    """Load a previously saved fingerprint. Returns None if not found."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def diff_programs(old_fp: dict, new_fp: dict) -> dict:
    """Compare two fingerprints and return a change summary.

    Returns:
        {
            "data_changed": bool,
            "file_controls_changed": bool,
            "paragraphs_added": [name, ...],
            "paragraphs_removed": [name, ...],
            "paragraphs_modified": [name, ...],
            "paragraphs_unchanged": [name, ...],
            "full_retranslation_needed": bool,
        }
    """
    result = {
        "data_changed": old_fp.get("_data_division") != new_fp.get("_data_division"),
        "file_controls_changed": old_fp.get("_file_controls") != new_fp.get("_file_controls"),
        "paragraphs_added": [],
        "paragraphs_removed": [],
        "paragraphs_modified": [],
        "paragraphs_unchanged": [],
    }

    old_paras = {k: v for k, v in old_fp.items() if k.startswith("para:")}
    new_paras = {k: v for k, v in new_fp.items() if k.startswith("para:")}

    for name, hash_val in new_paras.items():
        para_name = name[5:]  # strip "para:" prefix
        if name not in old_paras:
            result["paragraphs_added"].append(para_name)
        elif old_paras[name] != hash_val:
            result["paragraphs_modified"].append(para_name)
        else:
            result["paragraphs_unchanged"].append(para_name)

    for name in old_paras:
        if name not in new_paras:
            result["paragraphs_removed"].append(name[5:])

    # Full retranslation needed if data division or file controls changed
    # (since these affect the class structure, not just methods)
    result["full_retranslation_needed"] = (
        result["data_changed"]
        or result["file_controls_changed"]
        or bool(result["paragraphs_added"])
        or bool(result["paragraphs_removed"])
    )

    return result


def _patch_method(existing: str, method_name: str, new_method: str) -> tuple[str, bool]:
    """Replace a single method in the existing Python source.

    Tries AST-based replacement first (robust to formatting changes),
    falls back to regex if the source doesn't parse.

    Returns (patched_source, success).
    """
    result = _patch_method_ast(existing, method_name, new_method)
    if result is not None:
        return result, True
    # Fallback: regex-based patching
    return _patch_method_regex(existing, method_name, new_method)


def _patch_method_ast(
    existing: str, method_name: str, new_method: str,
) -> str | None:
    """Replace a method via AST node replacement. Returns None on failure."""
    try:
        tree = ast.parse(existing)
    except SyntaxError:
        return None

    # Find the class containing the target method
    target_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == method_name:
                        target_class = node
                        break
            if target_class:
                break

    if target_class is None:
        return None

    # Find target method's line range
    target_idx = None
    for i, item in enumerate(target_class.body):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == method_name:
                target_idx = i
                break

    if target_idx is None:
        return None

    # Use line numbers to do text replacement (preserves formatting elsewhere)
    target_node = target_class.body[target_idx]
    start_line = target_node.lineno  # 1-based
    if target_idx + 1 < len(target_class.body):
        end_line = target_class.body[target_idx + 1].lineno
    else:
        end_line = None

    lines = existing.split('\n')
    # Handle decorator lines (they come before the def)
    actual_start = start_line
    for dec in getattr(target_node, 'decorator_list', []):
        actual_start = min(actual_start, dec.lineno)

    if end_line is not None:
        # Replace lines from start to just before next item
        before = lines[:actual_start - 1]
        after = lines[end_line - 1:]
        new_lines = new_method.rstrip('\n').split('\n')
        result_lines = before + new_lines + [''] + after
    else:
        # Last method in class — replace to end of class
        before = lines[:actual_start - 1]
        new_lines = new_method.rstrip('\n').split('\n')
        # Find where the class ends (next non-indented line or EOF)
        class_end = len(lines)
        for k in range(actual_start, len(lines)):
            stripped = lines[k]
            if stripped and not stripped.startswith(' ') and not stripped.startswith('\t'):
                class_end = k
                break
        after = lines[class_end:]
        result_lines = before + new_lines + [''] + after

    return '\n'.join(result_lines)


def _patch_method_regex(
    existing: str, method_name: str, new_method: str,
) -> tuple[str, bool]:
    """Regex-based method replacement. Fallback for unparseable sources."""
    pattern = re.compile(
        rf'((?:[ \t]*@\w+.*\n)*'
        rf'    def {re.escape(method_name)}\(self[^)]*\)[^:]*:.*?)'
        rf'(?=\n    def |\n(?:[ \t]*@\w+.*\n)*    def |\nclass |\nif __name__|\Z)',
        re.DOTALL,
    )
    match = pattern.search(existing)
    if match:
        return existing[:match.start()] + new_method + existing[match.end():], True
    return existing, False


def incremental_translate(
    source_path: Path,
    output_path: Path,
    copy_paths: list[str] | None = None,
    config_path: str | None = None,
) -> tuple[str, dict]:
    """Perform incremental translation of a COBOL file.

    If a previous fingerprint exists and only paragraph bodies changed,
    patches only the affected methods in the existing Python output.
    Otherwise performs a full retranslation.

    Returns (python_source, change_summary).
    """
    # Parse the new version
    program = parse_cobol_file(source_path, copy_paths=copy_paths)
    smap = analyze(program, config_path=config_path)
    new_fp = compute_fingerprint(program)

    # Check for previous fingerprint
    fp_path = output_path.with_suffix(".fingerprint.json")
    old_fp = load_fingerprint(fp_path)

    if old_fp is None or not output_path.exists():
        # No previous translation -- full generation
        source = generate_python(smap)
        save_fingerprint(new_fp, fp_path)
        return source, {"full_retranslation_needed": True, "reason": "no previous translation"}

    # Compare fingerprints
    diff = diff_programs(old_fp, new_fp)

    if diff["full_retranslation_needed"]:
        # Structure changed -- full retranslation
        source = generate_python(smap)
        save_fingerprint(new_fp, fp_path)
        diff["reason"] = "structural change"
        return source, diff

    if not diff["paragraphs_modified"]:
        # Nothing changed
        source = output_path.read_text(encoding="utf-8")
        return source, {"full_retranslation_needed": False, "reason": "no changes"}

    # Only paragraph bodies changed -- patch the existing output
    existing = output_path.read_text(encoding="utf-8")
    mapper = PythonMapper(smap)

    patched = existing
    patch_failures: list[str] = []
    for para_name in diff["paragraphs_modified"]:
        # Find the paragraph in the new program
        para = next(
            (p for p in program.paragraphs if p.name == para_name), None
        )
        if para is None:
            continue

        method_name = _to_method_name(para_name)

        # Generate the new method body
        new_method = mapper._paragraph_method(para)

        # Find and replace the old method in the existing source
        patched, ok = _patch_method(patched, method_name, new_method)
        if not ok:
            patch_failures.append(para_name)

    # If any patches failed, fall back to full retranslation
    if patch_failures:
        source = generate_python(smap)
        save_fingerprint(new_fp, fp_path)
        diff["reason"] = f"patch failed for {', '.join(patch_failures)}; full retranslation"
        diff["full_retranslation_needed"] = True
        return source, diff

    save_fingerprint(new_fp, fp_path)
    diff["reason"] = f"patched {len(diff['paragraphs_modified'])} paragraphs"
    return patched, diff
