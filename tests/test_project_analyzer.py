"""Tests for cross-program CALL graph analysis and package generation."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from cobol_safe_translator.models import ProjectMap
from cobol_safe_translator.project_analyzer import analyze_project, generate_package


# -- Fixtures --

PROG_A_SRC = textwrap.dedent("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG-A.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RESULT PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "PROGRAM A".
           CALL "PROG-B" USING WS-RESULT.
           STOP RUN.
""")

PROG_B_SRC = textwrap.dedent("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG-B.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-INPUT PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "PROGRAM B".
           STOP RUN.
""")

PROG_C_SRC = textwrap.dedent("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG-C.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATA PIC X(10) VALUE SPACES.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "PROGRAM C".
           CALL "PROG-B".
           CALL "EXTERNAL-LIB".
           STOP RUN.
""")


@pytest.fixture
def cobol_project(tmp_path: Path) -> Path:
    """Create a temp directory with 3 COBOL files: A calls B, C calls B + external."""
    (tmp_path / "prog_a.cob").write_text(PROG_A_SRC, encoding="utf-8")
    (tmp_path / "prog_b.cob").write_text(PROG_B_SRC, encoding="utf-8")
    (tmp_path / "prog_c.cob").write_text(PROG_C_SRC, encoding="utf-8")
    return tmp_path


@pytest.fixture
def two_program_project(tmp_path: Path) -> Path:
    """Create a temp directory with 2 COBOL files: A calls B."""
    (tmp_path / "prog_a.cob").write_text(PROG_A_SRC, encoding="utf-8")
    (tmp_path / "prog_b.cob").write_text(PROG_B_SRC, encoding="utf-8")
    return tmp_path


# -- analyze_project tests --

class TestAnalyzeProject:
    """Tests for analyze_project()."""

    def test_discovers_all_programs(self, cobol_project: Path) -> None:
        pmap = analyze_project(cobol_project)
        assert len(pmap.programs) == 3
        assert "PROG-A" in pmap.programs
        assert "PROG-B" in pmap.programs
        assert "PROG-C" in pmap.programs

    def test_call_graph_edges(self, cobol_project: Path) -> None:
        pmap = analyze_project(cobol_project)
        # A calls B
        assert "PROG-A" in pmap.call_graph
        assert "PROG-B" in pmap.call_graph["PROG-A"]
        # C calls B
        assert "PROG-C" in pmap.call_graph
        assert "PROG-B" in pmap.call_graph["PROG-C"]

    def test_entry_points(self, cobol_project: Path) -> None:
        pmap = analyze_project(cobol_project)
        # B is called by A and C, so it is NOT an entry point
        assert "PROG-B" not in pmap.entry_points
        # A and C are not called by anyone
        assert "PROG-A" in pmap.entry_points
        assert "PROG-C" in pmap.entry_points

    def test_unresolved_calls(self, cobol_project: Path) -> None:
        pmap = analyze_project(cobol_project)
        # C calls EXTERNAL-LIB which is not in the project
        assert "PROG-C" in pmap.unresolved_calls
        assert "EXTERNAL-LIB" in pmap.unresolved_calls["PROG-C"]

    def test_standalone_program_is_entry_point(self, two_program_project: Path) -> None:
        pmap = analyze_project(two_program_project)
        assert "PROG-A" in pmap.entry_points
        # B is called by A, so not an entry point
        assert "PROG-B" not in pmap.entry_points

    def test_empty_directory(self, tmp_path: Path) -> None:
        pmap = analyze_project(tmp_path)
        assert len(pmap.programs) == 0
        assert pmap.entry_points == []
        assert pmap.call_graph == {}

    def test_returns_project_map_type(self, cobol_project: Path) -> None:
        pmap = analyze_project(cobol_project)
        assert isinstance(pmap, ProjectMap)


# -- generate_package tests --

class TestGeneratePackage:
    """Tests for generate_package()."""

    def test_creates_package_structure(self, cobol_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(cobol_project)
        out = tmp_path / "output"
        files = generate_package(pmap, out)

        pkg_dir = out / "cobol_project"
        assert pkg_dir.is_dir()
        assert (pkg_dir / "__init__.py").exists()
        assert (pkg_dir / "CALL_GRAPH.txt").exists()

    def test_generates_module_per_program(self, cobol_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(cobol_project)
        out = tmp_path / "output"
        files = generate_package(pmap, out)

        pkg_dir = out / "cobol_project"
        # Each program gets a .py file
        py_files = sorted(f.name for f in pkg_dir.glob("*.py") if f.name != "__init__.py")
        assert "prog_a.py" in py_files
        assert "prog_b.py" in py_files
        assert "prog_c.py" in py_files

    def test_init_imports_entry_points(self, cobol_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(cobol_project)
        out = tmp_path / "output"
        generate_package(pmap, out)

        init_content = (out / "cobol_project" / "__init__.py").read_text()
        # Entry points (A and C) should be imported
        assert "ProgaProgram" in init_content or "ProgAProgram" in init_content
        assert "ProgcProgram" in init_content or "ProgCProgram" in init_content

    def test_generated_python_is_valid_syntax(self, cobol_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(cobol_project)
        out = tmp_path / "output"
        files = generate_package(pmap, out)

        for f in files:
            if f.suffix == ".py":
                source = f.read_text(encoding="utf-8")
                # Must parse without SyntaxError
                ast.parse(source, filename=str(f))

    def test_call_stubs_replaced_with_imports(self, two_program_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(two_program_project)
        out = tmp_path / "output"
        generate_package(pmap, out)

        prog_a_source = (out / "cobol_project" / "prog_a.py").read_text()
        # The CALL stub for PROG-B should be replaced with an import
        assert "from .prog_b import" in prog_a_source
        # The original TODO stub should no longer be there
        assert "implement or import prog_b" not in prog_a_source

    def test_call_graph_report_content(self, cobol_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(cobol_project)
        out = tmp_path / "output"
        generate_package(pmap, out)

        report = (out / "cobol_project" / "CALL_GRAPH.txt").read_text()
        assert "3 programs" in report
        assert "PROG-A" in report
        assert "PROG-B" in report
        assert "EXTERNAL-LIB" in report
        assert "NOT FOUND" in report

    def test_custom_package_name(self, two_program_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(two_program_project)
        out = tmp_path / "output"
        files = generate_package(pmap, out, package_name="my_cobol_app")

        assert (out / "my_cobol_app" / "__init__.py").exists()
        assert (out / "my_cobol_app" / "prog_a.py").exists()

    def test_file_count_matches(self, cobol_project: Path, tmp_path: Path) -> None:
        pmap = analyze_project(cobol_project)
        out = tmp_path / "output"
        files = generate_package(pmap, out)

        # 3 program modules + __init__.py + CALL_GRAPH.txt = 5
        assert len(files) == 5

    def test_standalone_program_no_call_graph(self, tmp_path: Path) -> None:
        """A single program with no CALLs should produce a valid package."""
        (tmp_path / "solo.cob").write_text(PROG_B_SRC, encoding="utf-8")
        pmap = analyze_project(tmp_path)
        out = tmp_path / "output"
        files = generate_package(pmap, out)

        assert len(files) == 3  # 1 module + __init__.py + CALL_GRAPH.txt
        # The single program is an entry point
        assert len(pmap.entry_points) == 1
        assert pmap.call_graph == {}
