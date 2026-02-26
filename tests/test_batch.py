"""Tests for batch/directory processing."""

import ast
from pathlib import Path

import pytest

from cobol_safe_translator.batch import discover_cobol_files, run_batch, COBOL_EXTENSIONS
from cobol_safe_translator.cli import main


class TestDiscoverCobolFiles:
    def test_finds_cob_extension(self, tmp_path):
        (tmp_path / "prog.cob").write_text("IDENTIFICATION DIVISION.")
        files = discover_cobol_files(tmp_path)
        assert any(f.name == "prog.cob" for f in files)

    def test_finds_cbl_extension(self, tmp_path):
        (tmp_path / "prog.cbl").write_text("IDENTIFICATION DIVISION.")
        files = discover_cobol_files(tmp_path)
        assert any(f.name == "prog.cbl" for f in files)

    def test_finds_cobol_extension(self, tmp_path):
        (tmp_path / "prog.cobol").write_text("IDENTIFICATION DIVISION.")
        files = discover_cobol_files(tmp_path)
        assert any(f.name == "prog.cobol" for f in files)

    def test_excludes_cpy_copybooks(self, tmp_path):
        (tmp_path / "copy.cpy").write_text("01 WS-A PIC X.")
        files = discover_cobol_files(tmp_path)
        assert not any(f.suffix == ".cpy" for f in files)

    def test_excludes_py_files(self, tmp_path):
        (tmp_path / "script.py").write_text("print('hello')")
        files = discover_cobol_files(tmp_path)
        assert not any(f.suffix == ".py" for f in files)

    def test_empty_directory_returns_empty_list(self, tmp_path):
        files = discover_cobol_files(tmp_path)
        assert files == []

    def test_non_recursive_does_not_descend(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "nested.cob").write_text("IDENTIFICATION DIVISION.")
        files = discover_cobol_files(tmp_path, recursive=False)
        assert not any(f.name == "nested.cob" for f in files)

    def test_recursive_finds_nested_files(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "nested.cob").write_text("IDENTIFICATION DIVISION.")
        files = discover_cobol_files(tmp_path, recursive=True)
        assert any(f.name == "nested.cob" for f in files)

    def test_results_sorted(self, tmp_path):
        for name in ["zzz.cob", "aaa.cob", "mmm.cob"]:
            (tmp_path / name).write_text("IDENTIFICATION DIVISION.")
        files = discover_cobol_files(tmp_path)
        names = [f.name for f in files]
        assert names == sorted(names)


class TestRunBatch:
    def test_empty_directory_returns_1(self, tmp_path):
        rc = run_batch(tmp_path, tmp_path / "out", False, lambda s, o: 0)
        assert rc == 1

    def test_successful_batch_returns_0(self, tmp_path):
        (tmp_path / "a.cob").write_text("x")
        (tmp_path / "b.cob").write_text("x")
        calls = []

        def process(src, out):
            calls.append(src.name)
            return 0

        rc = run_batch(tmp_path, tmp_path / "out", False, process)
        assert rc == 0
        assert len(calls) == 2

    def test_partial_failure_returns_1(self, tmp_path):
        (tmp_path / "ok.cob").write_text("x")
        (tmp_path / "fail.cob").write_text("x")

        def process(src, out):
            return 1 if src.name == "fail.cob" else 0

        rc = run_batch(tmp_path, tmp_path / "out", False, process)
        assert rc == 1

    def test_output_subdir_per_file(self, tmp_path):
        (tmp_path / "prog.cob").write_text("x")
        seen_dirs = []

        def process(src, out):
            seen_dirs.append(out)
            return 0

        run_batch(tmp_path, tmp_path / "out", False, process)
        assert seen_dirs[0].name == "prog"


class TestBatchCLI:
    def test_translate_directory(self, samples_dir, tmp_path):
        out_dir = tmp_path / "out"
        result = main(["translate", str(samples_dir), "--output", str(out_dir)])
        assert result == 0
        # At least one subdirectory with a .py file should exist
        py_files = list(out_dir.rglob("*.py"))
        assert len(py_files) > 0

    def test_map_directory(self, samples_dir, tmp_path):
        out_dir = tmp_path / "out"
        result = main(["map", str(samples_dir), "--output", str(out_dir)])
        assert result == 0
        md_files = list(out_dir.rglob("software-map.md"))
        assert len(md_files) > 0

    def test_prompt_directory(self, samples_dir, tmp_path):
        out_dir = tmp_path / "out"
        result = main(["prompt", str(samples_dir), "--output", str(out_dir)])
        assert result == 0
        brief_files = list(out_dir.rglob("*_brief.md"))
        assert len(brief_files) > 0

    def test_translate_empty_directory_returns_1(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = main(["translate", str(empty), "--output", str(tmp_path / "out")])
        assert result == 1

    def test_recursive_flag(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        # Copy a minimal COBOL file into the subdir
        (subdir / "minimal.cob").write_text(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MINIMAL.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           STOP RUN.\n"
        )
        out_dir = tmp_path / "out"
        result = main(["translate", str(tmp_path), "--output", str(out_dir), "--recursive"])
        assert result == 0
        py_files = list(out_dir.rglob("*.py"))
        assert len(py_files) > 0

    def test_translate_directory_produces_valid_python(self, samples_dir, tmp_path):
        out_dir = tmp_path / "out"
        result = main(["translate", str(samples_dir), "--output", str(out_dir)])
        assert result == 0
        for py_file in out_dir.rglob("*.py"):
            source = py_file.read_text()
            ast.parse(source)  # must be valid Python


class TestRunBatchExceptionHandling:
    def test_exception_in_process_fn_continues_batch(self, tmp_path):
        """run_batch must continue processing even if process_fn raises."""
        (tmp_path / "a.cob").write_text("IDENTIFICATION DIVISION.")
        (tmp_path / "b.cob").write_text("IDENTIFICATION DIVISION.")

        calls = []
        def process_fn(src, out_dir):
            calls.append(src.name)
            if src.name == "a.cob":
                raise RuntimeError("simulated crash")
            return 0

        rc = run_batch(tmp_path, tmp_path / "out", False, process_fn, print)
        assert rc == 1  # one failure → non-zero
        assert "a.cob" in calls
        assert "b.cob" in calls  # b.cob must still be processed despite a.cob crash
