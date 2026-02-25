"""End-to-end tests for the CLI."""

import ast
import json
from pathlib import Path

from cobol_safe_translator.cli import main


class TestTranslateCommand:
    def test_translate_hello(self, hello_cob, tmp_path):
        out_dir = tmp_path / "translated"
        result = main(["translate", str(hello_cob), "--output", str(out_dir)])
        assert result == 0

        # Check output file exists
        py_file = out_dir / "hello_world.py"
        assert py_file.exists()

        # Check it's valid Python
        source = py_file.read_text()
        ast.parse(source)

    def test_translate_customer_report(self, customer_report_cob, tmp_path):
        out_dir = tmp_path / "translated"
        result = main(["translate", str(customer_report_cob), "--output", str(out_dir)])
        assert result == 0

        py_file = out_dir / "customer_report.py"
        assert py_file.exists()
        source = py_file.read_text()
        ast.parse(source)

    def test_translate_missing_file(self, tmp_path):
        result = main(["translate", "/nonexistent/file.cob", "--output", str(tmp_path)])
        assert result == 1


class TestMapCommand:
    def test_map_customer_report(self, customer_report_cob, tmp_path):
        out_dir = tmp_path / "report"
        result = main(["map", str(customer_report_cob), "--output", str(out_dir)])
        assert result == 0

        # Check both files exist
        md_file = out_dir / "software-map.md"
        json_file = out_dir / "software-map.json"
        assert md_file.exists()
        assert json_file.exists()

        # Validate markdown content
        md_content = md_file.read_text()
        assert "CUSTOMER-REPORT" in md_content
        assert "mermaid" in md_content
        assert "CUST-SSN" in md_content

        # Validate JSON
        data = json.loads(json_file.read_text())
        assert data["program_id"] == "CUSTOMER-REPORT"
        assert len(data["sensitivities"]) > 0

    def test_map_hello(self, hello_cob, tmp_path):
        out_dir = tmp_path / "report"
        result = main(["map", str(hello_cob), "--output", str(out_dir)])
        assert result == 0

        md_file = out_dir / "software-map.md"
        assert md_file.exists()

    def test_map_missing_file(self, tmp_path):
        result = main(["map", "/nonexistent/file.cob", "--output", str(tmp_path)])
        assert result == 1


class TestConfigOption:
    def test_translate_with_config(self, customer_report_cob, tmp_path):
        config = tmp_path / "custom.json"
        config.write_text('{"sensitive_patterns": [], "exclude_names": []}')
        out_dir = tmp_path / "translated"
        result = main(["translate", str(customer_report_cob), "--output", str(out_dir), "--config", str(config)])
        assert result == 0
        # Verify config was applied: empty patterns means no WARNING comments in output
        # (customer-report.cob normally produces warnings for SSN, BALANCE, etc.)
        py_file = out_dir / "customer_report.py"
        source = py_file.read_text()
        assert "# WARNING [" not in source

    def test_translate_with_missing_config(self, hello_cob, tmp_path, capsys):
        out_dir = tmp_path / "translated"
        result = main(["translate", str(hello_cob), "--output", str(out_dir), "--config", "/nonexistent/config.json"])
        assert result == 0  # Falls back to defaults with warning
        captured = capsys.readouterr()
        assert "Warning" in captured.err


class TestCLIMisc:
    def test_no_command(self):
        result = main([])
        assert result == 0  # prints help

    def test_version(self, capsys):
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "cobol2py" in captured.out
