"""Tests for the runtime import validation utility."""

from pathlib import Path

from cobol_safe_translator.cli import main
from cobol_safe_translator.validation import validate_generated_python


# --- A realistic generated Python snippet that should pass all checks ---

VALID_GENERATED = '''\
"""Auto-generated Python translation of COBOL program: TEST-PROG"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from cobol_safe_translator.adapters import CobolDecimal, CobolString, FileAdapter


@dataclass
class TestProgData:
    """Working-storage data items."""

    ws_counter: CobolDecimal = field(
        default_factory=lambda: CobolDecimal(5, 0, False, '0')
    )
    ws_name: CobolString = field(
        default_factory=lambda: CobolString(20, '')
    )


class TestProgProgram:
    """Translated from COBOL program TEST-PROG."""

    def __init__(self) -> None:
        self.data = TestProgData()

    def main_paragraph(self) -> None:
        self.data.ws_counter.add(1)
        self.data.ws_name.set("HELLO")

    def run(self) -> None:
        self.main_paragraph()


if __name__ == "__main__":
    program = TestProgProgram()
    program.run()
'''


class TestValidateGeneratedPython:
    """Unit tests for validate_generated_python()."""

    def test_valid_code_passes_all_checks(self):
        """A well-formed generated file must pass syntax, compile, and import."""
        is_valid, err = validate_generated_python(VALID_GENERATED)
        assert is_valid is True
        assert err == ""

    def test_syntax_error_fails_step1(self):
        """Code with a SyntaxError must fail at step 1."""
        bad_syntax = "def foo(\n"  # missing closing paren and body
        is_valid, err = validate_generated_python(bad_syntax)
        assert is_valid is False
        assert "SyntaxError" in err

    def test_undefined_variable_fails_step3(self):
        """Module-level code referencing an undefined name fails at import."""
        bad_import = (
            "x = undefined_variable_that_does_not_exist + 1\n"
        )
        is_valid, err = validate_generated_python(bad_import)
        assert is_valid is False
        assert "NameError" in err

    def test_bad_import_fails_step3(self):
        """A module that imports a nonexistent package fails at import."""
        bad_import = "from nonexistent_package_xyz import something\n"
        is_valid, err = validate_generated_python(bad_import)
        assert is_valid is False
        assert "ImportError" in err or "ModuleNotFoundError" in err

    def test_program_class_instantiation_error_fails(self):
        """A Program class that crashes on __init__ must fail validation."""
        bad_init = '''\
class BrokenProgram:
    def __init__(self):
        raise RuntimeError("init crash")
'''
        is_valid, err = validate_generated_python(bad_init)
        assert is_valid is False
        assert "RuntimeError" in err

    def test_empty_module_passes(self):
        """An empty module (no classes) should still pass — nothing to instantiate."""
        is_valid, err = validate_generated_python("# empty module\n")
        assert is_valid is True
        assert err == ""

    def test_custom_filename_appears_in_error(self):
        """The filename parameter should appear in compile-time error messages."""
        bad_syntax = "def foo(\n"
        is_valid, err = validate_generated_python(bad_syntax, filename="test_file.py")
        assert is_valid is False
        # The filename is used in the SyntaxError from ast.parse
        assert "SyntaxError" in err


class TestValidateCLIFlag:
    """Integration tests for the --validate CLI flag."""

    def test_translate_with_validate_passes(self, hello_cob, tmp_path):
        """translate --validate on a known-good file must return 0."""
        out_dir = tmp_path / "out"
        result = main([
            "translate", str(hello_cob),
            "--output", str(out_dir),
            "--validate",
        ])
        assert result == 0

    def test_translate_directory_with_validate(self, samples_dir, tmp_path):
        """translate --validate on the samples directory must return 0."""
        out_dir = tmp_path / "out"
        result = main([
            "translate", str(samples_dir),
            "--output", str(out_dir),
            "--validate",
        ])
        assert result == 0
