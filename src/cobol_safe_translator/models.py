"""Shared dataclasses for the COBOL-to-Python translator pipeline.

All state flows forward through these structures:
  COBOL Source -> Parser -> AST (CobolProgram) -> Analyzer -> Exporter
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


# --- PIC clause models ---

class PicCategory(Enum):
    NUMERIC = auto()
    ALPHANUMERIC = auto()
    ALPHABETIC = auto()
    EDITED = auto()
    UNKNOWN = auto()


@dataclass
class PicClause:
    raw: str
    expanded: str  # e.g. "9(5)V99" -> "99999V99"
    category: PicCategory
    size: int  # total character positions
    decimals: int = 0
    signed: bool = False


# --- DATA DIVISION models ---

@dataclass
class DataItem:
    level: int
    name: str
    pic: PicClause | None = None
    value: str | None = None
    occurs: int | None = None
    redefines: str | None = None
    children: list[DataItem] = field(default_factory=list)


# --- PROCEDURE DIVISION models ---

@dataclass
class CobolStatement:
    verb: str  # MOVE, ADD, PERFORM, IF, EVALUATE, DISPLAY, etc.
    raw_text: str
    operands: list[str] = field(default_factory=list)


@dataclass
class Paragraph:
    name: str
    statements: list[CobolStatement] = field(default_factory=list)


# --- Top-level program model ---

@dataclass
class FileControl:
    select_name: str
    assign_to: str


@dataclass
class CobolProgram:
    program_id: str = ""
    source_path: str = ""

    # IDENTIFICATION
    author: str = ""

    # ENVIRONMENT
    file_controls: list[FileControl] = field(default_factory=list)

    # DATA
    file_section: list[DataItem] = field(default_factory=list)
    working_storage: list[DataItem] = field(default_factory=list)

    # PROCEDURE
    paragraphs: list[Paragraph] = field(default_factory=list)

    # Raw text preserved for reference
    raw_lines: list[str] = field(default_factory=list)


# --- Analysis models ---

class SensitivityLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class SensitivityFlag:
    data_name: str
    pattern_matched: str
    level: SensitivityLevel
    reason: str


@dataclass
class Dependency:
    call_target: str
    source_paragraph: str


@dataclass
class ProgramStats:
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    paragraph_count: int = 0
    data_item_count: int = 0
    statement_count: int = 0


@dataclass
class SoftwareMap:
    program: CobolProgram
    sensitivities: list[SensitivityFlag] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    stats: ProgramStats = field(default_factory=ProgramStats)
    warnings: list[str] = field(default_factory=list)
