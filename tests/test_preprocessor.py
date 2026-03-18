"""Tests for the COPY/EXEC preprocessor."""

from __future__ import annotations

from pathlib import Path

import pytest

from cobol_safe_translator.preprocessor import find_copybook, resolve_copies


@pytest.fixture()
def copybook_dir(tmp_path: Path) -> Path:
    """Create a temp directory with a sample copybook."""
    cpy_dir = tmp_path / "cpy"
    cpy_dir.mkdir()
    (cpy_dir / "MYBOOK.cpy").write_text(
        "       01 WS-COPIED-VAR  PIC X(10).\n", encoding="utf-8"
    )
    return cpy_dir


class TestFindCopybook:
    def test_finds_by_base_name(self, copybook_dir: Path) -> None:
        result = find_copybook("MYBOOK", [copybook_dir])
        assert result is not None
        assert result.name == "MYBOOK.cpy"

    def test_finds_with_extension(self, copybook_dir: Path) -> None:
        result = find_copybook("MYBOOK.cpy", [copybook_dir])
        assert result is not None

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        result = find_copybook("NOEXIST", [tmp_path])
        assert result is None

    def test_skips_nonexistent_directory(self) -> None:
        result = find_copybook("FOO", [Path("/no/such/dir")])
        assert result is None


class TestResolveCopies:
    def test_simple_copy(self, copybook_dir: Path) -> None:
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       COPY MYBOOK.\n"
            "       PROCEDURE DIVISION.\n"
        )
        result = resolve_copies(source, [copybook_dir])
        assert "WS-COPIED-VAR" in result
        assert "COPY MYBOOK" not in result

    def test_copy_with_replacing(self, copybook_dir: Path) -> None:
        source = (
            "       COPY MYBOOK\n"
            "           REPLACING ==WS-COPIED-VAR== BY ==WS-NEW-VAR==.\n"
        )
        result = resolve_copies(source, [copybook_dir])
        assert "WS-NEW-VAR" in result
        assert "WS-COPIED-VAR" not in result

    def test_copy_not_found(self, tmp_path: Path) -> None:
        source = "       COPY MISSING-BOOK.\n"
        result = resolve_copies(source, [tmp_path])
        assert "NOT FOUND" in result
        assert "MISSING-BOOK" in result

    def test_multiple_copies(self, copybook_dir: Path) -> None:
        # Add a second copybook
        (copybook_dir / "OTHERBOOK.cpy").write_text(
            "       01 WS-OTHER  PIC 9(5).\n", encoding="utf-8"
        )
        source = (
            "       COPY MYBOOK.\n"
            "       COPY OTHERBOOK.\n"
        )
        result = resolve_copies(source, [copybook_dir])
        assert "WS-COPIED-VAR" in result
        assert "WS-OTHER" in result

    def test_no_paths_skips_resolution(self) -> None:
        source = "       COPY SOMETHING.\n"
        # No copybook_paths => COPY line preserved, but EXEC stripping runs
        result = resolve_copies(source, None)
        assert "COPY SOMETHING" in result

    def test_quoted_copybook_name(self, copybook_dir: Path) -> None:
        source = "       COPY 'MYBOOK'.\n"
        result = resolve_copies(source, [copybook_dir])
        assert "WS-COPIED-VAR" in result


class TestExecStripping:
    def test_exec_cics_single_line(self) -> None:
        source = "       EXEC CICS READ DATASET('ACCTFILE') END-EXEC\n"
        result = resolve_copies(source)
        assert "TODO(high): EXEC CICS" in result
        assert "Original:" in result
        assert "READ DATASET" in result

    def test_exec_cics_multiline(self) -> None:
        source = (
            "       EXEC CICS\n"
            "           READ DATASET('ACCTFILE')\n"
            "           INTO(WS-RECORD)\n"
            "       END-EXEC\n"
        )
        result = resolve_copies(source)
        assert "TODO(high): EXEC CICS" in result
        assert "READ DATASET" in result

    def test_exec_sql(self) -> None:
        source = "       EXEC SQL SELECT * FROM TABLE END-EXEC\n"
        result = resolve_copies(source)
        assert "TODO(high): EXEC SQL" in result
        assert "SELECT * FROM TABLE" in result

    def test_non_exec_lines_preserved(self) -> None:
        source = (
            "       MOVE 1 TO WS-VAR.\n"
            "       EXEC CICS RETURN END-EXEC\n"
            "       DISPLAY WS-VAR.\n"
        )
        result = resolve_copies(source)
        assert "MOVE 1 TO WS-VAR" in result
        assert "DISPLAY WS-VAR" in result
        assert "TODO(high): EXEC CICS" in result
