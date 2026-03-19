"""Runtime adapter classes for generated Python code.

These classes encapsulate COBOL data semantics so that generated Python
code behaves like the original COBOL with respect to truncation, padding,
and fixed-point arithmetic.
"""

from __future__ import annotations

import warnings
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from functools import total_ordering


@total_ordering
class CobolDecimal:
    """Fixed-point decimal that mimics COBOL PIC 9/S9 with V (implied decimal).

    Args:
        integer_digits: Number of digits before the decimal point.
        decimal_digits: Number of digits after the decimal point.
        signed: Whether the field allows negative values.
        initial: Initial value (default 0).
    """

    def __init__(
        self,
        integer_digits: int,
        decimal_digits: int = 0,
        signed: bool = False,
        initial: int | float | str | Decimal = 0,
    ) -> None:
        self.integer_digits = integer_digits
        self.decimal_digits = decimal_digits
        self.signed = signed
        self._max_digits = integer_digits + decimal_digits
        self._value = self._coerce(initial)

    def _coerce(self, value: int | float | str | Decimal, rounded: bool = False) -> Decimal:
        """Convert and truncate a value to fit the PIC specification.

        Args:
            value: The value to coerce.
            rounded: If True, use ROUND_HALF_UP (COBOL ROUNDED) instead of
                truncation toward zero.
        """
        try:
            d = Decimal(str(value))
            if not d.is_finite():
                d = Decimal(0)
        except InvalidOperation:
            d = Decimal(0)

        if not self.signed and d < 0:
            d = abs(d)

        # Truncate to max integer digits
        max_val = Decimal(10) ** self.integer_digits - (
            Decimal(10) ** -self.decimal_digits if self.decimal_digits else Decimal(1)
        )
        if abs(d) > max_val:
            # COBOL truncates high-order digits
            sign = -1 if d < 0 else 1
            modulus = Decimal(10) ** self.integer_digits
            d = sign * (abs(d) % modulus)

        # Quantize to decimal_digits
        if self.decimal_digits > 0:
            quant = Decimal(10) ** -self.decimal_digits
        else:
            quant = Decimal(1)
        if rounded:
            # COBOL ROUNDED: round half up (away from zero for .5)
            rounding = ROUND_HALF_UP
        else:
            # Default COBOL TRUNCATE: truncate toward zero
            # positive -> ROUND_FLOOR, negative -> ROUND_CEILING
            rounding = ROUND_FLOOR if d >= 0 else ROUND_CEILING
        d = d.quantize(quant, rounding=rounding)
        if d == 0:
            d = d.copy_abs()  # prevent -0 from overflow at exact modulus boundary

        return d

    @property
    def value(self) -> Decimal:
        return self._value

    def set(self, value: int | float | str | Decimal, rounded: bool = False) -> None:
        """MOVE equivalent — set the value with COBOL truncation rules.

        Args:
            value: The value to store.
            rounded: If True, use ROUND_HALF_UP instead of truncation.
        """
        self._value = self._coerce(value, rounded=rounded)

    def _to_decimal(self, other: int | float | str | Decimal | CobolDecimal) -> Decimal | None:
        """Convert operand to Decimal, returning None on invalid input."""
        if isinstance(other, CobolDecimal):
            return other._value
        try:
            return Decimal(str(other))
        except InvalidOperation:
            warnings.warn(f"Invalid operand {other!r}, value unchanged", stacklevel=3)
            return None

    def add(self, other: int | float | str | Decimal | CobolDecimal) -> None:
        """ADD equivalent."""
        d = self._to_decimal(other)
        if d is not None:
            self._value = self._coerce(self._value + d)

    def subtract(self, other: int | float | str | Decimal | CobolDecimal) -> None:
        """SUBTRACT equivalent."""
        d = self._to_decimal(other)
        if d is not None:
            self._value = self._coerce(self._value - d)

    def multiply(self, other: int | float | str | Decimal | CobolDecimal) -> None:
        """MULTIPLY equivalent."""
        d = self._to_decimal(other)
        if d is not None:
            self._value = self._coerce(self._value * d)

    def divide(self, other: int | float | str | Decimal | CobolDecimal) -> None:
        """DIVIDE equivalent."""
        divisor = self._to_decimal(other)
        if divisor is None:
            return
        if divisor == 0:
            warnings.warn("DIVIDE BY ZERO: value unchanged (COBOL EC-SIZE-ZERO-DIVIDE)", stacklevel=2)
            return
        self._value = self._coerce(self._value / divisor)

    def __repr__(self) -> str:
        sign = "S" if self.signed else ""
        dec_part = f"V9({self.decimal_digits})" if self.decimal_digits > 0 else ""
        return f"CobolDecimal({sign}9({self.integer_digits}){dec_part}={self._value})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CobolDecimal):
            return self._value == other._value
        if isinstance(other, (int, float, Decimal)):
            return self._value == Decimal(str(other))
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, CobolDecimal):
            return self._value < other._value
        if isinstance(other, (int, float, Decimal)):
            return self._value < Decimal(str(other))
        return NotImplemented

    def __float__(self) -> float:
        return float(self._value)

    def __int__(self) -> int:
        return int(self._value)


