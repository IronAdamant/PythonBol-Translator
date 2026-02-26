"""Analyzes a parsed CobolProgram for sensitivity flags, dependencies, and statistics.

Pipeline position: Parser -> AST -> **Analyzer** -> SoftwareMap -> Exporter
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .models import (
    CobolProgram,
    DataItem,
    Dependency,
    ProgramStats,
    SensitivityFlag,
    SensitivityLevel,
    SoftwareMap,
)
from .parser import count_raw_lines

# Default sensitive patterns (used when no config file is provided)
# Ordered by severity: HIGH first, then MEDIUM, then LOW.
DEFAULT_PATTERNS: list[dict[str, str]] = [
    {"pattern": r"(^|-)SSN(-|$)", "level": "high", "reason": "Social Security Number"},
    {"pattern": r"(^|-)SOCIAL-SEC", "level": "high", "reason": "Social Security Number"},
    {"pattern": r"(^|-)TAX-ID(-|$)", "level": "high", "reason": "Tax Identifier"},
    {"pattern": r"(^|-)DOB(-|$)", "level": "high", "reason": "Date of Birth"},
    {"pattern": r"(^|-)BIRTH(-|$)", "level": "high", "reason": "Date of Birth"},
    {"pattern": r"PASSWORD", "level": "high", "reason": "Password/credential"},
    {"pattern": r"(^|-)PIN(-|$)", "level": "high", "reason": "PIN code"},
    {"pattern": r"ACCOUNT", "level": "medium", "reason": "Account number"},
    {"pattern": r"BALANCE", "level": "medium", "reason": "Financial balance"},
    {"pattern": r"SALARY", "level": "medium", "reason": "Salary data"},
    {"pattern": r"(^|-)WAGE(-|$)", "level": "medium", "reason": "Wage data"},
    {"pattern": r"CREDIT", "level": "medium", "reason": "Credit information"},
    {"pattern": r"PAYMENT", "level": "medium", "reason": "Payment data"},
    {"pattern": r"^CUST-", "level": "low", "reason": "Customer-prefixed field"},
    {"pattern": r"^EMP-", "level": "low", "reason": "Employee-prefixed field"},
    {"pattern": r"ADDR", "level": "low", "reason": "Address data"},
    {"pattern": r"PHONE", "level": "low", "reason": "Phone number"},
    {"pattern": r"EMAIL", "level": "low", "reason": "Email address"},
]

DEFAULT_EXCLUDES: list[str] = ["WS-EOF", "WS-ERROR", "FILLER"]


def load_config(config_path: str | Path | None) -> tuple[list[dict[str, str]], list[str]]:
    """Load sensitivity config from a JSON file, or use defaults."""
    if config_path is None:
        return DEFAULT_PATTERNS, DEFAULT_EXCLUDES

    p = Path(config_path)
    if not p.exists():
        print(f"Warning: config file not found: {p} — using defaults", file=sys.stderr)
        return DEFAULT_PATTERNS, DEFAULT_EXCLUDES

    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not load config {p}: {e} — using defaults", file=sys.stderr)
        return DEFAULT_PATTERNS, DEFAULT_EXCLUDES

    patterns = data.get("sensitive_patterns", DEFAULT_PATTERNS)
    excludes = data.get("exclude_names", DEFAULT_EXCLUDES)
    # Validate pattern entries have required keys
    required_keys = {"pattern", "level", "reason"}
    valid_levels = {"high", "medium", "low"}
    validated: list[dict[str, str]] = []
    for i, pat in enumerate(patterns):
        missing = required_keys - set(pat.keys())
        if missing:
            print(f"Warning: pattern #{i} missing keys {missing} — skipping", file=sys.stderr)
            continue
        if pat["level"] not in valid_levels:
            print(f"Warning: pattern #{i} has invalid level '{pat['level']}' — skipping", file=sys.stderr)
            continue
        if not isinstance(pat["pattern"], str):
            print(f"Warning: pattern #{i} has non-string value — skipping", file=sys.stderr)
            continue
        try:
            re.compile(pat["pattern"], re.IGNORECASE)
        except re.error as e:
            print(f"Warning: pattern #{i} has invalid regex '{pat['pattern']}': {e} — skipping", file=sys.stderr)
            continue
        validated.append(pat)
    return validated, excludes


def _collect_all_data_names(items: list[DataItem]) -> list[str]:
    """Recursively collect all data item names."""
    names: list[str] = []
    for item in items:
        names.append(item.name)
        if item.children:
            names.extend(_collect_all_data_names(item.children))
    return names


def detect_sensitivities(
    program: CobolProgram,
    patterns: list[dict[str, str]],
    excludes: list[str],
) -> list[SensitivityFlag]:
    """Flag data items whose names match sensitive patterns."""
    all_names = (
        _collect_all_data_names(program.file_section)
        + _collect_all_data_names(program.working_storage)
        + _collect_all_data_names(program.linkage_section)
    )

    exclude_set = {e.upper() for e in excludes}
    flags: list[SensitivityFlag] = []

    for name in all_names:
        upper_name = name.upper()
        if upper_name in exclude_set:
            continue

        for pat in patterns:
            if re.search(pat["pattern"], upper_name, re.IGNORECASE):
                flags.append(SensitivityFlag(
                    data_name=name,
                    pattern_matched=pat["pattern"],
                    level=SensitivityLevel(pat["level"]),
                    reason=pat["reason"],
                ))
                break  # One flag per name, highest priority pattern wins

    return flags


def extract_dependencies(program: CobolProgram) -> list[Dependency]:
    """Find CALL statements and extract external program dependencies."""
    deps: list[Dependency] = []
    for para in program.paragraphs:
        for stmt in para.statements:
            if stmt.verb == "CALL":
                # CALL "PROGRAM-NAME" or CALL identifier
                target = _extract_call_target(stmt.operands)
                if target:
                    deps.append(Dependency(
                        call_target=target,
                        source_paragraph=para.name,
                    ))
    return deps


def _extract_call_target(operands: list[str]) -> str:
    """Extract the target program name from CALL operands."""
    if not operands or operands[0] is None:
        return ""
    target = operands[0].strip('"').strip("'")
    return target


def compute_stats(program: CobolProgram) -> ProgramStats:
    """Compute program statistics."""
    raw_text = "\n".join(program.raw_lines)
    total, code, comments, blanks = count_raw_lines(raw_text)

    data_count = (
        len(_collect_all_data_names(program.file_section))
        + len(_collect_all_data_names(program.working_storage))
        + len(_collect_all_data_names(program.linkage_section))
    )

    stmt_count = sum(len(p.statements) for p in program.paragraphs)

    return ProgramStats(
        total_lines=total,
        code_lines=code,
        comment_lines=comments,
        blank_lines=blanks,
        paragraph_count=len(program.paragraphs),
        data_item_count=data_count,
        statement_count=stmt_count,
    )


def analyze(
    program: CobolProgram,
    config_path: str | Path | None = None,
) -> SoftwareMap:
    """Run full analysis on a parsed COBOL program."""
    patterns, excludes = load_config(config_path)
    sensitivities = detect_sensitivities(program, patterns, excludes)
    dependencies = extract_dependencies(program)
    stats = compute_stats(program)

    warnings: list[str] = []

    # Warn about unsupported constructs
    for para in program.paragraphs:
        for stmt in para.statements:
            if stmt.verb == "GO":
                warnings.append(
                    f"GO TO in {para.name}: requires manual review"
                )
            elif stmt.verb == "COPY":
                warnings.append(
                    f"COPY statement in {para.name}: copybook expansion not supported in MVP"
                )

    if sensitivities:
        high_count = sum(1 for s in sensitivities if s.level == SensitivityLevel.HIGH)
        if high_count:
            warnings.append(
                f"{high_count} HIGH-sensitivity field(s) detected — review before deployment"
            )

    return SoftwareMap(
        program=program,
        sensitivities=sensitivities,
        dependencies=dependencies,
        stats=stats,
        warnings=warnings,
    )
