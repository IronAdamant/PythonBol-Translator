"""Export analysis results as Markdown and JSON reports.

Pipeline position: Analyzer -> SoftwareMap -> **Exporter** -> Reports (MD / JSON)
"""

from __future__ import annotations

import json
from datetime import datetime

from .models import (
    DataItem,
    SensitivityFlag,
    SensitivityLevel,
    SoftwareMap,
)


class MarkdownExporter:
    """Generates a software-map.md report from a SoftwareMap."""

    def __init__(self, software_map: SoftwareMap) -> None:
        self.smap = software_map
        self.program = software_map.program

    @staticmethod
    def _esc(text: str) -> str:
        """Escape pipe characters for Markdown table cells."""
        return text.replace("|", "\\|")

    def export(self) -> str:
        """Generate the full Markdown report."""
        sections: list[str] = []
        sections.append(self._header())
        sections.append(self._overview())
        sections.append(self._statistics())
        sections.append(self._data_division_summary())
        sections.append(self._procedure_summary())
        sections.append(self._sensitivity_report())
        sections.append(self._dependency_graph())
        sections.append(self._warnings())
        sections.append(self._recommendations())
        sections.append(self._footer())
        return "\n".join(sections)

    def _header(self) -> str:
        return (
            f"# Software Map: {self.program.program_id}\n\n"
            f"**Source:** `{self.program.source_path}`  \n"
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
            f"**Author:** {self.program.author or 'Unknown'}\n"
        )

    def _overview(self) -> str:
        lines = [
            "## Overview\n",
            f"COBOL program `{self.program.program_id}` analysis report.",
            f"This document provides a structural breakdown, sensitivity analysis,",
            f"and dependency mapping for modernization planning.\n",
        ]
        return "\n".join(lines)

    def _statistics(self) -> str:
        s = self.smap.stats
        lines = [
            "## Statistics\n",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total lines | {s.total_lines} |",
            f"| Code lines | {s.code_lines} |",
            f"| Comment lines | {s.comment_lines} |",
            f"| Blank lines | {s.blank_lines} |",
            f"| Paragraphs | {s.paragraph_count} |",
            f"| Data items | {s.data_item_count} |",
            f"| Statements | {s.statement_count} |",
            "",
        ]
        return "\n".join(lines)

    def _data_division_summary(self) -> str:
        lines = ["## Data Division\n"]

        if self.program.file_controls:
            lines.append("### File Controls\n")
            for fc in self.program.file_controls:
                lines.append(f"- `{fc.select_name}` -> `{fc.assign_to}`")
            lines.append("")

        if self.program.file_section:
            lines.append("### File Section\n")
            for item in self.program.file_section:
                lines.extend(self._format_data_tree(item, 0))
            lines.append("")

        if self.program.working_storage:
            lines.append("### Working-Storage\n")
            for item in self.program.working_storage:
                lines.extend(self._format_data_tree(item, 0))
            lines.append("")

        if self.program.linkage_section:
            lines.append("### Linkage Section\n")
            for item in self.program.linkage_section:
                lines.extend(self._format_data_tree(item, 0))
            lines.append("")

        return "\n".join(lines)

    def _format_data_tree(self, item: DataItem, depth: int) -> list[str]:
        """Format a data item tree as indented list."""
        indent = "  " * depth
        pic_str = f" `{item.pic.raw}`" if item.pic else ""
        val_str = f" = `{item.value}`" if item.value else ""
        line = f"{indent}- **{item.level:02d}** `{item.name}`{pic_str}{val_str}"
        lines = [line]
        for child in item.children:
            lines.extend(self._format_data_tree(child, depth + 1))
        return lines

    def _procedure_summary(self) -> str:
        lines = ["## Procedure Division\n"]
        lines.append("### Paragraphs\n")
        for para in self.program.paragraphs:
            verb_counts: dict[str, int] = {}
            for stmt in para.statements:
                verb_counts[stmt.verb] = verb_counts.get(stmt.verb, 0) + 1
            verbs = ", ".join(f"{v}({c})" for v, c in sorted(verb_counts.items()))
            lines.append(f"- **{para.name}** — {len(para.statements)} statements: {verbs}")
        lines.append("")
        return "\n".join(lines)

    def _sensitivity_report(self) -> str:
        lines = ["## Sensitivity Report\n"]

        if not self.smap.sensitivities:
            lines.append("No sensitive data fields detected.\n")
            return "\n".join(lines)

        # Group by level
        by_level: dict[SensitivityLevel, list[SensitivityFlag]] = {}
        for flag in self.smap.sensitivities:
            by_level.setdefault(flag.level, []).append(flag)

        for level in (SensitivityLevel.HIGH, SensitivityLevel.MEDIUM, SensitivityLevel.LOW):
            flags = by_level.get(level, [])
            if not flags:
                continue

            badge = {"high": "!!!", "medium": "!!", "low": "!"}[level.value]
            lines.append(f"### {level.value.upper()} Sensitivity ({badge})\n")
            lines.append("| Data Name | Pattern | Reason |")
            lines.append("|-----------|---------|--------|")
            for f in flags:
                lines.append(f"| `{self._esc(f.data_name)}` | `{self._esc(f.pattern_matched)}` | {self._esc(f.reason)} |")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _mermaid_id(name: str) -> str:
        """Sanitize a name for use as a Mermaid node ID.

        Uses char-code encoding for non-alphanumeric characters to avoid
        collisions (e.g., PROG-A vs PROG.A would otherwise both become PROG_A).
        """
        result = []
        for c in name:
            if c.isalnum() or c == "_":
                result.append(c)
            else:
                result.append(f"_{ord(c):x}_")
        return "".join(result)

    def _dependency_graph(self) -> str:
        lines = ["## Dependency Graph\n"]

        if not self.smap.dependencies:
            lines.append("No external dependencies (CALL statements) detected.\n")
            return "\n".join(lines)

        prog_id = self._mermaid_id(self.program.program_id)
        prog_label = self.program.program_id.replace('"', '#quot;')

        lines.append("```mermaid")
        lines.append("graph TD")
        lines.append(f"    {prog_id}[\"{prog_label}\"]")

        seen: set[str] = set()
        for dep in self.smap.dependencies:
            dep_id = self._mermaid_id(dep.call_target)
            if dep_id not in seen:
                dep_label = dep.call_target.replace('"', '#quot;')
                lines.append(f"    {prog_id} --> {dep_id}[\"{dep_label}\"]")
                seen.add(dep_id)

        lines.append("```\n")

        lines.append("### Call Details\n")
        lines.append("| Source Paragraph | Target Program |")
        lines.append("|-----------------|----------------|")
        for dep in self.smap.dependencies:
            lines.append(f"| `{self._esc(dep.source_paragraph)}` | `{self._esc(dep.call_target)}` |")
        lines.append("")

        return "\n".join(lines)

    def _warnings(self) -> str:
        lines = ["## Warnings\n"]
        if not self.smap.warnings:
            lines.append("No warnings.\n")
            return "\n".join(lines)

        for w in self.smap.warnings:
            lines.append(f"- {w}")
        lines.append("")
        return "\n".join(lines)

    def _recommendations(self) -> str:
        lines = ["## Recommendations\n"]
        recs: list[str] = []

        if any(s.level == SensitivityLevel.HIGH for s in self.smap.sensitivities):
            recs.append("Review all HIGH-sensitivity fields before exposing translated code to any data")

        if self.smap.dependencies:
            recs.append("Identify and translate all called subprograms before integration testing")

        has_goto = any(
            s.verb == "GO" for p in self.program.paragraphs for s in p.statements
        )
        if has_goto:
            recs.append("Restructure GO TO statements — these cannot be automatically translated")

        has_write = any(
            s.verb == "WRITE" for p in self.program.paragraphs for s in p.statements
        )
        if has_write:
            recs.append("File write operations require manual implementation (safety restriction)")

        if not recs:
            recs.append("No critical recommendations — standard review process applies")

        for i, r in enumerate(recs, 1):
            lines.append(f"{i}. {r}")
        lines.append("")
        return "\n".join(lines)

    def _footer(self) -> str:
        return (
            "---\n\n"
            "*Generated by cobol-safe-translator. "
            "This report is for analysis purposes only — "
            "always verify against original COBOL source.*\n"
        )


