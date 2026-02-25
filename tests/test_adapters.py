"""Tests for the runtime adapter classes."""

import tempfile
from decimal import Decimal
from pathlib import Path

from cobol_safe_translator.adapters import CobolDecimal, CobolString, FileAdapter


class TestCobolDecimal:
    def test_basic_creation(self):
        d = CobolDecimal(5, 2)
        assert d.value == Decimal("0.00")

    def test_initial_value(self):
        d = CobolDecimal(5, 2, initial=123.45)
        assert d.value == Decimal("123.45")

    def test_set(self):
        d = CobolDecimal(5, 2)
        d.set(99.99)
        assert d.value == Decimal("99.99")

    def test_add(self):
        d = CobolDecimal(5, 2, initial=10)
        d.add(5.5)
        assert d.value == Decimal("15.50")

    def test_subtract(self):
        d = CobolDecimal(5, 2, initial=10)
        d.subtract(3.25)
        assert d.value == Decimal("6.75")

    def test_multiply(self):
        d = CobolDecimal(5, 2, initial=10)
        d.multiply(3)
        assert d.value == Decimal("30.00")

    def test_divide(self):
        d = CobolDecimal(5, 2, initial=10)
        d.divide(3)
        # COBOL truncates, so 3.33 not 3.34
        assert d.value == Decimal("3.33")

    def test_divide_by_zero(self):
        d = CobolDecimal(5, 2, initial=10)
        d.divide(0)
        assert d.value == Decimal("10.00")

    def test_truncation(self):
        d = CobolDecimal(3, 0)
        d.set(12345)
        # Should truncate high-order digits: 12345 mod 1000 = 345
        assert d.value == Decimal("345")

    def test_unsigned_rejects_negative(self):
        d = CobolDecimal(5, 2, signed=False, initial=-10)
        assert d.value >= 0

    def test_signed_allows_negative(self):
        d = CobolDecimal(5, 2, signed=True, initial=-10)
        assert d.value == Decimal("-10.00")

    def test_equality(self):
        a = CobolDecimal(5, 2, initial=10)
        b = CobolDecimal(5, 2, initial=10)
        assert a == b
        assert a == Decimal("10.00")

    def test_comparison(self):
        a = CobolDecimal(5, 2, initial=10)
        b = CobolDecimal(5, 2, initial=20)
        assert a < b
        assert b > a
        assert a < 15
        assert b > 15

    def test_repr(self):
        d = CobolDecimal(5, 2, signed=True, initial=10)
        assert "CobolDecimal" in repr(d)


class TestCobolString:
    def test_basic_creation(self):
        s = CobolString(10)
        assert s.value == " " * 10
        assert len(s.value) == 10

    def test_initial_value(self):
        s = CobolString(10, "HELLO")
        assert s.value == "HELLO     "
        assert len(s.value) == 10

    def test_padding(self):
        s = CobolString(5, "AB")
        assert s.value == "AB   "

    def test_truncation(self):
        s = CobolString(5, "ABCDEFGH")
        assert s.value == "ABCDE"
        assert len(s.value) == 5

    def test_set(self):
        s = CobolString(5)
        s.set("HI")
        assert s.value == "HI   "

    def test_equality(self):
        a = CobolString(5, "HELLO")
        b = CobolString(5, "HELLO")
        assert a == b
        assert a == "HELLO"

    def test_str(self):
        s = CobolString(5, "HI")
        assert str(s) == "HI   "

    def test_repr(self):
        s = CobolString(5, "HI")
        assert "CobolString" in repr(s)


class TestFileAdapter:
    def test_read_file(self, tmp_path):
        # Create a temp file
        test_file = tmp_path / "test.dat"
        test_file.write_text("LINE1\nLINE2\nLINE3\n")

        fa = FileAdapter(str(test_file))
        fa.open_input()

        assert fa.read() == "LINE1"
        assert fa.read() == "LINE2"
        assert fa.read() == "LINE3"
        assert fa.read() is None
        assert fa.eof is True

        fa.close()

    def test_eof_detection(self, tmp_path):
        test_file = tmp_path / "empty.dat"
        test_file.write_text("")

        fa = FileAdapter(str(test_file))
        fa.open_input()
        assert fa.read() is None
        assert fa.eof is True
        fa.close()

    def test_no_write_method(self):
        fa = FileAdapter("dummy.dat")
        assert not hasattr(fa, "write")
        assert not hasattr(fa, "open_output")

    def test_read_before_open_raises(self):
        fa = FileAdapter("dummy.dat")
        try:
            fa.read()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass
