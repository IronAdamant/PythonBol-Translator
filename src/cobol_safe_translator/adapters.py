"""Runtime adapter classes for generated Python code.

These classes encapsulate COBOL data semantics so that generated Python
code behaves like the original COBOL with respect to truncation, padding,
and fixed-point arithmetic.
"""

from __future__ import annotations

import warnings
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, Decimal, InvalidOperation


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

    def _coerce(self, value: int | float | str | Decimal) -> Decimal:
        """Convert and truncate a value to fit the PIC specification."""
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            d = Decimal(0)

        if not self.signed and d < 0:
            d = abs(d)

        # Truncate to max integer digits
        max_val = Decimal(10 ** self.integer_digits) - Decimal(
            10 ** -self.decimal_digits if self.decimal_digits else 1
        )
        if abs(d) > max_val:
            # COBOL truncates high-order digits
            sign = -1 if d < 0 else 1
            modulus = Decimal(10 ** self.integer_digits)
            d = sign * (abs(d) % modulus)

        # Quantize to decimal_digits — truncate toward zero (COBOL TRUNCATE)
        if self.decimal_digits > 0:
            quant = Decimal(10) ** -self.decimal_digits
        else:
            quant = Decimal(1)
        # ROUND_DOWN rounds toward zero in Python >=3.3 but to be explicit:
        # positive -> ROUND_FLOOR, negative -> ROUND_CEILING (both truncate toward zero)
        rounding = ROUND_FLOOR if d >= 0 else ROUND_CEILING
        d = d.quantize(quant, rounding=rounding)

        return d

    @property
    def value(self) -> Decimal:
        return self._value

    def set(self, value: int | float | str | Decimal) -> None:
        """MOVE equivalent — set the value with COBOL truncation rules."""
        self._value = self._coerce(value)

    def _to_decimal(self, other: int | float | str | Decimal) -> Decimal | None:
        """Convert operand to Decimal, returning None on invalid input."""
        try:
            return Decimal(str(other))
        except InvalidOperation:
            warnings.warn(f"Invalid operand {other!r}, value unchanged", stacklevel=3)
            return None

    def add(self, other: int | float | str | Decimal) -> None:
        """ADD equivalent."""
        d = self._to_decimal(other)
        if d is not None:
            self._value = self._coerce(self._value + d)

    def subtract(self, other: int | float | str | Decimal) -> None:
        """SUBTRACT equivalent."""
        d = self._to_decimal(other)
        if d is not None:
            self._value = self._coerce(self._value - d)

    def multiply(self, other: int | float | str | Decimal) -> None:
        """MULTIPLY equivalent."""
        d = self._to_decimal(other)
        if d is not None:
            self._value = self._coerce(self._value * d)

    def divide(self, other: int | float | str | Decimal) -> None:
        """DIVIDE equivalent."""
        try:
            divisor = Decimal(str(other))
        except InvalidOperation:
            warnings.warn("DIVIDE: invalid operand, value unchanged", stacklevel=2)
            return
        if divisor == 0:
            warnings.warn("DIVIDE BY ZERO: value unchanged (COBOL EC-SIZE-ZERO-DIVIDE)", stacklevel=2)
            return
        self._value = self._coerce(self._value / divisor)

    def __repr__(self) -> str:
        sign = "S" if self.signed else ""
        return f"CobolDecimal({sign}9({self.integer_digits})V9({self.decimal_digits})={self._value})"

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

    def __gt__(self, other: object) -> bool:
        if isinstance(other, CobolDecimal):
            return self._value > other._value
        if isinstance(other, (int, float, Decimal)):
            return self._value > Decimal(str(other))
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, CobolDecimal):
            return self._value <= other._value
        if isinstance(other, (int, float, Decimal)):
            return self._value <= Decimal(str(other))
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, CobolDecimal):
            return self._value >= other._value
        if isinstance(other, (int, float, Decimal)):
            return self._value >= Decimal(str(other))
        return NotImplemented

    def __float__(self) -> float:
        return float(self._value)

    def __int__(self) -> int:
        return int(self._value)


class CobolString:
    """Fixed-length string that mimics COBOL PIC X/A fields.

    Values are padded with spaces on the right and truncated on the right
    when they exceed the field size.
    """

    def __init__(self, size: int, initial: str = "") -> None:
        self.size = size
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

    def set(self, value: str) -> None:
        """MOVE equivalent for string fields."""
        self._value = self._coerce(value)

    def __repr__(self) -> str:
        return f"CobolString(X({self.size})={self._value!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CobolString):
            return self._value == other._value
        if isinstance(other, str):
            return self._value == self._coerce(other)
        return NotImplemented

    def __str__(self) -> str:
        return self._value


class FileAdapter:
    """Read-only file adapter for generated code.

    By design, this adapter has NO write methods — this is a core safety
    guarantee of the translator. It provides sequential read access only.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._file = None
        self._eof = False

    @property
    def eof(self) -> bool:
        return self._eof

    def open_input(self) -> None:
        """OPEN INPUT equivalent."""
        if self._file is not None:
            self.close()
        self._file = open(self.path, "r", encoding="utf-8")
        self._eof = False

    def read(self) -> str | None:
        """READ equivalent. Returns next line or None at EOF."""
        if self._file is None:
            raise RuntimeError("File not opened")
        line = self._file.readline()
        if not line:
            self._eof = True
            return None
        return line.rstrip("\n")

    def close(self) -> None:
        """CLOSE equivalent."""
        if self._file:
            self._file.close()
            self._file = None

    def __enter__(self) -> FileAdapter:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
