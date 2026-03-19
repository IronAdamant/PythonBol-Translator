"""Tests for incremental (diff-based) re-translation."""

import json

from conftest import make_cobol

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.incremental import (
    _hash_data_items,
    _hash_paragraph,
    _patch_method,
    compute_fingerprint,
    diff_programs,
    incremental_translate,
    load_fingerprint,
    save_fingerprint,
)
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_program(procedure_lines, data_lines=None):
    """Parse a COBOL snippet into a CobolProgram."""
    source = make_cobol(procedure_lines, data_lines)
    return parse_cobol(source)


# ---------------------------------------------------------------------------
# compute_fingerprint
# ---------------------------------------------------------------------------

class TestComputeFingerprint:
    def test_consistent_hashes(self):
        """Same source produces the same fingerprint."""
        prog = _make_program(["DISPLAY 'HELLO'."])
        fp1 = compute_fingerprint(prog)
        fp2 = compute_fingerprint(prog)
        assert fp1 == fp2

    def test_contains_data_division_key(self):
        prog = _make_program(["DISPLAY 'HELLO'."])
        fp = compute_fingerprint(prog)
        assert "_data_division" in fp

    def test_contains_file_controls_key(self):
        prog = _make_program(["DISPLAY 'HELLO'."])
        fp = compute_fingerprint(prog)
        assert "_file_controls" in fp

    def test_contains_program_id(self):
        prog = _make_program(["DISPLAY 'HELLO'."])
        fp = compute_fingerprint(prog)
        assert fp["_program_id"] == "TEST-PROG"

    def test_contains_paragraph_hash(self):
        prog = _make_program(["DISPLAY 'HELLO'."])
        fp = compute_fingerprint(prog)
        assert "para:MAIN-PARA" in fp

    def test_different_body_different_hash(self):
        """Changing a paragraph body changes its hash."""
        prog1 = _make_program(["DISPLAY 'HELLO'."])
        prog2 = _make_program(["DISPLAY 'GOODBYE'."])
        fp1 = compute_fingerprint(prog1)
        fp2 = compute_fingerprint(prog2)
        assert fp1["para:MAIN-PARA"] != fp2["para:MAIN-PARA"]

    def test_different_data_different_hash(self):
        """Changing working-storage changes the data division hash."""
        prog1 = _make_program(
            ["DISPLAY 'HELLO'."],
            data_lines=["       01 WS-X PIC 9(5)."],
        )
        prog2 = _make_program(
            ["DISPLAY 'HELLO'."],
            data_lines=["       01 WS-X PIC X(10)."],
        )
        fp1 = compute_fingerprint(prog1)
        fp2 = compute_fingerprint(prog2)
        assert fp1["_data_division"] != fp2["_data_division"]


# ---------------------------------------------------------------------------
# diff_programs
# ---------------------------------------------------------------------------

class TestDiffPrograms:
    def test_no_changes(self):
        prog = _make_program(["DISPLAY 'HI'."])
        fp = compute_fingerprint(prog)
        diff = diff_programs(fp, fp)
        assert not diff["data_changed"]
        assert not diff["file_controls_changed"]
        assert diff["paragraphs_added"] == []
        assert diff["paragraphs_removed"] == []
        assert diff["paragraphs_modified"] == []
        assert diff["paragraphs_unchanged"] == ["MAIN-PARA"]
        assert not diff["full_retranslation_needed"]

    def test_detects_modified_paragraph(self):
        prog1 = _make_program(["DISPLAY 'HELLO'."])
        prog2 = _make_program(["DISPLAY 'GOODBYE'."])
        fp1 = compute_fingerprint(prog1)
        fp2 = compute_fingerprint(prog2)
        diff = diff_programs(fp1, fp2)
        assert "MAIN-PARA" in diff["paragraphs_modified"]
        assert not diff["full_retranslation_needed"]

    def test_detects_added_paragraph(self):
        old_fp = {"_data_division": "abc", "_file_controls": "def", "_program_id": "X"}
        new_fp = {
            "_data_division": "abc", "_file_controls": "def",
            "_program_id": "X", "para:NEW-PARA": "hash1",
        }
        diff = diff_programs(old_fp, new_fp)
        assert "NEW-PARA" in diff["paragraphs_added"]
        assert diff["full_retranslation_needed"]

    def test_detects_removed_paragraph(self):
        old_fp = {
            "_data_division": "abc", "_file_controls": "def",
            "_program_id": "X", "para:OLD-PARA": "hash1",
        }
        new_fp = {"_data_division": "abc", "_file_controls": "def", "_program_id": "X"}
        diff = diff_programs(old_fp, new_fp)
        assert "OLD-PARA" in diff["paragraphs_removed"]
        assert diff["full_retranslation_needed"]

    def test_detects_data_division_change(self):
        old_fp = {"_data_division": "aaa", "_file_controls": "bbb", "_program_id": "X"}
        new_fp = {"_data_division": "ccc", "_file_controls": "bbb", "_program_id": "X"}
        diff = diff_programs(old_fp, new_fp)
        assert diff["data_changed"]
        assert diff["full_retranslation_needed"]

    def test_detects_file_controls_change(self):
        old_fp = {"_data_division": "aaa", "_file_controls": "bbb", "_program_id": "X"}
        new_fp = {"_data_division": "aaa", "_file_controls": "ccc", "_program_id": "X"}
        diff = diff_programs(old_fp, new_fp)
        assert diff["file_controls_changed"]
        assert diff["full_retranslation_needed"]


