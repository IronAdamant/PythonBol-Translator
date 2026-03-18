"""Shared fixtures for the COBOL safe translator test suite."""

from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def hello_cob() -> Path:
    return SAMPLES_DIR / "hello.cob"


@pytest.fixture
def customer_report_cob() -> Path:
    return SAMPLES_DIR / "customer-report.cob"


@pytest.fixture
def hello_source(hello_cob: Path) -> str:
    return hello_cob.read_text()


@pytest.fixture
def customer_report_source(customer_report_cob: Path) -> str:
    return customer_report_cob.read_text()


@pytest.fixture
def payroll_calc_cob() -> Path:
    return SAMPLES_DIR / "payroll-calc.cob"


@pytest.fixture
def bankacct_cob() -> Path:
    return SAMPLES_DIR / "BANKACCT.cob"


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES_DIR


def make_cobol(
    procedure_lines: list[str],
    data_lines: list[str] | None = None,
) -> str:
    """Build minimal COBOL source with given DATA and PROCEDURE lines.

    Args:
        procedure_lines: Lines for PROCEDURE DIVISION (indented automatically).
        data_lines: Optional custom WORKING-STORAGE lines. Defaults to WS-A/B/C PIC 9(5).
    """
    if data_lines is None:
        data_lines = [
            "       01 WS-A PIC 9(5).",
            "       01 WS-B PIC 9(5).",
            "       01 WS-C PIC 9(5).",
        ]
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. TEST-PROG.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        *data_lines,
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
    ]
    for pl in procedure_lines:
        lines.append(f"           {pl}")
    return "\n".join(lines) + "\n"
