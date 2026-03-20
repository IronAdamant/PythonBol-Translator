"""Batch TODO triage across a COBOL project directory.

Scans translated Python output (or translates on-the-fly) and produces a
consolidated report: TODO counts by category, per-program breakdown,
suggested work streams for team assignment.

Pipeline: Directory -> translate each -> scan TODOs -> categorize -> report
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .batch import discover_cobol_files
from .mapper import generate_python
from .models import SoftwareMap
from .parser import parse_cobol_file
from .analyzer import analyze


# --- TODO categories (order matters for display) ---

_CATEGORIES: dict[str, tuple[str, ...]] = {
    "DB2 / SQL": ("SQL", "CURSOR", "FETCH", "SQLCODE", "COMMIT", "ROLLBACK", "DB-API"),
    "CICS": ("CICS", "MAP", "TRANSID", "COMMAREA", "BMS", "FLASK", "EIBTRNID"),
    "DLI / IMS": ("DLI", "IMS", "CBLTDLI", "AIBTDLI", "PCB", "SSA", "SEGMENT"),
    "File I/O": ("READ", "WRITE", "OPEN", "CLOSE", "FILE", "REWRITE", "DELETE", "START"),
    "External CALL": ("CALL", "IMPLEMENT OR IMPORT", "ENTRY"),
    "Control Flow": ("PERFORM", "GO TO", "IF", "EVALUATE", "ALTER", "THRU"),
    "String Ops": ("STRING", "UNSTRING", "INSPECT", "POINTER"),
    "Data / MOVE": ("MOVE", "CORRESPONDING", "GROUP", "REDEFINES"),
    "Arithmetic": ("COMPUTE", "ADD", "SUBTRACT", "DIVIDE", "MULTIPLY", "SIZE ERROR"),
}


@dataclass
class TodoItem:
    line_number: int
    text: str
    category: str


@dataclass
class ProgramTriage:
    program_id: str
    source_path: str
    total_lines: int
    todos: list[TodoItem] = field(default_factory=list)
    error: str | None = None


@dataclass
class ProjectTriage:
    programs: list[ProgramTriage] = field(default_factory=list)
    category_totals: dict[str, int] = field(default_factory=dict)
    total_todos: int = 0
    total_programs: int = 0
    clean_programs: int = 0


def _categorize_todo(text: str) -> str:
    upper = text.upper()
    for cat, keywords in _CATEGORIES.items():
        if any(kw in upper for kw in keywords):
            return cat
    return "Other"


def _scan_todos(python_source: str) -> list[TodoItem]:
    todos: list[TodoItem] = []
    for i, line in enumerate(python_source.splitlines(), 1):
        stripped = line.strip()
        if "TODO(high)" in stripped:
            clean = stripped.lstrip("# ").strip()
            cat = _categorize_todo(clean)
            todos.append(TodoItem(line_number=i, text=clean, category=cat))
    return todos


def triage_project(
    directory: Path,
    recursive: bool = False,
    copy_paths: list[str] | None = None,
    config_path: str | None = None,
) -> ProjectTriage:
    """Triage all COBOL files in a directory.

    Translates each file and categorizes TODO markers for team assignment.
    """
    files = discover_cobol_files(directory, recursive=recursive)
    result = ProjectTriage(total_programs=len(files))
    cat_counts: Counter[str] = Counter()

    for f in files:
        try:
            program = parse_cobol_file(f, copy_paths=copy_paths)
            smap = analyze(program, config_path=config_path)
            python_source = generate_python(smap)
            todos = _scan_todos(python_source)
            pid = program.program_id or f.stem
            pt = ProgramTriage(
                program_id=pid,
                source_path=str(f),
                total_lines=len(python_source.splitlines()),
                todos=todos,
            )
        except Exception as exc:
            pt = ProgramTriage(
                program_id=f.stem,
                source_path=str(f),
                total_lines=0,
                error=str(exc),
            )

        result.programs.append(pt)
        if not pt.todos and not pt.error:
            result.clean_programs += 1
        for todo in pt.todos:
            cat_counts[todo.category] += 1

    result.total_todos = sum(cat_counts.values())
    result.category_totals = dict(cat_counts.most_common())
    return result


def format_triage_report(triage: ProjectTriage) -> str:
    """Format a Markdown triage report for team assignment."""
    lines: list[str] = []
    lines.append("# Migration Triage Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Programs scanned:** {triage.total_programs}")
    lines.append(f"- **Clean (no TODOs):** {triage.clean_programs}")
    lines.append(f"- **Total TODO items:** {triage.total_todos}")
    lines.append("")

    if not triage.category_totals:
        lines.append("All programs translated cleanly - no items requiring attention.")
        return "\n".join(lines)

    # Work stream breakdown
    lines.append("## Work Streams")
    lines.append("")
    lines.append("Assign each category to a developer or team:")
    lines.append("")
    lines.append("| Category | Count | % of Total | Suggested Skills |")
    lines.append("|----------|------:|:----------:|------------------|")

    skill_map = {
        "DB2 / SQL": "SQL, DB-API 2.0, database migration",
        "CICS": "Web framework (Flask/FastAPI), transaction design",
        "DLI / IMS": "Hierarchical DB, IMS, API design",
        "File I/O": "Python file handling, VSAM concepts",
        "External CALL": "Cross-module integration, API contracts",
        "Control Flow": "COBOL control flow, Python refactoring",
        "String Ops": "COBOL string semantics, regex",
        "Data / MOVE": "COBOL data model, CobolDecimal/CobolString",
        "Arithmetic": "Fixed-point arithmetic, COBOL COMPUTE",
        "Other": "General COBOL knowledge",
    }

    for cat, count in triage.category_totals.items():
        pct = f"{count / triage.total_todos * 100:.0f}%" if triage.total_todos else "0%"
        skills = skill_map.get(cat, "")
        lines.append(f"| {cat} | {count} | {pct} | {skills} |")

    lines.append("")

    # Per-program breakdown (sorted by TODO count descending)
    lines.append("## Per-Program Breakdown")
    lines.append("")
    lines.append("| Program | TODOs | Top Category | Source |")
    lines.append("|---------|------:|--------------|--------|")

    sorted_progs = sorted(
        triage.programs,
        key=lambda p: len(p.todos),
        reverse=True,
    )
    for pt in sorted_progs:
        if pt.error:
            lines.append(f"| {pt.program_id} | ERROR | Parse failed | `{pt.source_path}` |")
            continue
        n = len(pt.todos)
        if n == 0:
            lines.append(f"| {pt.program_id} | 0 | Clean | `{pt.source_path}` |")
        else:
            cats = Counter(t.category for t in pt.todos)
            top_cat = cats.most_common(1)[0][0]
            lines.append(f"| {pt.program_id} | {n} | {top_cat} | `{pt.source_path}` |")

    lines.append("")

    # Detailed TODO inventory for programs with issues
    programs_with_todos = [p for p in sorted_progs if p.todos]
    if programs_with_todos:
        lines.append("## Detailed TODO Inventory")
        lines.append("")
        for pt in programs_with_todos:
            lines.append(f"### {pt.program_id} ({len(pt.todos)} items)")
            lines.append("")
            by_cat: dict[str, list[TodoItem]] = {}
            for todo in pt.todos:
                by_cat.setdefault(todo.category, []).append(todo)
            for cat, items in sorted(by_cat.items()):
                lines.append(f"**{cat}** ({len(items)})")
                lines.append("")
                for item in items:
                    lines.append(f"- Line {item.line_number}: {item.text}")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by [cobol-safe-translator](https://github.com/IronAdamant/PythonBol-Translator)*")
    return "\n".join(lines)


def format_triage_json(triage: ProjectTriage) -> str:
    """Format triage data as JSON for tooling integration."""
    data = {
        "summary": {
            "total_programs": triage.total_programs,
            "clean_programs": triage.clean_programs,
            "total_todos": triage.total_todos,
            "categories": triage.category_totals,
        },
        "programs": [
            {
                "program_id": pt.program_id,
                "source_path": pt.source_path,
                "total_lines": pt.total_lines,
                "todo_count": len(pt.todos),
                "error": pt.error,
                "todos_by_category": dict(Counter(t.category for t in pt.todos)),
            }
            for pt in triage.programs
        ],
    }
    return json.dumps(data, indent=2)
