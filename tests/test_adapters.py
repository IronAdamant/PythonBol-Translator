"""Tests for the runtime adapter classes."""

from decimal import Decimal
from pathlib import Path

import pytest

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
        assert d.value == Decimal("10.00")

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
        assert a <= 10
        assert a <= 15
        assert b >= 20
        assert b >= 15
        assert a <= b
        assert b >= a

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
        with pytest.raises(RuntimeError, match="File not opened"):
            fa.read()

    def test_reopen_resets_to_beginning(self, tmp_path):
        """Re-opening should close previous handle and restart from beginning."""
        f = tmp_path / "reopen.txt"
        f.write_text("line1\nline2\n")
        fa = FileAdapter(str(f))
        fa.open_input()
        assert fa.read() == "line1"
        fa.open_input()  # re-open
        assert fa.read() == "line1", "Re-open should restart from beginning"
        fa.close()

    def test_read_strips_windows_crlf(self, tmp_path):
        """read() must strip both \\r and \\n so Windows CRLF files work correctly."""
        f = tmp_path / "windows.dat"
        f.write_bytes(b"RECORD001\r\nRECORD002\r\n")
        fa = FileAdapter(str(f))
        fa.open_input()
        assert fa.read() == "RECORD001"
        assert fa.read() == "RECORD002"
        assert fa.read() is None
        fa.close()


class TestCobolDecimalInvalidOperand:
    def test_add_invalid_string_leaves_value_unchanged(self):
        import warnings as w_mod
        d = CobolDecimal(5, 2, False, "10.00")
        with w_mod.catch_warnings(record=True) as w:
            w_mod.simplefilter("always")
            d.add("not-a-number")
            assert len(w) == 1
            assert "Invalid operand" in str(w[0].message)
        assert d.value == Decimal("10.00")


class TestSignedNegativeOverflow:
    def test_signed_negative_overflow_truncates(self):
        d = CobolDecimal(2, 0, signed=True)  # range -99 to 99
        d.set(-90)
        d.subtract(20)  # -110, should truncate to -10
        assert d.value == Decimal("-10")

    def test_signed_negative_decimal_truncation(self):
        d = CobolDecimal(3, 2, signed=True)
        d.set("-5.999")
        # COBOL truncates toward zero: -5.99, not rounded to -6.00
        assert d.value == Decimal("-5.99")


class TestAdapterComparisonEdgeCases:
    def test_cobol_string_eq_int_returns_false(self):
        s = CobolString(5, "HELLO")
        assert not (s == 42)

    def test_cobol_decimal_eq_string_returns_false(self):
        d = CobolDecimal(5, 2, False, "10.00")
        assert not (d == "not-a-number")


class TestCobolStringComparisons:
    """Tests for CobolString comparison operators (COBOL-style padding)."""

    def test_lt(self):
        a = CobolString(5, "AB")
        b = CobolString(5, "CD")
        assert a < b
        assert a < "CD"

    def test_gt(self):
        a = CobolString(5, "CD")
        b = CobolString(5, "AB")
        assert a > b
        assert a > "AB"

    def test_le(self):
        a = CobolString(5, "AB")
        b = CobolString(5, "AB")
        assert a <= b
        assert a <= "AB"
        assert a <= "CD"

    def test_ge(self):
        a = CobolString(5, "CD")
        assert a >= "AB"
        assert a >= "CD"

    def test_different_size_padding(self):
        """COBOL pads shorter operand with spaces for comparison."""
        a = CobolString(3, "AB")
        b = CobolString(5, "AB")
        assert a == b

    def test_set_accepts_int(self):
        """CobolString.set should accept int (from MOVE ZEROS)."""
        s = CobolString(5)
        s.set(0)
        assert s.value == "0    "

    def test_set_accepts_float(self):
        s = CobolString(10)
        s.set(3.14)
        assert s.value.startswith("3.14")


class TestCobolDecimalRepr:
    def test_repr_no_decimals_omits_v(self):
        d = CobolDecimal(5, 0)
        r = repr(d)
        assert "V" not in r
        assert "9(5)" in r

    def test_repr_with_decimals_includes_v(self):
        d = CobolDecimal(5, 2, signed=True)
        r = repr(d)
        assert "V9(2)" in r
        assert "S" in r


class TestCobolDecimalConversions:
    def test_float_conversion(self):
        d = CobolDecimal(5, 2, False, "12.34")
        assert float(d) == 12.34
        assert isinstance(float(d), float)

    def test_int_conversion(self):
        d = CobolDecimal(5, 2, False, "12.99")
        assert int(d) == 12
        assert isinstance(int(d), int)
