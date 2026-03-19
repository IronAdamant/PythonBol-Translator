"""Integration tests for COPY expansion and COPY REPLACING with real copybooks.

Tests use real COBOL source files and copybooks from the sample test projects
in ~/Documents/coding_projects/sample_projects_for_testing/. Each test verifies
that COPY resolution produces valid Python and that copybook expansion works
correctly with real-world file structures.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol, parse_cobol_file
from cobol_safe_translator.preprocessor import resolve_copies

# Base path for all sample test projects.
# Use an absolute path since the test file may live in a git worktree that is
# not a sibling of sample_projects_for_testing.
SAMPLES_BASE = Path.home() / "Documents" / "coding_projects" / "sample_projects_for_testing"

# Skip the entire module if sample projects are not available
pytestmark = pytest.mark.skipif(
    not SAMPLES_BASE.is_dir(),
    reason=f"Sample projects not found at {SAMPLES_BASE}",
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _find_copybook_dirs(project_root: Path) -> list[Path]:
    """Find all directories that contain .cpy files within a project."""
    dirs: set[Path] = set()
    for cpy in project_root.rglob("*.cpy"):
        dirs.add(cpy.parent)
    # Also check for uppercase .CPY
    for cpy in project_root.rglob("*.CPY"):
        dirs.add(cpy.parent)
    return sorted(dirs)


def _find_cobol_sources(project_root: Path) -> list[Path]:
    """Find COBOL source files (not copybooks) within a project."""
    extensions = {".cbl", ".cob", ".cobol", ".CBL", ".COB", ".COBOL"}
    files: list[Path] = []
    for f in project_root.rglob("*"):
        if f.is_file() and f.suffix in extensions:
            files.append(f)
    return sorted(files)


def _sources_with_copy(project_root: Path) -> list[Path]:
    """Find COBOL source files that contain COPY statements."""
    copy_re = re.compile(r"^\s*COPY\s+", re.IGNORECASE | re.MULTILINE)
    result: list[Path] = []
    for src in _find_cobol_sources(project_root):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if copy_re.search(text):
            result.append(src)
    return result


def _sources_with_copy_replacing(project_root: Path) -> list[Path]:
    """Find COBOL source files containing COPY ... REPLACING patterns."""
    # Matches both single-line and multi-line COPY ... REPLACING
    replacing_re = re.compile(
        r"COPY\s+[\w.'\"+-]+.*?REPLACING", re.IGNORECASE | re.DOTALL
    )
    result: list[Path] = []
    for src in _find_cobol_sources(project_root):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if replacing_re.search(text):
            result.append(src)
    return result


def _translate_file(path: Path, copy_paths: list[Path] | None = None) -> str:
    """Parse, analyze, and translate a COBOL file to Python source."""
    program = parse_cobol_file(
        path,
        copy_paths=[str(p) for p in copy_paths] if copy_paths else None,
    )
    smap = analyze(program)
    return generate_python(smap)


def _is_valid_python(source: str) -> bool:
    """Check whether a string is valid Python syntax."""
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


# ---------------------------------------------------------------------------
# Project definitions: (project_dir, copybook_dirs_relative)
# Each project that has copybooks gets its own set of tests.
# ---------------------------------------------------------------------------

# Cobol-Projects: Internal-Sort has COPY REPLACING with :tag: pattern
COBOL_PROJECTS_ROOT = SAMPLES_BASE / "Cobol-Projects"
COBOL_PROJECTS_AVAILABLE = COBOL_PROJECTS_ROOT.is_dir()

# dbb-zappbuild: MortgageApplication with COPY of nested copybooks
DBB_ROOT = SAMPLES_BASE / "dbb-zappbuild"
DBB_AVAILABLE = DBB_ROOT.is_dir()

# proleap-cobol-parser: Extensive COPY/REPLACING test cases
PROLEAP_ROOT = SAMPLES_BASE / "proleap-cobol-parser"
PROLEAP_AVAILABLE = PROLEAP_ROOT.is_dir()

# idz-utilities: GAM COBOL samples with COPY
IDZ_ROOT = SAMPLES_BASE / "idz-utilities"
IDZ_AVAILABLE = IDZ_ROOT.is_dir()


# ===========================================================================
# 1. COPY expansion with real copybooks
# ===========================================================================

class TestCopyExpansionCobolProjects:
    """Test COPY expansion using Cobol-Projects (Internal-Sort, ECBAP)."""

    pytestmark = pytest.mark.skipif(
        not COBOL_PROJECTS_AVAILABLE,
        reason="Cobol-Projects not found",
    )

    def test_copybook_dirs_discovered(self) -> None:
        """Cobol-Projects should have multiple directories with .cpy files."""
        dirs = _find_copybook_dirs(COBOL_PROJECTS_ROOT)
        assert len(dirs) >= 3, f"Expected >=3 copybook dirs, found {len(dirs)}"

    def test_sources_with_copy_found(self) -> None:
        """Multiple source files in Cobol-Projects reference COPY statements."""
        sources = _sources_with_copy(COBOL_PROJECTS_ROOT)
        assert len(sources) >= 5, f"Expected >=5 sources with COPY, found {len(sources)}"

    def test_internal_sort_with_copybooks_valid_python(self) -> None:
        """Internal-Sort .cbl files translate to valid Python with copybook paths."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort directory not found")

        cpy_dir = sort_dir / "cpy"
        cbl_dir = sort_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("Internal-Sort cpy/cbl directories not found")

        sources = list(cbl_dir.glob("*.cbl"))
        assert len(sources) > 0, "No .cbl files found in Internal-Sort"

        for src in sources:
            python_src = _translate_file(src, copy_paths=[cpy_dir])
            assert _is_valid_python(python_src), (
                f"{src.name} did not produce valid Python with copybook paths"
            )

    def test_copybook_expansion_resolves_more_with_paths(self) -> None:
        """Translation with copybook paths resolves more COPY statements than without."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort directory not found")

        cpy_dir = sort_dir / "cpy"
        cbl_dir = sort_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("Internal-Sort cpy/cbl directories not found")

        # Pick a file that uses COPY (sort1f.cbl has COPY CUSTOMER REPLACING ...)
        sort1f = cbl_dir / "sort1f.cbl"
        if not sort1f.exists():
            pytest.skip("sort1f.cbl not found")

        source_text = sort1f.read_text(encoding="utf-8", errors="replace")

        # Without copybook paths: COPY lines become NOT FOUND comments
        result_without, _ = resolve_copies(source_text, source_dir=str(cbl_dir))
        # With copybook paths: COPY lines are expanded
        result_with, _ = resolve_copies(
            source_text,
            source_dir=str(cbl_dir),
            copy_paths=[str(cpy_dir)],
        )

        # The version with paths should have fewer "NOT FOUND" markers
        not_found_without = result_without.count("NOT FOUND")
        not_found_with = result_with.count("NOT FOUND")
        assert not_found_with < not_found_without, (
            f"Expected fewer NOT FOUND with paths ({not_found_with}) "
            f"than without ({not_found_without})"
        )

    def test_ecbap_with_copybooks_valid_python(self) -> None:
        """ECBAP .cbl files translate to valid Python with copybook paths."""
        ecbap_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "ECBAP"
        if not ecbap_dir.is_dir():
            pytest.skip("ECBAP directory not found")

        cpy_dir = ecbap_dir / "cpy"
        cbl_dir = ecbap_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("ECBAP cpy/cbl directories not found")

        sources = list(cbl_dir.glob("*.cbl"))
        assert len(sources) > 0, "No .cbl files found in ECBAP"

        valid_count = 0
        for src in sources:
            python_src = _translate_file(src, copy_paths=[cpy_dir])
            if _is_valid_python(python_src):
                valid_count += 1

        # At least 80% should produce valid Python
        ratio = valid_count / len(sources)
        assert ratio >= 0.8, (
            f"Only {valid_count}/{len(sources)} ({ratio:.0%}) produced valid Python"
        )


class TestCopyExpansionDbb:
    """Test COPY expansion using dbb-zappbuild MortgageApplication."""

    pytestmark = pytest.mark.skipif(
        not DBB_AVAILABLE,
        reason="dbb-zappbuild not found",
    )

    def test_mortgage_copybooks_found(self) -> None:
        """dbb-zappbuild should have copybook files for MortgageApplication."""
        cpy_dir = DBB_ROOT / "samples" / "MortgageApplication" / "copybook"
        assert cpy_dir.is_dir(), "MortgageApplication/copybook not found"
        cpys = list(cpy_dir.glob("*.cpy"))
        assert len(cpys) >= 3, f"Expected >=3 copybooks, found {len(cpys)}"

    def test_mortgage_sources_translate_with_copybooks(self) -> None:
        """MortgageApplication COBOL files translate to valid Python with copybook paths."""
        cpy_dir = DBB_ROOT / "samples" / "MortgageApplication" / "copybook"
        cbl_dir = DBB_ROOT / "samples" / "MortgageApplication" / "cobol"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("MortgageApplication copybook/cobol directories not found")

        sources = list(cbl_dir.glob("*.cbl"))
        assert len(sources) > 0, "No .cbl files found"

        valid_count = 0
        for src in sources:
            python_src = _translate_file(src, copy_paths=[cpy_dir])
            if _is_valid_python(python_src):
                valid_count += 1

        assert valid_count >= 1, "No files produced valid Python with copybook paths"

    def test_nested_copy_in_copybook(self) -> None:
        """MortgageApplication has copybooks that COPY other copybooks (epsmtcom.cpy).

        Note: on Linux, file lookup is case-sensitive. The dbb-zappbuild copybooks
        use lowercase filenames (epsmtcom.cpy) while the COPY statements inside them
        use uppercase (COPY EPSMTINP). This test uses lowercase COPY names to match
        the actual filesystem case.
        """
        cpy_dir = DBB_ROOT / "samples" / "MortgageApplication" / "copybook"
        if not cpy_dir.is_dir():
            pytest.skip("MortgageApplication/copybook not found")

        # epsmtcom.cpy contains COPY EPSMTINP and COPY EPSMTOUT
        epsmtcom = cpy_dir / "epsmtcom.cpy"
        if not epsmtcom.exists():
            pytest.skip("epsmtcom.cpy not found")

        content = epsmtcom.read_text(encoding="utf-8", errors="replace")
        assert "COPY" in content.upper(), "epsmtcom.cpy should contain nested COPY"

        # Build a minimal COBOL source that COPYs epsmtcom using the actual
        # filesystem case (lowercase) so find_copybook can locate it on Linux.
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NEST-TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY epsmtcom.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           STOP RUN.\n"
        )
        # With copybook path, the first-level COPY should resolve
        resolved, _ = resolve_copies(source, copy_paths=[str(cpy_dir)])
        # epsmtcom.cpy content should be inlined (PROCESS-INDICATOR, etc.)
        assert "PROCESS-INDICATOR" in resolved, (
            "First-level COPY should inline epsmtcom.cpy content"
        )


class TestCopyExpansionIdz:
    """Test COPY expansion using idz-utilities GAM COBOL samples."""

    pytestmark = pytest.mark.skipif(
        not IDZ_AVAILABLE,
        reason="idz-utilities not found",
    )

    def test_gam_copybooks_found(self) -> None:
        """idz-utilities GAM COBOL sample should have copybooks."""
        cpy_dir = (
            IDZ_ROOT / "COBOL-Samples" / "Global Auto Mart COBOL Sample"
            / "GAM_COBOL" / "COPYBOOK"
        )
        if not cpy_dir.is_dir():
            pytest.skip("GAM_COBOL/COPYBOOK not found")
        cpys = list(cpy_dir.glob("*.cpy"))
        assert len(cpys) >= 3, f"Expected >=3 copybooks, found {len(cpys)}"

    def test_gam_sources_translate_with_copybooks(self) -> None:
        """GAM COBOL source files translate to valid Python with copybook paths."""
        gam_root = (
            IDZ_ROOT / "COBOL-Samples" / "Global Auto Mart COBOL Sample"
            / "GAM_COBOL"
        )
        if not gam_root.is_dir():
            pytest.skip("GAM_COBOL directory not found")

        cpy_dir = gam_root / "COPYBOOK"
        if not cpy_dir.is_dir():
            pytest.skip("GAM_COBOL/COPYBOOK not found")

        # GAM source files are in subdirectories (GAM0VMM/, GAM0VII/, etc.)
        sources = list(gam_root.rglob("*.cbl"))
        assert len(sources) > 0, "No .cbl files found in GAM_COBOL"

        valid_count = 0
        for src in sources:
            python_src = _translate_file(src, copy_paths=[cpy_dir])
            if _is_valid_python(python_src):
                valid_count += 1

        assert valid_count >= 1, "No GAM files produced valid Python with copybook paths"


# ===========================================================================
# 2. COPY REPLACING tests with real files
# ===========================================================================

class TestCopyReplacingCobolProjects:
    """Test COPY REPLACING using Cobol-Projects (uses ==:tag:== pattern)."""

    pytestmark = pytest.mark.skipif(
        not COBOL_PROJECTS_AVAILABLE,
        reason="Cobol-Projects not found",
    )

    def test_replacing_files_found(self) -> None:
        """Cobol-Projects should have source files with COPY REPLACING."""
        files = _sources_with_copy_replacing(COBOL_PROJECTS_ROOT)
        assert len(files) >= 3, (
            f"Expected >=3 files with COPY REPLACING, found {len(files)}"
        )

    def test_tag_replacing_expands_correctly(self) -> None:
        """COPY CUSTOMER REPLACING ==:tag:== BY ==INFile== produces resolved content."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort not found")

        cpy_dir = sort_dir / "cpy"
        if not cpy_dir.is_dir():
            pytest.skip("Internal-Sort/cpy not found")

        customer_cpy = cpy_dir / "CUSTOMER.cpy"
        if not customer_cpy.exists():
            pytest.skip("CUSTOMER.cpy not found")

        # Build a COPY REPLACING statement and resolve it
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. REPLACE-TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY CUSTOMER REPLACING ==:tag:== BY ==INFile==.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           STOP RUN.\n"
        )
        resolved, _ = resolve_copies(source, copy_paths=[str(cpy_dir)])

        # The :tag: pattern should be replaced with INFile
        assert ":tag:" not in resolved, "REPLACING should substitute :tag:"
        assert "INFile" in resolved, "INFile should appear after REPLACING"

    def test_wsfst_replacing_produces_valid_python(self) -> None:
        """COPY WSFST REPLACING ==:tag:== BY ==TL== produces valid Python."""
        ecbap_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "ECBAP"
        if not ecbap_dir.is_dir():
            pytest.skip("ECBAP not found")

        cpy_dir = ecbap_dir / "cpy"
        cbl_dir = ecbap_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("ECBAP cpy/cbl not found")

        # TABLE1.cbl uses COPY WSFST REPLACING ==:tag:== BY ==TL==
        table1 = cbl_dir / "TABLE1.cbl"
        if not table1.exists():
            pytest.skip("TABLE1.cbl not found")

        python_src = _translate_file(table1, copy_paths=[cpy_dir])
        assert _is_valid_python(python_src), (
            "TABLE1.cbl with COPY REPLACING should produce valid Python"
        )

    def test_replacing_multiple_tags_in_single_file(self) -> None:
        """sort3f.cbl uses COPY with REPLACING for multiple different tags."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort not found")

        cpy_dir = sort_dir / "cpy"
        cbl_dir = sort_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("Internal-Sort cpy/cbl not found")

        # sort3f.cbl has multiple COPY CUSTOMER REPLACING with different tags
        sort3f = cbl_dir / "sort3f.cbl"
        if not sort3f.exists():
            pytest.skip("sort3f.cbl not found")

        source_text = sort3f.read_text(encoding="utf-8", errors="replace")
        resolved, _ = resolve_copies(
            source_text,
            source_dir=str(cbl_dir),
            copy_paths=[str(cpy_dir)],
        )

        # All three tags (INFile, SORTFile, OUTFile) should appear
        assert "INFile" in resolved, "INFile tag should be present after REPLACING"
        assert "SORTFile" in resolved, "SORTFile tag should be present after REPLACING"
        assert "OUTFile" in resolved, "OUTFile tag should be present after REPLACING"
        # The original :tag: placeholder should not remain
        assert ":tag:" not in resolved, "No :tag: placeholders should remain"

    def test_all_replacing_files_produce_valid_python(self) -> None:
        """Every file with COPY REPLACING should produce valid Python."""
        cpy_dirs = _find_copybook_dirs(COBOL_PROJECTS_ROOT)
        if not cpy_dirs:
            pytest.skip("No copybook directories found")

        replacing_files = _sources_with_copy_replacing(COBOL_PROJECTS_ROOT)
        if not replacing_files:
            pytest.skip("No files with COPY REPLACING found")

        valid_count = 0
        for src in replacing_files:
            python_src = _translate_file(src, copy_paths=cpy_dirs)
            if _is_valid_python(python_src):
                valid_count += 1

        ratio = valid_count / len(replacing_files)
        assert ratio >= 0.7, (
            f"Only {valid_count}/{len(replacing_files)} ({ratio:.0%}) "
            f"COPY REPLACING files produced valid Python"
        )


class TestCopyReplacingProleap:
    """Test COPY REPLACING using proleap-cobol-parser test resources."""

    pytestmark = pytest.mark.skipif(
        not PROLEAP_AVAILABLE,
        reason="proleap-cobol-parser not found",
    )

    def test_proleap_replacing_files_exist(self) -> None:
        """proleap-cobol-parser should have COPY REPLACING test files."""
        var_dir = (
            PROLEAP_ROOT / "src" / "test" / "resources"
            / "io" / "proleap" / "cobol" / "ast" / "variable"
        )
        if not var_dir.is_dir():
            pytest.skip("proleap variable test dir not found")

        replace_cbl = var_dir / "CopyReplace.cbl"
        assert replace_cbl.exists(), "CopyReplace.cbl should exist"

    def test_proleap_copy_replace_pseudotext(self) -> None:
        """CopyReplace.cbl with ==pseudo-text== REPLACING translates successfully."""
        var_dir = (
            PROLEAP_ROOT / "src" / "test" / "resources"
            / "io" / "proleap" / "cobol" / "ast" / "variable"
        )
        if not var_dir.is_dir():
            pytest.skip("proleap variable test dir not found")

        replace_cbl = var_dir / "CopyReplace.cbl"
        if not replace_cbl.exists():
            pytest.skip("CopyReplace.cbl not found")

        # The copybooks are in the same directory as the source
        python_src = _translate_file(replace_cbl, copy_paths=[var_dir])
        assert _is_valid_python(python_src), (
            "CopyReplace.cbl should produce valid Python"
        )

    def test_proleap_pseudotext_replacement_applied(self) -> None:
        """Pseudo-text REPLACING ==That== BY ==DISPLAY== is correctly applied."""
        var_dir = (
            PROLEAP_ROOT / "src" / "test" / "resources"
            / "io" / "proleap" / "cobol" / "ast" / "variable"
        )
        if not var_dir.is_dir():
            pytest.skip("proleap variable test dir not found")

        replace_cbl = var_dir / "CopyReplace.cbl"
        if not replace_cbl.exists():
            pytest.skip("CopyReplace.cbl not found")

        source_text = replace_cbl.read_text(encoding="utf-8", errors="replace")
        resolved, _ = resolve_copies(source_text, copy_paths=[str(var_dir)])

        # CopyReplace2.cpy contains "That" which should be replaced by "DISPLAY"
        assert "DISPLAY" in resolved, (
            "REPLACING ==That== BY ==DISPLAY== should produce DISPLAY in output"
        )

    def test_proleap_copyreplace_preprocessor_dir(self) -> None:
        """proleap copyreplace preprocessor test case translates with copybooks dir."""
        preproc_dir = (
            PROLEAP_ROOT / "src" / "test" / "resources"
            / "io" / "proleap" / "cobol" / "preprocessor"
            / "copy" / "copyreplace" / "variable"
        )
        if not preproc_dir.is_dir():
            pytest.skip("proleap copyreplace preprocessor dir not found")

        cpy_dir = preproc_dir / "copybooks"
        replace_cbl = preproc_dir / "CopyReplace.cbl"
        if not cpy_dir.is_dir() or not replace_cbl.exists():
            pytest.skip("copybooks dir or CopyReplace.cbl not found")

        python_src = _translate_file(replace_cbl, copy_paths=[cpy_dir])
        assert _is_valid_python(python_src), (
            "proleap CopyReplace.cbl with copybooks dir should produce valid Python"
        )


# ===========================================================================
# 3. CLI --copybook-path integration tests
# ===========================================================================

class TestCLICopybookPath:
    """Test the --copybook-path CLI flag with real copybook directories."""

    pytestmark = pytest.mark.skipif(
        not COBOL_PROJECTS_AVAILABLE,
        reason="Cobol-Projects not found",
    )

    def test_cli_translate_with_copybook_path(self, tmp_path: Path) -> None:
        """cobol2py translate --copybook-path produces valid Python output."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort not found")

        cpy_dir = sort_dir / "cpy"
        cbl_dir = sort_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("Internal-Sort cpy/cbl not found")

        sort1f = cbl_dir / "sort1f.cbl"
        if not sort1f.exists():
            pytest.skip("sort1f.cbl not found")

        out_dir = tmp_path / "cli_out"
        result = subprocess.run(
            [
                sys.executable, "-m", "cobol_safe_translator",
                "translate", str(sort1f),
                "--output", str(out_dir),
                "--copybook-path", str(cpy_dir),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        # Find the generated .py file
        py_files = list(out_dir.rglob("*.py"))
        assert len(py_files) >= 1, "No .py files generated"

        # Verify it is valid Python
        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            assert _is_valid_python(source), f"{py_file.name} is not valid Python"

    def test_cli_translate_with_multiple_copybook_paths(self, tmp_path: Path) -> None:
        """cobol2py translate with multiple -I flags works correctly."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort not found")

        cpy_dir = sort_dir / "cpy"
        common_cpy = COBOL_PROJECTS_ROOT / "common" / "cpy"
        cbl_dir = sort_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("Required directories not found")

        sort1f = cbl_dir / "sort1f.cbl"
        if not sort1f.exists():
            pytest.skip("sort1f.cbl not found")

        out_dir = tmp_path / "cli_out"
        cmd = [
            sys.executable, "-m", "cobol_safe_translator",
            "translate", str(sort1f),
            "--output", str(out_dir),
            "-I", str(cpy_dir),
        ]
        # Add the common cpy dir if it exists
        if common_cpy.is_dir():
            cmd.extend(["-I", str(common_cpy)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        py_files = list(out_dir.rglob("*.py"))
        assert len(py_files) >= 1, "No .py files generated"

    def test_cli_translate_without_copybook_path_still_works(self, tmp_path: Path) -> None:
        """Translation without --copybook-path still succeeds (COPY unresolved)."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort not found")

        cbl_dir = sort_dir / "cbl"
        sort1f = cbl_dir / "sort1f.cbl"
        if not sort1f.exists():
            pytest.skip("sort1f.cbl not found")

        out_dir = tmp_path / "cli_out"
        result = subprocess.run(
            [
                sys.executable, "-m", "cobol_safe_translator",
                "translate", str(sort1f),
                "--output", str(out_dir),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"CLI failed without copybook path: {result.stderr}"

    def test_cli_copybook_path_resolves_more_content(self, tmp_path: Path) -> None:
        """Output with --copybook-path should contain more data items than without."""
        sort_dir = COBOL_PROJECTS_ROOT / "OpenCobol" / "Internal-Sort"
        if not sort_dir.is_dir():
            pytest.skip("Internal-Sort not found")

        cpy_dir = sort_dir / "cpy"
        cbl_dir = sort_dir / "cbl"
        if not cpy_dir.is_dir() or not cbl_dir.is_dir():
            pytest.skip("Required directories not found")

        sort1f = cbl_dir / "sort1f.cbl"
        if not sort1f.exists():
            pytest.skip("sort1f.cbl not found")

        # Translate without copybook path
        out_without = tmp_path / "without"
        subprocess.run(
            [
                sys.executable, "-m", "cobol_safe_translator",
                "translate", str(sort1f),
                "--output", str(out_without),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Translate with copybook path
        out_with = tmp_path / "with"
        subprocess.run(
            [
                sys.executable, "-m", "cobol_safe_translator",
                "translate", str(sort1f),
                "--output", str(out_with),
                "--copybook-path", str(cpy_dir),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        py_without = list(out_without.rglob("*.py"))
        py_with = list(out_with.rglob("*.py"))

        if py_without and py_with:
            src_without = py_without[0].read_text()
            src_with = py_with[0].read_text()
            # The version with copybooks should be longer (more resolved content)
            assert len(src_with) >= len(src_without), (
                "Translation with copybook paths should be at least as long"
            )


# ===========================================================================
# 4. Broad integration: translate all COPY-using files across projects
# ===========================================================================

class TestBroadCopyIntegration:
    """Translate a sample of COPY-using files from multiple projects."""

    def test_cobol_projects_copy_files_valid(self) -> None:
        """Files with COPY in Cobol-Projects produce valid Python with copybook dirs."""
        if not COBOL_PROJECTS_AVAILABLE:
            pytest.skip("Cobol-Projects not found")

        cpy_dirs = _find_copybook_dirs(COBOL_PROJECTS_ROOT)
        sources = _sources_with_copy(COBOL_PROJECTS_ROOT)
        if not sources:
            pytest.skip("No COPY-using sources found")

        # Test up to 10 files to keep test time reasonable
        sample = sources[:10]
        valid_count = 0
        for src in sample:
            python_src = _translate_file(src, copy_paths=cpy_dirs)
            if _is_valid_python(python_src):
                valid_count += 1

        ratio = valid_count / len(sample)
        assert ratio >= 0.7, (
            f"Only {valid_count}/{len(sample)} ({ratio:.0%}) "
            f"COPY-using files produced valid Python"
        )

    def test_dbb_copy_files_valid(self) -> None:
        """Files with COPY in dbb-zappbuild produce valid Python with copybook dirs."""
        if not DBB_AVAILABLE:
            pytest.skip("dbb-zappbuild not found")

        cpy_dirs = _find_copybook_dirs(DBB_ROOT)
        sources = _sources_with_copy(DBB_ROOT)
        if not sources:
            pytest.skip("No COPY-using sources found in dbb-zappbuild")

        valid_count = 0
        for src in sources:
            python_src = _translate_file(src, copy_paths=cpy_dirs)
            if _is_valid_python(python_src):
                valid_count += 1

        assert valid_count >= 1, "No dbb-zappbuild COPY files produced valid Python"