@total_ordering
class CobolString:
    """Fixed-length string that mimics COBOL PIC X/A fields.

    Values are padded with spaces on the right and truncated on the right
    when they exceed the field size.

    Args:
        ebcdic: If True, comparisons use EBCDIC (cp037) collation order
            instead of ASCII/Unicode.  Opt-in only.
    """

    def __init__(self, size: int, initial: str = "", ebcdic: bool = False) -> None:
        self.size = size
        self._ebcdic = ebcdic
        self._value = self._coerce(initial)

    def _coerce(self, value: str) -> str:
        """Pad or truncate to fixed size."""
        s = str(value)
        if len(s) > self.size:
            return s[: self.size]
        return s.ljust(self.size)

    @property
    def value(self) -> str:
        return self._value

    def set(self, value: str | int | float) -> None:
        """MOVE equivalent for string fields."""
        self._value = self._coerce(value)

    def __repr__(self) -> str:
        return f"CobolString(X({self.size})={self._value!r})"

    def _compare_value(self, other: object) -> str | None:
        """Get the coerced value of other for comparison, or None if incompatible."""
        if isinstance(other, CobolString):
            max_size = max(self.size, other.size)
            return other._value.ljust(max_size)
        if isinstance(other, str):
            return self._coerce(other)
        return None

    def _cmp_key(self, s: str) -> str | bytes:
        """Return comparison key — EBCDIC bytes if enabled, else original string."""
        if self._ebcdic:
            from .ebcdic import ebcdic_key
            return ebcdic_key(s)
        return s

    def __eq__(self, other: object) -> bool:
        val = self._compare_value(other)
        if val is None:
            return NotImplemented
        if isinstance(other, CobolString):
            max_size = max(self.size, other.size)
            return self._value.ljust(max_size) == val
        return self._value == val

    def __lt__(self, other: object) -> bool:
        val = self._compare_value(other)
        if val is None:
            return NotImplemented
        if isinstance(other, CobolString):
            max_size = max(self.size, other.size)
            return self._cmp_key(self._value.ljust(max_size)) < self._cmp_key(val)
        return self._cmp_key(self._value) < self._cmp_key(val)

    def __str__(self) -> str:
        return self._value


