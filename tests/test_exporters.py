"""Tests for the report exporters."""

import json

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.exporters import export_json, export_markdown
from cobol_safe_translator.parser import parse_cobol


class TestMarkdownExporter:
    def test_contains_header(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "# Software Map:" in md
        assert "CUSTOMER-REPORT" in md

    def test_contains_statistics(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "## Statistics" in md
        assert "Total lines" in md

    def test_contains_sensitivity_report(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "## Sensitivity Report" in md
        assert "CUST-SSN" in md

    def test_contains_mermaid_graph(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "```mermaid" in md
        assert "AUDIT-LOG" in md

    def test_contains_recommendations(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "## Recommendations" in md

    def test_hello_no_sensitivities(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "No sensitive data fields detected" in md

    def test_contains_data_division(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "## Data Division" in md
        assert "CUSTOMER-FILE" in md

    def test_contains_procedure_summary(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        md = export_markdown(smap)
        assert "## Procedure Division" in md
        assert "MAIN-PROGRAM" in md


class TestJsonExporter:
    def test_valid_json(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        raw = export_json(smap)
        data = json.loads(raw)
        assert isinstance(data, dict)

    def test_has_required_fields(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        data = json.loads(export_json(smap))
        assert "program_id" in data
        assert "statistics" in data
        assert "sensitivities" in data
        assert "dependencies" in data

    def test_program_id(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        data = json.loads(export_json(smap))
        assert data["program_id"] == "CUSTOMER-REPORT"

    def test_sensitivities_present(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        data = json.loads(export_json(smap))
        assert len(data["sensitivities"]) > 0
        names = [s["data_name"] for s in data["sensitivities"]]
        assert "CUST-SSN" in names

    def test_dependencies_present(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        data = json.loads(export_json(smap))
        assert len(data["dependencies"]) > 0
        targets = [d["call_target"] for d in data["dependencies"]]
        assert "AUDIT-LOG" in targets

    def test_paragraphs_and_file_controls(self, customer_report_source):
        """Verify JSON export includes paragraph and file_control structures."""
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        data = json.loads(export_json(smap))
        assert len(data["paragraphs"]) > 0
        for p in data["paragraphs"]:
            assert "name" in p
            assert "statement_count" in p
            assert "verbs" in p
        assert len(data["file_controls"]) > 0
        fc_names = [fc["name"] for fc in data["file_controls"]]
        assert "CUSTOMER-FILE" in fc_names
