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
def payroll_calc_source(payroll_calc_cob: Path) -> str:
    return payroll_calc_cob.read_text()


@pytest.fixture
def bankacct_cob() -> Path:
    return SAMPLES_DIR / "BANKACCT.cob"


@pytest.fixture
def bankacct_source(bankacct_cob: Path) -> str:
    return bankacct_cob.read_text()


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES_DIR
