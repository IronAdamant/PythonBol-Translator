"""Tests for the runtime adapter classes."""

from decimal import Decimal
from pathlib import Path

import pytest

from cobol_safe_translator.adapters import (
    CobolDecimal, CobolString, FileAdapter, GroupView, IndexedFileAdapter,
)


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

    def test_write_methods_exist(self):
        fa = FileAdapter("dummy.dat")
        assert hasattr(fa, "write")
        assert hasattr(fa, "open_output")
        assert hasattr(fa, "open_extend")
        assert hasattr(fa, "open_io")

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


class TestCobolDecimalNegativeZero:
    def test_overflow_at_exact_modulus_does_not_produce_negative_zero(self):
        """set(-100) on (2,0) should overflow to 0, not -0."""
        d = CobolDecimal(2, 0, signed=True)
        d.set(-100)
        assert str(d.value) == "0"
        assert d.value >= 0

    def test_overflow_non_zero_negative_is_fine(self):
        d = CobolDecimal(2, 0, signed=True)
        d.set(-150)  # -150 mod 100 = -50
        assert d.value == Decimal("-50")


class TestGroupView:
    """Tests for GroupView — concatenated view of COBOL group item fields."""

    def test_value_concatenates_children(self):
        """GroupView.value should concatenate child fields padded to their sizes."""
        f1 = CobolString(5, "HELLO")
        f2 = CobolString(5, "WORLD")
        gv = GroupView([f1, f2], [5, 5])
        assert gv.value == "HELLOWORLD"

    def test_value_pads_short_fields(self):
        """Short field values are space-padded to their PIC size."""
        f1 = CobolString(5, "AB")
        f2 = CobolString(3, "X")
        gv = GroupView([f1, f2], [5, 3])
        assert gv.value == "AB   X  "
        assert len(gv.value) == 8

    def test_value_truncates_long_fields(self):
        """Fields longer than their PIC size are truncated."""
        f1 = CobolString(3, "ABCDE")
        gv = GroupView([f1], [3])
        assert gv.value == "ABC"

    def test_set_distributes_across_children(self):
        """GroupView.set should distribute a string across child fields."""
        f1 = CobolString(3)
        f2 = CobolString(3)
        f3 = CobolString(4)
        gv = GroupView([f1, f2, f3], [3, 3, 4])
        gv.set("ABCDEFGHIJ")
        assert f1.value == "ABC"
        assert f2.value == "DEF"
        assert f3.value == "GHIJ"

    def test_set_pads_short_value(self):
        """Short source values are space-padded before distribution."""
        f1 = CobolString(3)
        f2 = CobolString(3)
        gv = GroupView([f1, f2], [3, 3])
        gv.set("AB")
        assert f1.value == "AB "
        assert f2.value == "   "

    def test_set_with_numeric_children(self):
        """GroupView.set should distribute across CobolDecimal children too."""
        f1 = CobolDecimal(3, 0)
        f2 = CobolDecimal(2, 0)
        gv = GroupView([f1, f2], [3, 2])
        gv.set("12345")
        assert f1.value == Decimal("123")
        assert f2.value == Decimal("45")

    def test_size_property(self):
        """GroupView.size returns the total of all child sizes."""
        f1 = CobolString(5)
        f2 = CobolString(10)
        gv = GroupView([f1, f2], [5, 10])
        assert gv.size == 15

    def test_group_to_group_move_via_set(self):
        """Simulate group-to-group MOVE: read from one GroupView, set another."""
        # Source: WS-SRC with children "ABC" (3) and "DE" (2)
        src_f1 = CobolString(3, "ABC")
        src_f2 = CobolString(2, "DE")
        src_gv = GroupView([src_f1, src_f2], [3, 2])

        # Target: WS-TGT with children of size 2 and 3
        tgt_f1 = CobolString(2)
        tgt_f2 = CobolString(3)
        tgt_gv = GroupView([tgt_f1, tgt_f2], [2, 3])

        # Group MOVE: distribute source concatenation across target
        tgt_gv.set(src_gv.value)
        assert tgt_f1.value == "AB"
        assert tgt_f2.value == "CDE"

    def test_mixed_field_types(self):
        """GroupView should handle mixed CobolString and CobolDecimal children."""
        f1 = CobolString(5, "HELLO")
        f2 = CobolDecimal(3, 0, initial=42)
        gv = GroupView([f1, f2], [5, 3])
        # CobolDecimal(3,0) with value 42 => str is "42", padded to "42 "
        assert gv.value == "HELLO42 "

    def test_value_with_numeric_decimal_child(self):
        """Numeric field with decimals formats correctly in group view."""
        f1 = CobolDecimal(3, 2, initial=1.23)
        gv = GroupView([f1], [5])
        # Decimal "1.23" as string is "1.23", padded to 5 chars
        assert gv.value == "1.23 "
        assert len(gv.value) == 5


