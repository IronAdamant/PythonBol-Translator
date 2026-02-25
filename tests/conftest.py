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
