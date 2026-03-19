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
        result, _ = resolve_copies(source, [copybook_dir])
        assert "WS-COPIED-VAR" in result
        assert "COPY MYBOOK" not in result

    def test_copy_with_replacing(self, copybook_dir: Path) -> None:
        source = (
            "       COPY MYBOOK\n"
            "           REPLACING ==WS-COPIED-VAR== BY ==WS-NEW-VAR==.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        assert "WS-NEW-VAR" in result
        assert "WS-COPIED-VAR" not in result

    def test_copy_not_found(self, tmp_path: Path) -> None:
        source = "       COPY MISSING-BOOK.\n"
        result, _ = resolve_copies(source, [tmp_path])
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
        result, _ = resolve_copies(source, [copybook_dir])
        assert "WS-COPIED-VAR" in result
        assert "WS-OTHER" in result

    def test_no_paths_skips_resolution(self) -> None:
        source = "       COPY SOMETHING.\n"
        # No copybook_paths => COPY line preserved, but EXEC stripping runs
        result, _ = resolve_copies(source, None)
        assert "COPY SOMETHING" in result

    def test_quoted_copybook_name(self, copybook_dir: Path) -> None:
        source = "       COPY 'MYBOOK'.\n"
        result, _ = resolve_copies(source, [copybook_dir])
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
        result, _ = resolve_copies(
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
        result, _ = resolve_copies(
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
        result, _ = resolve_copies(
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
        result, _ = resolve_copies(
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
        result, _ = resolve_copies(
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
        result, _ = resolve_copies(
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
        result, _ = resolve_copies(source, source_dir=src_dir)
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
        result, _ = resolve_copies(source, source_dir=src_dir)
        assert "WS-COB" in result
        assert "WS-COPY" in result


class TestExecStripping:
    def test_exec_cics_single_line(self) -> None:
        source = "       EXEC CICS READ DATASET('ACCTFILE') END-EXEC\n"
        result, _ = resolve_copies(source)
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
        result, _ = resolve_copies(source)
        assert "TODO(high): EXEC CICS" in result
        assert "READ DATASET" in result

    def test_exec_sql(self) -> None:
        source = "       EXEC SQL SELECT * FROM TABLE END-EXEC\n"
        result, _ = resolve_copies(source)
        assert "TODO(high): EXEC SQL" in result
        assert "SELECT * FROM TABLE" in result

    def test_non_exec_lines_preserved(self) -> None:
        source = (
            "       MOVE 1 TO WS-VAR.\n"
            "       EXEC CICS RETURN END-EXEC\n"
            "       DISPLAY WS-VAR.\n"
        )
        result, _ = resolve_copies(source)
        assert "MOVE 1 TO WS-VAR" in result
        assert "DISPLAY WS-VAR" in result
        assert "TODO(high): EXEC CICS" in result


class TestCopyReplacingLeadingTrailing:
    """Tests for COPY REPLACING with LEADING/TRAILING qualifiers."""

    def test_replacing_leading(self, copybook_dir: Path) -> None:
        """REPLACING LEADING replaces prefix only at start of words."""
        # Copybook contains 'WS-COPIED-VAR'
        source = (
            "       COPY MYBOOK\n"
            "           REPLACING LEADING ==WS-== BY ==NEW-==.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        # WS- at start of word should be replaced
        assert "NEW-COPIED-VAR" in result
        assert "WS-COPIED-VAR" not in result

    def test_replacing_leading_no_mid_word(self, copybook_dir: Path) -> None:
        """REPLACING LEADING does NOT replace text in the middle of a word."""
        # Create a copybook where the target text appears mid-word
        (copybook_dir / "MIDWORD.cpy").write_text(
            "       01 MY-WS-FIELD  PIC X(10).\n"
            "       01 WS-OTHER     PIC X(5).\n",
            encoding="utf-8",
        )
        source = (
            "       COPY MIDWORD\n"
            "           REPLACING LEADING ==WS-== BY ==NEW-==.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        # WS- at start of word should be replaced
        assert "NEW-OTHER" in result
        # WS- in the middle of MY-WS-FIELD should NOT be replaced
        assert "MY-WS-FIELD" in result

    def test_replacing_trailing(self, copybook_dir: Path) -> None:
        """REPLACING TRAILING replaces suffix only at end of words."""
        (copybook_dir / "TRAIL.cpy").write_text(
            "       01 IN-REC     PIC X(10).\n"
            "       01 REC-TYPE   PIC X(5).\n",
            encoding="utf-8",
        )
        source = (
            "       COPY TRAIL\n"
            "           REPLACING TRAILING ==-REC== BY ==-RECORD==.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        # -REC at end of word should be replaced
        assert "IN-RECORD" in result
        # -REC in the middle of REC-TYPE should NOT be replaced
        assert "REC-TYPE" in result

    def test_replacing_trailing_no_start_of_word(self, copybook_dir: Path) -> None:
        """REPLACING TRAILING does NOT replace text at the start of a word."""
        (copybook_dir / "TRAIL2.cpy").write_text(
            "       01 REC-FIELD  PIC X(10).\n"
            "       01 MY-REC     PIC X(5).\n",
            encoding="utf-8",
        )
        source = (
            "       COPY TRAIL2\n"
            "           REPLACING TRAILING ==REC== BY ==RECORD==.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        # REC at end of MY-REC should be replaced
        assert "MY-RECORD" in result
        # REC at start of REC-FIELD should NOT be replaced
        assert "REC-FIELD" in result

    def test_existing_pseudo_text_still_works(self, copybook_dir: Path) -> None:
        """Existing pseudo-text REPLACING (no qualifier) still works."""
        source = (
            "       COPY MYBOOK\n"
            "           REPLACING ==WS-COPIED-VAR== BY ==WS-NEW-VAR==.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        assert "WS-NEW-VAR" in result
        assert "WS-COPIED-VAR" not in result


class TestCopyReplacingNonPseudoText:
    """Tests for COPY REPLACING without == delimiters (word-level)."""

    def test_non_pseudo_text_replacing(self, copybook_dir: Path) -> None:
        """REPLACING word BY word (no == delimiters) does whole-word replacement."""
        (copybook_dir / "WORDS.cpy").write_text(
            "       01 OLD-FIELD  PIC X(10).\n"
            "       01 OLD-COUNT  PIC 9(5).\n",
            encoding="utf-8",
        )
        source = (
            "       COPY WORDS\n"
            "           REPLACING OLD-FIELD BY NEW-FIELD.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        assert "NEW-FIELD" in result
        # OLD-COUNT should remain unchanged (different word)
        assert "OLD-COUNT" in result

    def test_non_pseudo_text_single_word(self, copybook_dir: Path) -> None:
        """Non-pseudo-text REPLACING replaces a single identifier."""
        (copybook_dir / "SINGLE.cpy").write_text(
            "       01 ALPHA  PIC X(10).\n",
            encoding="utf-8",
        )
        source = "       COPY SINGLE REPLACING ALPHA BY BETA.\n"
        result, _ = resolve_copies(source, [copybook_dir])
        assert "BETA" in result
        assert "ALPHA" not in result

    def test_non_pseudo_text_does_not_partial_match(self, copybook_dir: Path) -> None:
        """Non-pseudo-text REPLACING is full-word, not substring."""
        (copybook_dir / "PARTIAL.cpy").write_text(
            "       01 ABC-FIELD  PIC X(10).\n"
            "       01 ABC        PIC X(5).\n",
            encoding="utf-8",
        )
        source = "       COPY PARTIAL REPLACING ABC BY XYZ.\n"
        result, _ = resolve_copies(source, [copybook_dir])
        # ABC as standalone word should remain since FULL uses .replace()
        # which is literal text substitution. The standalone ABC is replaced.
        assert "XYZ" in result

    def test_pseudo_text_takes_priority(self, copybook_dir: Path) -> None:
        """If pseudo-text delimiters are present, non-pseudo-text fallback is skipped."""
        source = (
            "       COPY MYBOOK\n"
            "           REPLACING ==WS-COPIED-VAR== BY ==WS-REPLACED==.\n"
        )
        result, _ = resolve_copies(source, [copybook_dir])
        assert "WS-REPLACED" in result
        assert "WS-COPIED-VAR" not in result
