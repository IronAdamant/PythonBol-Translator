"""Screen-related code generation methods for PythonMapper.

Extracted from mapper_codegen.py and mapper_verbs.py to keep each
module under 500 LOC.

Contains: _screen_layout_comments, _emit_screen_comments,
_collect_screen_fields, _translate_screen_display, _translate_screen_accept.
"""

from __future__ import annotations

from .models import ScreenField
from .utils import _to_python_name


class ScreenCodegenMixin:
    """Screen section code generation and I/O translation methods."""

    # --- SCREEN SECTION layout comments (from mapper_codegen.py) ---

    def _screen_layout_comments(self) -> str:
        """Generate comments describing the SCREEN SECTION layout."""
        if not self.program.screen_section:
            return ""

        lines: list[str] = []
        lines.append("")
        lines.append("# " + "=" * 60)
        lines.append("# SCREEN SECTION")
        lines.append("# " + "=" * 60)
        for screen in self.program.screen_section:
            lines.append(f"# SCREEN: {screen.name or '(unnamed)'}")
            self._emit_screen_comments(screen, lines, indent=1)
            lines.append(
                "#   TODO(high): implement screen I/O"
                " -- consider curses, prompt_toolkit, or web UI"
            )
            lines.append("#")
        lines.append("")
        return "\n".join(lines)

    def _emit_screen_comments(
        self, sf: ScreenField, lines: list[str], indent: int,
    ) -> None:
        """Recursively emit comment lines describing a screen field tree."""
        prefix = "#" + "  " * indent
        fields = self._collect_screen_fields(sf)
        for f in fields:
            parts: list[str] = []
            if f.line or f.column:
                parts.append(f"Line {f.line}, Col {f.column}")
            if f.blank_screen:
                parts.append("BLANK SCREEN")
            if f.value:
                parts.append(f'"{f.value}"')
            if f.pic:
                parts.append(f"PIC {f.pic}")
            if f.using:
                parts.append(f"USING {f.using}")
            elif f.from_field:
                parts.append(f"FROM {f.from_field}")
            elif f.to_field:
                parts.append(f"TO {f.to_field}")
            if f.attributes:
                parts.append(f"[{', '.join(f.attributes)}]")
            lines.append(f"{prefix} {': '.join(parts) if parts else '(empty field)'}")

    # --- SCREEN SECTION I/O methods (from mapper_verbs.py) ---

    def _collect_screen_fields(self, sf: ScreenField) -> list[ScreenField]:
        """Flatten a screen tree into leaf fields in display order."""
        leaves: list[ScreenField] = []
        if sf.value or sf.pic or sf.using or sf.from_field or sf.to_field or sf.blank_screen:
            leaves.append(sf)
        for child in sf.children:
            leaves.extend(self._collect_screen_fields(child))
        return leaves

    def _translate_screen_display(self, screen: ScreenField) -> list[str]:
        """Generate print() calls for DISPLAY screen-name."""
        lines = [f"# DISPLAY {screen.name}"]
        fields = self._collect_screen_fields(screen)
        if not fields:
            lines.append(f"pass  # screen {screen.name} has no displayable fields")
            return lines
        for sf in fields:
            if sf.blank_screen:
                lines.append("print('\\n' * 24)  # BLANK SCREEN")
                continue
            if sf.value:
                lines.append(f"print({sf.value!r}, end='')")
            if sf.using:
                py = _to_python_name(sf.using)
                lines.append(f"print(self.data.{py}.value, end='')")
            elif sf.from_field:
                py = _to_python_name(sf.from_field)
                lines.append(f"print(self.data.{py}.value, end='')")
        # Add a trailing newline
        lines.append("print()  # end of screen")
        return lines

    def _translate_screen_accept(self, screen: ScreenField) -> list[str]:
        """Generate input() calls for ACCEPT screen-name."""
        lines = [f"# ACCEPT {screen.name}"]
        fields = self._collect_screen_fields(screen)
        if not fields:
            lines.append(f"pass  # screen {screen.name} has no input fields")
            return lines
        for sf in fields:
            if sf.blank_screen:
                lines.append("print('\\n' * 24)  # BLANK SCREEN")
                continue
            if sf.value:
                lines.append(f"print({sf.value!r}, end='')")
            if sf.using:
                py = _to_python_name(sf.using)
                lines.append(f"self.data.{py}.set(input())")
            elif sf.to_field:
                py = _to_python_name(sf.to_field)
                lines.append(f"self.data.{py}.set(input())")
            elif sf.from_field:
                py = _to_python_name(sf.from_field)
                lines.append(f"print(self.data.{py}.value, end='')")
        return lines
