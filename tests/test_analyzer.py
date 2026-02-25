"""Tests for the COBOL analyzer."""

from cobol_safe_translator.analyzer import (
    analyze,
    detect_sensitivities,
    extract_dependencies,
    load_config,
    DEFAULT_PATTERNS,
    DEFAULT_EXCLUDES,
)
from cobol_safe_translator.models import SensitivityLevel
from cobol_safe_translator.parser import parse_cobol


class TestSensitivityDetection:
    def test_detects_ssn(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        flags = detect_sensitivities(program, DEFAULT_PATTERNS, DEFAULT_EXCLUDES)
        ssn_flags = [f for f in flags if f.data_name == "CUST-SSN"]
        assert len(ssn_flags) == 1
        assert ssn_flags[0].level == SensitivityLevel.HIGH

    def test_detects_balance(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        flags = detect_sensitivities(program, DEFAULT_PATTERNS, DEFAULT_EXCLUDES)
        bal_flags = [f for f in flags if "BALANCE" in f.data_name]
        assert len(bal_flags) == 2  # CUST-BALANCE and WS-TOTAL-BALANCE

    def test_excludes_configured_names(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        # Without exclusions, CUST-SSN is detected
        flags_no_exclude = detect_sensitivities(program, DEFAULT_PATTERNS, [])
        ssn_flags = [f for f in flags_no_exclude if f.data_name == "CUST-SSN"]
        assert len(ssn_flags) == 1, "CUST-SSN should be flagged without exclusion"
        # With CUST-SSN excluded, it should not appear
        flags_with_exclude = detect_sensitivities(program, DEFAULT_PATTERNS, ["CUST-SSN"])
        ssn_excluded = [f for f in flags_with_exclude if f.data_name == "CUST-SSN"]
        assert len(ssn_excluded) == 0, "CUST-SSN should be excluded when in exclude list"

    def test_no_sensitivities_in_hello(self, hello_source):
        program = parse_cobol(hello_source)
        flags = detect_sensitivities(program, DEFAULT_PATTERNS, DEFAULT_EXCLUDES)
        assert len(flags) == 0

    def test_credit_flagged(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        flags = detect_sensitivities(program, DEFAULT_PATTERNS, DEFAULT_EXCLUDES)
        credit_flags = [f for f in flags if "CREDIT" in f.data_name]
        assert len(credit_flags) == 2  # CUST-CREDIT-LIMIT and WS-TOTAL-CREDIT


class TestDependencyExtraction:
    def test_finds_call_statements(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        deps = extract_dependencies(program)
        assert len(deps) == 1
        assert deps[0].call_target == "AUDIT-LOG"

    def test_no_deps_in_hello(self, hello_source):
        program = parse_cobol(hello_source)
        deps = extract_dependencies(program)
        assert len(deps) == 0


class TestFullAnalysis:
    def test_analyze_customer_report(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        assert smap.stats.total_lines > 0
        assert smap.stats.paragraph_count > 0
        assert len(smap.sensitivities) > 0
        assert len(smap.dependencies) > 0

    def test_analyze_hello(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        assert smap.stats.total_lines > 0
        assert smap.stats.paragraph_count > 0
        assert len(smap.warnings) == 0

    def test_stats_accuracy(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        assert smap.stats.code_lines > 0
        assert smap.stats.total_lines == smap.stats.code_lines + smap.stats.comment_lines + smap.stats.blank_lines


class TestConfigValidation:
    def test_invalid_regex_skipped(self, tmp_path):
        config = tmp_path / "bad_regex.json"
        config.write_text(
            '{"sensitive_patterns": ['
            '{"pattern": "[invalid(regex", "level": "high", "reason": "test"}'
            '], "exclude_names": []}'
        )
        patterns, excludes = load_config(config)
        # Invalid regex should be skipped, resulting in empty list
        assert len(patterns) == 0

    def test_missing_keys_skipped(self, tmp_path):
        config = tmp_path / "missing_keys.json"
        config.write_text(
            '{"sensitive_patterns": ['
            '{"pattern": "SSN", "level": "high"}'
            '], "exclude_names": []}'
        )
        patterns, excludes = load_config(config)
        # Missing "reason" key — pattern should be skipped
        assert len(patterns) == 0

    def test_invalid_level_skipped(self, tmp_path):
        config = tmp_path / "bad_level.json"
        config.write_text(
            '{"sensitive_patterns": ['
            '{"pattern": "SSN", "level": "extreme", "reason": "test"}'
            '], "exclude_names": []}'
        )
        patterns, excludes = load_config(config)
        assert len(patterns) == 0

    def test_valid_custom_pattern_accepted(self, tmp_path):
        config = tmp_path / "valid.json"
        config.write_text(
            '{"sensitive_patterns": ['
            '{"pattern": "CUSTOM-FIELD", "level": "high", "reason": "custom test"}'
            '], "exclude_names": ["FILLER"]}'
        )
        patterns, excludes = load_config(config)
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "CUSTOM-FIELD"
        assert patterns[0]["level"] == "high"
        assert excludes == ["FILLER"]
