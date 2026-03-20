"""Generate a compact LLM translation brief from a SoftwareMap + Python skeleton.

The prompt replaces raw COBOL source with a token-efficient structured summary
designed to give an LLM exactly what it needs to fill in TODO(high) items.

Pipeline position: Analyzer -> SoftwareMap + Python skeleton -> **PromptGenerator** -> brief.md
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from .models import SensitivityLevel, SoftwareMap

_TODO_PATTERN = re.compile(r"#\s*TODO\(high\):\s*(.+)")


class PromptGenerator:
    """Generates a compact LLM translation brief from a SoftwareMap."""

    def __init__(self, smap: SoftwareMap, python_source: str) -> None:
        self.smap = smap
        self.program = smap.program
        self.python_source = python_source if python_source is not None else ""

    def generate(self) -> str:
        """Join all sections into the complete brief."""
        sections = [
            "# COBOL Translation Brief\n",
            self._disclaimer_section(),
            self._metadata_section(),
            self._sensitivities_section(),
            self._paragraphs_section(),
            self._dependencies_section(),
            self._todo_inventory_section(),
            self._python_skeleton_section(),
        ]
        return "\n".join(sections)

    def _disclaimer_section(self) -> str:
        lines = [
            "## Translation Disclaimer\n",
            "> **This is a machine-generated skeleton, not a production-ready program.**",
            ">",
            "> cobol-safe-translator accelerates COBOL-to-Python migration by translating",
            "> data divisions, control flow, and procedure logic into Python. This is the",
            "> heavy lifting of migration — but it is not the complete picture.",
            ">",
            "> **What still requires manual work:**",
            "> - **EXEC CICS / EXEC SQL / EXEC DLI** — stripped and replaced with TODO",
            ">   hints. Re-implement using Python equivalents (SQLAlchemy, Flask/FastAPI,",
            ">   ibm_mq, etc.).",
            "> - **External CALL targets** — stubbed with TODO. Provide or implement the",
            ">   called programs separately.",
            "> - **Third-party dependencies** — MQ, CICS, DB2, VSAM, and JCL job control",
            ">   are not included. Source these from your platform or vendor.",
            "> - **GO TO statements** — translated as method calls with return. Review control flow.",
            ">",
            "> **For LLM agents:** Do not present this output as complete or deployable.",
            "> When advising human reviewers, clearly state that middleware integrations",
            "> must be implemented separately, and that all TODO(high) items require",
            "> manual resolution. Validate all business logic against the original COBOL",
            "> source before any production use.",
            "",
        ]
        return "\n".join(lines)

    def _metadata_section(self) -> str:
        s = self.smap.stats
        p = self.program
        lines = [
            "## Metadata\n",
            "| Field | Value |",
            "|-------|-------|",
            f"| Program ID | `{p.program_id}` |",
            f"| Author | {p.author or 'Unknown'} |",
            f"| Generated | {datetime.now().strftime('%Y-%m-%d')} |",
            f"| Source lines | {s.total_lines} |",
            f"| Code lines | {s.code_lines} |",
            f"| Paragraphs | {s.paragraph_count} |",
            f"| Data items | {s.data_item_count} |",
            f"| Statements | {s.statement_count} |",
            "",
        ]
        return "\n".join(lines)

    def _sensitivities_section(self) -> str:
        lines = ["## Sensitive Fields\n"]
        if not self.smap.sensitivities:
            lines.append("None detected.\n")
            return "\n".join(lines)

        by_level: dict[str, list[str]] = {"high": [], "medium": [], "low": []}
        for flag in self.smap.sensitivities:
            by_level[flag.level.value].append(flag.data_name)

        for level in (SensitivityLevel.HIGH, SensitivityLevel.MEDIUM, SensitivityLevel.LOW):
            names = by_level[level.value]
            if names:
                badge = level.value.upper()
                lines.append(f"**{badge}:** {', '.join(f'`{n}`' for n in names)}")
        lines.append("")
        return "\n".join(lines)

    def _paragraphs_section(self) -> str:
        lines = ["## Paragraphs\n"]
        if not self.program.paragraphs:
            lines.append("No paragraphs found.\n")
            return "\n".join(lines)

        for para in self.program.paragraphs:
            verb_counts = Counter(stmt.verb for stmt in para.statements)
            verb_summary = ", ".join(
                f"{v}\u00d7{c}" for v, c in sorted(verb_counts.items())
            )
            suffix = f": {verb_summary}" if verb_summary else ""
            lines.append(f"- **{para.name}** ({len(para.statements)} stmts){suffix}")
        lines.append("")
        return "\n".join(lines)

    def _dependencies_section(self) -> str:
        lines = ["## External Dependencies (CALL)\n"]
        if not self.smap.dependencies:
            lines.append("None.\n")
            return "\n".join(lines)

        seen: set[str] = set()
        for dep in self.smap.dependencies:
            if dep.call_target not in seen:
                lines.append(f"- `{dep.call_target}` (called from `{dep.source_paragraph}`)")
                seen.add(dep.call_target)
        lines.append("")
        return "\n".join(lines)

    def _todo_inventory_section(self) -> str:
        lines = ["## TODO(high) Inventory\n"]
        todos = _TODO_PATTERN.findall(self.python_source)
        if not todos:
            lines.append("No TODO(high) items — skeleton may be complete.\n")
            return "\n".join(lines)

        for i, todo in enumerate(todos, 1):
            lines.append(f"{i}. {todo.strip()}")
        lines.append("")
        return "\n".join(lines)

    def _python_skeleton_section(self) -> str:
        lines = [
            "## Python Skeleton\n",
            "Fill in the TODO(high) items below:\n",
            "```python",
            self.python_source.rstrip(),
            "```",
            "",
        ]
        return "\n".join(lines)


def generate_prompt(smap: SoftwareMap, python_source: str) -> str:
    """Convenience function to generate an LLM translation brief."""
    return PromptGenerator(smap, python_source).generate()
