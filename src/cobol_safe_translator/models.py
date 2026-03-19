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
class ConditionName:
    """88-level condition name (e.g., 88 WS-EOF VALUE "Y")."""
    name: str
    values: list[str] = field(default_factory=list)  # VALUE "A" "B" "C"
    thru_ranges: list[tuple[str, str]] = field(default_factory=list)  # VALUE 1 THRU 10


@dataclass
class DataItem:
    level: int
    name: str
    pic: PicClause | None = None
    value: str | None = None
    occurs: int | None = None
    redefines: str | None = None
    usage: str | None = None  # COMP, COMP-3, BINARY, etc.
    children: list[DataItem] = field(default_factory=list)
    conditions: list[ConditionName] = field(default_factory=list)  # 88-level items
    is_external: bool = False
    is_global: bool = False
    justified_right: bool = False
    blank_when_zero: bool = False
    occurs_depending: str | None = None  # field name for variable-length


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


@dataclass
class UseDeclaration:
    """A USE declarative section with handler body."""
    section_name: str
    use_type: str  # "ERROR", "EXCEPTION", "REPORTING", "DEBUGGING"
    targets: list[str] = field(default_factory=list)
    is_global: bool = False
    before_after: str = "AFTER"
    paragraphs: list[Paragraph] = field(default_factory=list)


# --- Top-level program model ---

@dataclass
class FileControl:
    select_name: str
    assign_to: str
    file_status: str | None = None
    organization: str | None = None  # SEQUENTIAL, INDEXED, RELATIVE
    access_mode: str | None = None  # SEQUENTIAL, RANDOM, DYNAMIC
    record_key: str | None = None
    alternate_keys: list[str] = field(default_factory=list)


# --- SCREEN SECTION models ---

@dataclass
class ScreenField:
    """A field in the SCREEN SECTION."""
    level: int
    name: str = ""
    line: int = 0
    column: int = 0
    pic: str = ""
    value: str = ""
    using: str = ""  # USING data-name (input/output)
    from_field: str = ""  # FROM data-name (display only)
    to_field: str = ""  # TO data-name (input only)
    blank_screen: bool = False
    attributes: list[str] = field(default_factory=list)  # HIGHLIGHT, BLINK, etc.
    children: list[ScreenField] = field(default_factory=list)


# --- REPORT SECTION models ---

@dataclass
class ReportField:
    """A printable field within a report line (03-level with PIC/SOURCE/SUM/VALUE)."""
    name: str = ""  # optional field name
    column: int = 0
    pic: str = ""
    source: str = ""  # SOURCE data-name (runtime value)
    sum_field: str = ""  # SUM data-name (accumulated value)
    value: str = ""  # literal VALUE
    group_indicate: bool = False


@dataclass
class ReportLine:
    """A LINE entry within a report group (02-level with LINE IS ...)."""
    line_number: int | str = 0  # absolute number or "PLUS n"
    fields: list[ReportField] = field(default_factory=list)


@dataclass
class ReportGroup:
    """A 01-level report group (TYPE IS DETAIL, CONTROL HEADING, etc.)."""
    name: str = ""
    type_clause: str = ""  # e.g. "DETAIL", "REPORT HEADING", "CONTROL FOOTING STATENUM"
    next_group: str = ""  # NEXT GROUP PLUS n
    lines: list[ReportLine] = field(default_factory=list)


@dataclass
class ReportDescription:
    """RD entry — Report Description."""
    name: str = ""
    controls: list[str] = field(default_factory=list)  # CONTROLS ARE field1 field2 ...
    page_limit: int = 0
    heading: int = 0
    first_detail: int = 0
    last_detail: int = 0
    footing: int = 0
    groups: list[ReportGroup] = field(default_factory=list)


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
    linkage_section: list[DataItem] = field(default_factory=list)
    local_storage: list[DataItem] = field(default_factory=list)
    report_section: list[ReportDescription] = field(default_factory=list)
    screen_section: list[ScreenField] = field(default_factory=list)

    # PROCEDURE
    paragraphs: list[Paragraph] = field(default_factory=list)
    declaratives: list[UseDeclaration] = field(default_factory=list)

    # Nested/concatenated programs within the same source file
    nested_programs: list[CobolProgram] = field(default_factory=list)

    # Raw text preserved for reference
    raw_lines: list[str] = field(default_factory=list)

    @property
    def all_data_items(self) -> list[DataItem]:
        """All data items across working-storage, local-storage, file section, and linkage."""
        return self.working_storage + self.local_storage + self.file_section + self.linkage_section


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