class TestIndexedFileAdapter:
    """Tests for IndexedFileAdapter — SQLite-backed VSAM-style keyed access."""

    def test_write_then_sequential_read(self, tmp_path):
        """OPEN OUTPUT + WRITE records, then OPEN INPUT + sequential READ."""
        db_file = str(tmp_path / "customers.dat")
        fa = IndexedFileAdapter(db_file, record_key="cust_id", access_mode="SEQUENTIAL")

        fa.open_output()
        assert fa.status == "00"
        fa.write("Alice Record", key="001")
        fa.write("Bob Record", key="002")
        fa.write("Carol Record", key="003")
        fa.close()

        fa.open_input()
        assert fa.read() == "Alice Record"
        assert fa.status == "00"
        assert fa.read() == "Bob Record"
        assert fa.read() == "Carol Record"
        assert fa.read() is None
        assert fa.eof is True
        assert fa.status == "10"
        fa.close()

    def test_random_read_by_key(self, tmp_path):
        """Random read retrieves the correct record by key."""
        db_file = str(tmp_path / "accounts.dat")
        fa = IndexedFileAdapter(db_file, record_key="acct_no", access_mode="RANDOM")

        fa.open_output()
        fa.write("Checking 1000", key="CHK001")
        fa.write("Savings 5000", key="SAV001")
        fa.write("Checking 2000", key="CHK002")
        fa.close()

        fa.open_input()
        assert fa.read(key="SAV001") == "Savings 5000"
        assert fa.status == "00"
        assert fa.read(key="CHK002") == "Checking 2000"
        assert fa.status == "00"
        fa.close()

    def test_rewrite_existing_record(self, tmp_path):
        """REWRITE updates an existing record in place."""
        db_file = str(tmp_path / "inventory.dat")
        fa = IndexedFileAdapter(db_file, record_key="item_id", access_mode="RANDOM")

        fa.open_output()
        fa.write("Widget qty=10", key="W001")
        fa.write("Gadget qty=5", key="G001")
        fa.close()

        fa.open_io()
        fa.rewrite("Widget qty=20", key="W001")
        assert fa.status == "00"
        # Verify the update
        assert fa.read(key="W001") == "Widget qty=20"
        assert fa.read(key="G001") == "Gadget qty=5"
        fa.close()

    def test_delete_record(self, tmp_path):
        """DELETE removes a record by key."""
        db_file = str(tmp_path / "employees.dat")
        fa = IndexedFileAdapter(db_file, record_key="emp_id", access_mode="RANDOM")

        fa.open_output()
        fa.write("John Doe", key="E001")
        fa.write("Jane Smith", key="E002")
        fa.write("Bob Jones", key="E003")
        fa.close()

        fa.open_io()
        fa.delete(key="E002")
        assert fa.status == "00"
        # Verify deletion
        assert fa.read(key="E002") is None
        assert fa.status == "23"
        # Other records still exist
        assert fa.read(key="E001") == "John Doe"
        assert fa.read(key="E003") == "Bob Jones"
        fa.close()

    def test_start_positioning_then_sequential_read(self, tmp_path):
        """START positions the cursor, then sequential READ continues from there."""
        db_file = str(tmp_path / "products.dat")
        fa = IndexedFileAdapter(db_file, record_key="prod_id", access_mode="DYNAMIC")

        fa.open_output()
        fa.write("Apple", key="A01")
        fa.write("Banana", key="B01")
        fa.write("Cherry", key="C01")
        fa.write("Date", key="D01")
        fa.close()

        fa.open_input()
        fa.start(key="C01", comparison="EQUAL")
        assert fa.status == "00"
        assert fa.read() == "Cherry"
        assert fa.read() == "Date"
        assert fa.read() is None
        assert fa.eof is True
        fa.close()

    def test_start_greater_than(self, tmp_path):
        """START with GREATER positions past the specified key."""
        db_file = str(tmp_path / "orders.dat")
        fa = IndexedFileAdapter(db_file, record_key="order_id", access_mode="DYNAMIC")

        fa.open_output()
        fa.write("Order 1", key="100")
        fa.write("Order 2", key="200")
        fa.write("Order 3", key="300")
        fa.close()

        fa.open_input()
        fa.start(key="100", comparison="GREATER")
        assert fa.status == "00"
        assert fa.read() == "Order 2"
        fa.close()

    def test_duplicate_key_error(self, tmp_path):
        """Writing a duplicate key sets status to '22'."""
        db_file = str(tmp_path / "unique.dat")
        fa = IndexedFileAdapter(db_file, record_key="id")

        fa.open_output()
        fa.write("First", key="K001")
        assert fa.status == "00"
        fa.write("Duplicate", key="K001")
        assert fa.status == "22"
        fa.close()

    def test_record_not_found(self, tmp_path):
        """Reading a nonexistent key sets status to '23'."""
        db_file = str(tmp_path / "sparse.dat")
        fa = IndexedFileAdapter(db_file, record_key="id", access_mode="RANDOM")

        fa.open_output()
        fa.write("Only Record", key="EXISTS")
        fa.close()

        fa.open_input()
        result = fa.read(key="MISSING")
        assert result is None
        assert fa.status == "23"
        fa.close()

    def test_eof_on_empty_file(self, tmp_path):
        """Sequential read on empty file returns EOF immediately."""
        db_file = str(tmp_path / "empty.dat")
        fa = IndexedFileAdapter(db_file, record_key="id")

        fa.open_output()
        fa.close()

        fa.open_input()
        result = fa.read()
        assert result is None
        assert fa.eof is True
        assert fa.status == "10"
        fa.close()

    def test_rewrite_nonexistent_record(self, tmp_path):
        """REWRITE on a missing key sets status to '23'."""
        db_file = str(tmp_path / "missing.dat")
        fa = IndexedFileAdapter(db_file, record_key="id", access_mode="RANDOM")

        fa.open_output()
        fa.write("Existing", key="K001")
        fa.close()

        fa.open_io()
        fa.rewrite("Updated", key="MISSING")
        assert fa.status == "23"
        fa.close()

    def test_delete_nonexistent_record(self, tmp_path):
        """DELETE on a missing key sets status to '23'."""
        db_file = str(tmp_path / "del_miss.dat")
        fa = IndexedFileAdapter(db_file, record_key="id", access_mode="RANDOM")

        fa.open_output()
        fa.write("Only", key="K001")
        fa.close()

        fa.open_io()
        fa.delete(key="MISSING")
        assert fa.status == "23"
        fa.close()

    def test_read_before_open_raises(self):
        """Reading without opening raises RuntimeError."""
        fa = IndexedFileAdapter("nonexistent.dat")
        with pytest.raises(RuntimeError, match="File not opened"):
            fa.read()

    def test_context_manager(self, tmp_path):
        """IndexedFileAdapter works as a context manager."""
        db_file = str(tmp_path / "ctx.dat")
        fa = IndexedFileAdapter(db_file, record_key="id")
        fa.open_output()
        fa.write("Test", key="001")
        fa.close()

        with IndexedFileAdapter(db_file, record_key="id") as fa2:
            assert fa2.read() == "Test"

    def test_open_output_clears_existing_data(self, tmp_path):
        """OPEN OUTPUT drops and recreates the table."""
        db_file = str(tmp_path / "clear.dat")
        fa = IndexedFileAdapter(db_file, record_key="id")

        fa.open_output()
        fa.write("Old Data", key="001")
        fa.close()

        fa.open_output()
        fa.write("New Data", key="002")
        fa.close()

        fa.open_input()
        assert fa.read() == "New Data"
        assert fa.read() is None  # old data is gone
        fa.close()

    def test_close_resets_state(self, tmp_path):
        """Close resets eof, mode, and status."""
        db_file = str(tmp_path / "reset.dat")
        fa = IndexedFileAdapter(db_file, record_key="id")
        fa.open_output()
        fa.close()
        assert fa.status == "00"
        assert fa.eof is False
        assert fa._mode is None
