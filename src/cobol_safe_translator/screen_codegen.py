"""Screen-related code generation methods for PythonMapper.

Extracted from mapper_codegen.py and mapper_verbs.py to keep each
module under 500 LOC.

Contains: _screen_layout_comments, _emit_screen_comments,
_collect_screen_fields, _translate_screen_display, _translate_screen_accept.

Screen I/O uses ANSI escape sequences for cursor positioning — zero
external dependencies, works on modern terminals including Windows Terminal.
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
        """Generate ANSI-positioned output for DISPLAY screen-name.

        Uses ANSI escape sequences for cursor positioning:
          \\033[{line};{col}H — move cursor to line, column
          \\033[2J            — clear screen
          \\033[7m / \\033[0m  — reverse video on/off
        """
        lines = [f"# DISPLAY {screen.name}"]
        fields = self._collect_screen_fields(screen)
        if not fields:
            lines.append(f"pass  # screen {screen.name} has no displayable fields")
            return lines
        for sf in fields:
            if sf.blank_screen:
                lines.append("print('\\033[2J\\033[H', end='')  # BLANK SCREEN")
                continue
            pos = ""
            if sf.line or sf.column:
                row = sf.line if sf.line else 1
                col = sf.column if sf.column else 1
                pos = f"print(f'\\033[{row};{col}H', end='')  # Line {row}, Col {col}"
                lines.append(pos)
            # Apply display attributes
            attr_on, attr_off = _ansi_attrs(sf.attributes)
            if sf.value:
                lines.append(f"print(f'{attr_on}{sf.value!s}{attr_off}', end='')")
            if sf.using:
                py = _to_python_name(sf.using)
                lines.append(f"print(f'{attr_on}{{self.data.{py}.value}}{attr_off}', end='')")
            elif sf.from_field:
                py = _to_python_name(sf.from_field)
                lines.append(f"print(f'{attr_on}{{self.data.{py}.value}}{attr_off}', end='')")
        lines.append("print()  # flush output")
        return lines

    def _translate_screen_accept(self, screen: ScreenField) -> list[str]:
        """Generate ANSI-positioned input for ACCEPT screen-name."""
        lines = [f"# ACCEPT {screen.name}"]
        fields = self._collect_screen_fields(screen)
        if not fields:
            lines.append(f"pass  # screen {screen.name} has no input fields")
            return lines
        for sf in fields:
            if sf.blank_screen:
                lines.append("print('\\033[2J\\033[H', end='')  # BLANK SCREEN")
                continue
            if sf.line or sf.column:
                row = sf.line if sf.line else 1
                col = sf.column if sf.column else 1
                lines.append(
                    f"print(f'\\033[{row};{col}H', end='')  "
                    f"# Line {row}, Col {col}"
                )
            attr_on, attr_off = _ansi_attrs(sf.attributes)
            if sf.value:
                lines.append(f"print(f'{attr_on}{sf.value!s}{attr_off}', end='')")
            if sf.using:
                py = _to_python_name(sf.using)
                lines.append(f"self.data.{py}.set(input())")
            elif sf.to_field:
                py = _to_python_name(sf.to_field)
                lines.append(f"self.data.{py}.set(input())")
            elif sf.from_field:
                py = _to_python_name(sf.from_field)
                lines.append(f"print(f'{attr_on}{{self.data.{py}.value}}{attr_off}', end='')")
        return lines


def _ansi_attrs(attributes: list[str]) -> tuple[str, str]:
    """Convert COBOL screen attributes to ANSI escape sequences.

    Returns (on_seq, off_seq) strings to wrap output.
    """
    if not attributes:
        return "", ""
    codes: list[str] = []
    for attr in attributes:
        upper = attr.upper()
        if "HIGHLIGHT" in upper:
            codes.append("1")  # bold
        elif "LOWLIGHT" in upper:
            codes.append("2")  # dim
        elif "BLINK" in upper:
            codes.append("5")  # blink
        elif "REVERSE" in upper:
            codes.append("7")  # reverse video
        elif "UNDERLINE" in upper:
            codes.append("4")  # underline
        elif "FOREGROUND" in upper:
            # Extract color number
            parts = upper.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                codes.append(f"3{parts[-1]}")
        elif "BACKGROUND" in upper:
            parts = upper.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                codes.append(f"4{parts[-1]}")
    if not codes:
        return "", ""
    on = "\\033[" + ";".join(codes) + "m"
    off = "\\033[0m"
    return on, off