class JsonExporter:
    """Generates a software-map.json for programmatic consumption (e.g., by LLMs)."""

    def __init__(self, software_map: SoftwareMap) -> None:
        self.smap = software_map

    def export(self) -> str:
        """Generate JSON string."""
        data = {
            "program_id": self.smap.program.program_id,
            "source_path": self.smap.program.source_path,
            "author": self.smap.program.author,
            "generated": datetime.now().isoformat(),
            "statistics": self._stats_dict(),
            "file_controls": [
                {"name": fc.select_name, "assign_to": fc.assign_to}
                for fc in self.smap.program.file_controls
            ],
            "paragraphs": [
                {
                    "name": p.name,
                    "statement_count": len(p.statements),
                    "verbs": sorted({s.verb for s in p.statements}),
                }
                for p in self.smap.program.paragraphs
            ],
            "sensitivities": [
                {
                    "data_name": f.data_name,
                    "pattern": f.pattern_matched,
                    "level": f.level.value,
                    "reason": f.reason,
                }
                for f in self.smap.sensitivities
            ],
            "dependencies": [
                {
                    "call_target": d.call_target,
                    "source_paragraph": d.source_paragraph,
                }
                for d in self.smap.dependencies
            ],
            "warnings": self.smap.warnings,
        }
        return json.dumps(data, indent=2)

    def _stats_dict(self) -> dict:
        s = self.smap.stats
        return {
            "total_lines": s.total_lines,
            "code_lines": s.code_lines,
            "comment_lines": s.comment_lines,
            "blank_lines": s.blank_lines,
            "paragraph_count": s.paragraph_count,
            "data_item_count": s.data_item_count,
            "statement_count": s.statement_count,
        }


def export_markdown(software_map: SoftwareMap) -> str:
    """Convenience function to export a Markdown report."""
    return MarkdownExporter(software_map).export()


def export_json(software_map: SoftwareMap) -> str:
    """Convenience function to export a JSON report."""
    return JsonExporter(software_map).export()