class GroupView:
    """Concatenated view of COBOL group item fields.

    Provides get/set that reads from or distributes across child fields
    as a single string buffer, mimicking COBOL group-level MOVE semantics.

    In COBOL, a group item is treated as an alphanumeric field whose value
    is the concatenation of all its elementary children.  When you MOVE a
    group to another group, the source's concatenated representation is
    distributed across the target's children left-to-right.
    """

    def __init__(
        self,
        fields: list[CobolDecimal | CobolString],
        sizes: list[int],
    ) -> None:
        self._fields = fields
        self._sizes = sizes
        self._total_size = sum(sizes)

    @property
    def size(self) -> int:
        return self._total_size

    @property
    def value(self) -> str:
        """Concatenate all child field values into a single string."""
        parts: list[str] = []
        for fld, sz in zip(self._fields, self._sizes):
            val = str(fld.value)
            if len(val) < sz:
                val = val.ljust(sz)
            elif len(val) > sz:
                val = val[:sz]
            parts.append(val)
        return "".join(parts)

    def set(self, value: str | int | float) -> None:
        """Distribute a string value across child fields (group MOVE)."""
        s = str(value)
        if len(s) < self._total_size:
            s = s.ljust(self._total_size)
        offset = 0
        for fld, sz in zip(self._fields, self._sizes):
            chunk = s[offset:offset + sz]
            fld.set(chunk)
            offset += sz


class FileAdapter:
    """File adapter for generated code with read and write support.

    Supports OPEN INPUT (read), OPEN OUTPUT (write/create),
    OPEN EXTEND (append), and OPEN I-O (read+write).
    """

    def __init__(self, path: str, encoding: str = "utf-8") -> None:
        self.path = path
        self.encoding = encoding
        self._file = None
        self._eof = False
        self._mode: str | None = None
        self._status: str = "00"

    @property
    def eof(self) -> bool:
        return self._eof

    @property
    def status(self) -> str:
        """COBOL FILE STATUS code: "00"=success, "10"=EOF, "35"=not found, "30"=I/O error."""
        return self._status

    def open_input(self) -> None:
        """OPEN INPUT equivalent — sequential read."""
        if self._file is not None:
            self.close()
        try:
            self._file = open(self.path, "r", encoding=self.encoding)
            self._eof = False
            self._mode = "INPUT"
            self._status = "00"
        except FileNotFoundError:
            self._status = "35"
        except OSError:
            self._status = "30"

    def open_output(self) -> None:
        """OPEN OUTPUT equivalent — create/truncate for writing."""
        if self._file is not None:
            self.close()
        try:
            self._file = open(self.path, "w", encoding=self.encoding)
            self._eof = False
            self._mode = "OUTPUT"
            self._status = "00"
        except OSError:
            self._status = "30"

    def open_extend(self) -> None:
        """OPEN EXTEND equivalent — append to existing file."""
        if self._file is not None:
            self.close()
        try:
            self._file = open(self.path, "a", encoding=self.encoding)
            self._eof = False
            self._mode = "EXTEND"
            self._status = "00"
        except OSError:
            self._status = "30"

    def open_io(self) -> None:
        """OPEN I-O equivalent — read and write."""
        if self._file is not None:
            self.close()
        try:
            self._file = open(self.path, "r+", encoding=self.encoding)
            self._eof = False
            self._mode = "I-O"
            self._status = "00"
        except FileNotFoundError:
            self._status = "35"
        except OSError:
            self._status = "30"

    def read(self) -> str | None:
        """READ equivalent. Returns next line or None at EOF."""
        if self._file is None:
            raise RuntimeError("File not opened")
        line = self._file.readline()
        if not line:
            self._eof = True
            self._status = "10"
            return None
        self._status = "00"
        return line.rstrip("\r\n")

    def write(self, record: str) -> None:
        """WRITE equivalent. Writes a record (line) to the file."""
        if self._file is None:
            raise RuntimeError("File not opened")
        if self._mode == "INPUT":
            raise RuntimeError("Cannot write to file opened for INPUT")
        self._file.write(record + "\n")
        self._status = "00"

    def close(self) -> None:
        """CLOSE equivalent."""
        if self._file:
            self._file.close()
            self._file = None
            self._mode = None
            self._eof = False
        self._status = "00"

    def __enter__(self) -> FileAdapter:
        self.open_input()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