# ---------------------------------------------------------------------------
# save_fingerprint / load_fingerprint roundtrip
# ---------------------------------------------------------------------------

class TestFingerprintIO:
    def test_roundtrip(self, tmp_path):
        fp = {"_data_division": "abc", "para:MAIN": "xyz"}
        fp_path = tmp_path / "test.fingerprint.json"
        save_fingerprint(fp, fp_path)
        loaded = load_fingerprint(fp_path)
        assert loaded == fp

    def test_load_missing_returns_none(self, tmp_path):
        fp_path = tmp_path / "nonexistent.fingerprint.json"
        assert load_fingerprint(fp_path) is None

    def test_load_corrupt_returns_none(self, tmp_path):
        fp_path = tmp_path / "corrupt.fingerprint.json"
        fp_path.write_text("not valid json {{{", encoding="utf-8")
        assert load_fingerprint(fp_path) is None


# ---------------------------------------------------------------------------
# _patch_method
# ---------------------------------------------------------------------------

class TestPatchMethod:
    def test_replaces_method_body(self):
        existing = (
            "class Foo:\n"
            "    def alpha(self) -> None:\n"
            '        """Paragraph: ALPHA"""\n'
            "        print('old')\n"
            "\n"
            "    def beta(self) -> None:\n"
            '        """Paragraph: BETA"""\n'
            "        print('beta')\n"
            "\n"
        )
        new_method = (
            "    def alpha(self) -> None:\n"
            '        """Paragraph: ALPHA"""\n'
            "        print('new')\n"
        )
        patched = _patch_method(existing, "alpha", new_method)
        assert "print('new')" in patched
        assert "print('old')" not in patched
        # beta must be preserved
        assert "print('beta')" in patched

    def test_preserves_unchanged_methods(self):
        existing = (
            "class Foo:\n"
            "    def alpha(self) -> None:\n"
            "        pass\n"
            "\n"
            "    def beta(self) -> None:\n"
            "        print('keep me')\n"
            "\n"
            "    def gamma(self) -> None:\n"
            "        print('also keep')\n"
            "\n"
        )
        new_method = (
            "    def alpha(self) -> None:\n"
            "        print('replaced')\n"
        )
        patched = _patch_method(existing, "alpha", new_method)
        assert "print('replaced')" in patched
        assert "print('keep me')" in patched
        assert "print('also keep')" in patched


# ---------------------------------------------------------------------------
# incremental_translate (integration)
# ---------------------------------------------------------------------------

