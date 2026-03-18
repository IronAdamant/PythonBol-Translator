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


class TestCopyPaths:
    """Tests for user-specified copybook search paths (copy_paths)."""

    def test_copybook_found_via_copy_paths(self, tmp_path: Path) -> None:
        """Copybooks in a separate directory are found when copy_paths is specified."""
        # Source file directory (no copybooks here)
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        # Separate copybook directory
        cpy_dir = tmp_path / "copybooks"
        cpy_dir.mkdir()
        (cpy_dir / "SHARED.cpy").write_text(
            "       01 WS-SHARED  PIC X(20).\n", encoding="utf-8"
        )

        source = "       COPY SHARED.\n"
        result = resolve_copies(
            source, source_dir=src_dir, copy_paths=[cpy_dir]
        )
        assert "WS-SHARED" in result
        assert "COPY SHARED" not in result

    def test_source_dir_searched_first(self, tmp_path: Path) -> None:
        """Source file's directory is searched before copy_paths."""
        # Both directories have a copybook with the same name but different content
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "DUPE.cpy").write_text(
            "       01 WS-FROM-SRC  PIC X(5).\n", encoding="utf-8"
        )

        cpy_dir = tmp_path / "copybooks"
        cpy_dir.mkdir()
        (cpy_dir / "DUPE.cpy").write_text(
            "       01 WS-FROM-CPY  PIC X(5).\n", encoding="utf-8"
        )

        source = "       COPY DUPE.\n"
        result = resolve_copies(
            source, source_dir=src_dir, copy_paths=[cpy_dir]
        )
        # Source dir wins — its copybook is used
        assert "WS-FROM-SRC" in result
        assert "WS-FROM-CPY" not in result

    def test_missing_copybook_graceful_fallback(self, tmp_path: Path) -> None:
        """Missing copybooks produce a NOT FOUND comment, no crash."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        cpy_dir = tmp_path / "copybooks"
        cpy_dir.mkdir()

        source = "       COPY NONEXISTENT.\n"
        result = resolve_copies(
            source, source_dir=src_dir, copy_paths=[cpy_dir]
        )
        assert "NOT FOUND" in result
        assert "NONEXISTENT" in result

    def test_multiple_copy_paths(self, tmp_path: Path) -> None:
        """Multiple copy_paths are searched in order."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        dir_a = tmp_path / "lib_a"
        dir_a.mkdir()
        (dir_a / "BOOK-A.cpy").write_text(
            "       01 WS-A  PIC X(3).\n", encoding="utf-8"
        )

        dir_b = tmp_path / "lib_b"
        dir_b.mkdir()
        (dir_b / "BOOK-B.cpy").write_text(
            "       01 WS-B  PIC 9(4).\n", encoding="utf-8"
        )

        source = (
            "       COPY BOOK-A.\n"
            "       COPY BOOK-B.\n"
        )
        result = resolve_copies(
            source, source_dir=src_dir, copy_paths=[dir_a, dir_b]
        )
        assert "WS-A" in result
        assert "WS-B" in result

    def test_copy_paths_order_among_themselves(self, tmp_path: Path) -> None:
        """Earlier copy_paths directories take priority over later ones."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        dir_first = tmp_path / "first"
        dir_first.mkdir()
        (dir_first / "PRIO.cpy").write_text(
            "       01 WS-FIRST  PIC X(1).\n", encoding="utf-8"
        )

        dir_second = tmp_path / "second"
        dir_second.mkdir()
        (dir_second / "PRIO.cpy").write_text(
            "       01 WS-SECOND  PIC X(1).\n", encoding="utf-8"
        )

        source = "       COPY PRIO.\n"
        result = resolve_copies(
            source, source_dir=src_dir, copy_paths=[dir_first, dir_second]
        )
        assert "WS-FIRST" in result
        assert "WS-SECOND" not in result

    def test_subdirectories_searched_after_copy_paths(self, tmp_path: Path) -> None:
        """Subdirectories of source_dir are searched after copy_paths."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        # Copybook in a subdirectory of source
        sub = src_dir / "sub"
        sub.mkdir()
        (sub / "SUBBOOK.cpy").write_text(
            "       01 WS-SUB  PIC X(2).\n", encoding="utf-8"
        )

        # Also put a different version in copy_paths
        cpy_dir = tmp_path / "copybooks"
        cpy_dir.mkdir()
        (cpy_dir / "SUBBOOK.cpy").write_text(
            "       01 WS-CPY  PIC X(2).\n", encoding="utf-8"
        )

        source = "       COPY SUBBOOK.\n"
        result = resolve_copies(
            source, source_dir=src_dir, copy_paths=[cpy_dir]
        )
        # copy_paths wins over subdirectory
        assert "WS-CPY" in result
        assert "WS-SUB" not in result

    def test_subdirectories_found_without_copy_paths(self, tmp_path: Path) -> None:
        """Subdirectories of source_dir are searched even without copy_paths."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        sub = src_dir / "includes"
        sub.mkdir()
        (sub / "INCL.cpy").write_text(
            "       01 WS-INCL  PIC X(8).\n", encoding="utf-8"
        )

        source = "       COPY INCL.\n"
        result = resolve_copies(source, source_dir=src_dir)
        assert "WS-INCL" in result

    def test_additional_extensions_found(self, tmp_path: Path) -> None:
        """Copybooks with .cob, .cobol, and .copy extensions are found."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "COBBOOK.cob").write_text(
            "       01 WS-COB  PIC X(3).\n", encoding="utf-8"
        )
        (src_dir / "COPYEXT.copy").write_text(
            "       01 WS-COPY  PIC X(3).\n", encoding="utf-8"
        )

        source = (
            "       COPY COBBOOK.\n"
            "       COPY COPYEXT.\n"
        )
        result = resolve_copies(source, source_dir=src_dir)
        assert "WS-COB" in result
        assert "WS-COPY" in result


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