class TestIncrementalTranslate:
    def _write_cobol(self, path, procedure_lines, data_lines=None):
        """Write a COBOL source file to disk."""
        source = make_cobol(procedure_lines, data_lines)
        path.write_text(source, encoding="utf-8")
        return path

    def test_full_translation_on_first_run(self, tmp_path):
        """First run always does a full translation."""
        src = self._write_cobol(tmp_path / "test.cob", ["DISPLAY 'HELLO'."])
        out_path = tmp_path / "out" / "test_prog.py"

        python_source, diff = incremental_translate(src, out_path)

        assert diff["full_retranslation_needed"]
        assert diff["reason"] == "no previous translation"
        assert "class TestProgProgram" in python_source
        # Fingerprint should be saved
        fp_path = out_path.with_suffix(".fingerprint.json")
        assert fp_path.exists()

    def test_no_changes_detected(self, tmp_path):
        """Same source twice produces no changes on second run."""
        src = self._write_cobol(tmp_path / "test.cob", ["DISPLAY 'HELLO'."])
        out_path = tmp_path / "out" / "test_prog.py"

        # First run
        python_source, _ = incremental_translate(src, out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(python_source, encoding="utf-8")

        # Second run (no changes)
        python_source2, diff = incremental_translate(src, out_path)
        assert not diff["full_retranslation_needed"]
        assert diff["reason"] == "no changes"

    def test_patches_modified_paragraph(self, tmp_path):
        """Modifying a paragraph body triggers incremental patching."""
        src = tmp_path / "test.cob"
        out_path = tmp_path / "out" / "test_prog.py"

        # First run
        self._write_cobol(src, ["DISPLAY 'HELLO'."])
        python_v1, _ = incremental_translate(src, out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(python_v1, encoding="utf-8")
        assert "HELLO" in python_v1

        # Modify the paragraph body
        self._write_cobol(src, ["DISPLAY 'GOODBYE'."])
        python_v2, diff = incremental_translate(src, out_path)

        assert not diff["full_retranslation_needed"]
        assert "MAIN-PARA" in diff["paragraphs_modified"]
        assert "patched 1 paragraphs" in diff["reason"]
        assert "GOODBYE" in python_v2

    def test_full_retranslation_on_data_change(self, tmp_path):
        """Changing working-storage triggers full retranslation."""
        src = tmp_path / "test.cob"
        out_path = tmp_path / "out" / "test_prog.py"

        # First run
        self._write_cobol(
            src, ["DISPLAY 'HELLO'."],
            data_lines=["       01 WS-X PIC 9(5)."],
        )
        python_v1, _ = incremental_translate(src, out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(python_v1, encoding="utf-8")

        # Change data division
        self._write_cobol(
            src, ["DISPLAY 'HELLO'."],
            data_lines=["       01 WS-X PIC X(10)."],
        )
        python_v2, diff = incremental_translate(src, out_path)

        assert diff["full_retranslation_needed"]
        assert diff["data_changed"]

    def test_patching_preserves_unchanged_content(self, tmp_path):
        """Patching a paragraph does not alter other methods or the header."""
        src = tmp_path / "test.cob"
        out_path = tmp_path / "out" / "test_prog.py"

        # First run with a manual edit in the output
        self._write_cobol(src, ["DISPLAY 'HELLO'."])
        python_v1, _ = incremental_translate(src, out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Inject a marker comment into the header area (before the class)
        marker = "# MANUAL EDIT MARKER\n"
        python_v1_with_marker = marker + python_v1
        out_path.write_text(python_v1_with_marker, encoding="utf-8")

        # Modify paragraph
        self._write_cobol(src, ["DISPLAY 'CHANGED'."])
        python_v2, diff = incremental_translate(src, out_path)

        assert not diff["full_retranslation_needed"]
        # The marker should still be there -- patching preserves non-method text
        assert "# MANUAL EDIT MARKER" in python_v2
        assert "CHANGED" in python_v2


# ---------------------------------------------------------------------------
# _hash_paragraph / _hash_data_items unit tests
# ---------------------------------------------------------------------------

class TestHashFunctions:
    def test_hash_paragraph_deterministic(self):
        prog = _make_program(["DISPLAY 'A'."])
        para = prog.paragraphs[0]
        assert _hash_paragraph(para) == _hash_paragraph(para)

    def test_hash_paragraph_changes_with_content(self):
        prog1 = _make_program(["DISPLAY 'A'."])
        prog2 = _make_program(["DISPLAY 'B'."])
        assert _hash_paragraph(prog1.paragraphs[0]) != _hash_paragraph(prog2.paragraphs[0])

    def test_hash_data_items_deterministic(self):
        prog = _make_program(["DISPLAY 'A'."])
        h1 = _hash_data_items(prog.all_data_items)
        h2 = _hash_data_items(prog.all_data_items)
        assert h1 == h2

    def test_hash_data_items_changes_with_content(self):
        prog1 = _make_program(
            ["DISPLAY 'A'."],
            data_lines=["       01 WS-X PIC 9(5)."],
        )
        prog2 = _make_program(
            ["DISPLAY 'A'."],
            data_lines=["       01 WS-X PIC X(10)."],
        )
        assert _hash_data_items(prog1.all_data_items) != _hash_data_items(prog2.all_data_items)
