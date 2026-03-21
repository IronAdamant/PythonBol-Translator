"""Tests for sort_translators module: SORT, MERGE, RELEASE, RETURN verbs."""

from cobol_safe_translator.sort_translators import (
    translate_merge,
    translate_release,
    translate_return_verb,
    translate_sort,
)


class TestTranslateSort:
    def test_sort_using_giving(self):
        ops = ["SORT-FILE", "ON", "ASCENDING", "KEY", "SORT-KEY",
               "USING", "INPUT-FILE", "GIVING", "OUTPUT-FILE"]
        lines = translate_sort(ops)
        combined = "\n".join(lines)
        assert "SORT SORT-FILE" in combined
        assert "ASCENDING KEY: SORT-KEY" in combined
        assert "input_file" in combined
        assert "output_file" in combined
        assert ".sort(" in combined

    def test_sort_descending(self):
        ops = ["SORT-FILE", "DESCENDING", "KEY", "AMOUNT",
               "USING", "IN-FILE", "GIVING", "OUT-FILE"]
        lines = translate_sort(ops)
        combined = "\n".join(lines)
        assert "reverse=True" in combined

    def test_sort_multi_key(self):
        ops = ["SORT-FILE", "ASCENDING", "KEY", "DEPT",
               "DESCENDING", "KEY", "SALARY",
               "USING", "EMP-FILE", "GIVING", "SORTED-FILE"]
        lines = translate_sort(ops)
        combined = "\n".join(lines)
        assert "ASCENDING KEY: DEPT" in combined
        assert "DESCENDING KEY: SALARY" in combined

    def test_sort_input_procedure(self):
        ops = ["SORT-FILE", "ASCENDING", "KEY", "REC-KEY",
               "INPUT", "PROCEDURE", "IS", "FILTER-PARA",
               "GIVING", "OUT-FILE"]
        lines = translate_sort(ops)
        combined = "\n".join(lines)
        assert "filter_para()" in combined
        assert "_sort_work" in combined

    def test_sort_output_procedure(self):
        ops = ["SORT-FILE", "ASCENDING", "KEY", "REC-KEY",
               "USING", "IN-FILE",
               "OUTPUT", "PROCEDURE", "IS", "WRITE-PARA"]
        lines = translate_sort(ops)
        combined = "\n".join(lines)
        assert "write_para()" in combined
        assert "_sort_sorted" in combined

    def test_sort_input_output_procedures(self):
        ops = ["SORT-FILE", "ASCENDING", "KEY", "REC-KEY",
               "INPUT", "PROCEDURE", "IS", "READ-PARA",
               "OUTPUT", "PROCEDURE", "IS", "WRITE-PARA"]
        lines = translate_sort(ops)
        combined = "\n".join(lines)
        assert "read_para()" in combined
        assert "write_para()" in combined

    def test_sort_no_operands(self):
        lines = translate_sort([])
        assert lines == ["# SORT: no operands"]

    def test_sort_procedure_with_thru(self):
        ops = ["SORT-FILE", "ASCENDING", "KEY", "K1",
               "INPUT", "PROCEDURE", "IS", "PARA-A", "THRU", "PARA-Z",
               "GIVING", "OUT-FILE"]
        lines = translate_sort(ops)
        combined = "\n".join(lines)
        assert "para_a()" in combined
        assert "THRU PARA-Z" in combined


class TestTranslateMerge:
    def test_merge_using_giving(self):
        ops = ["MERGE-FILE", "ASCENDING", "KEY", "M-KEY",
               "USING", "FILE-A", "FILE-B", "GIVING", "MERGED-FILE"]
        lines = translate_merge(ops)
        combined = "\n".join(lines)
        assert "MERGE MERGE-FILE" in combined
        assert "heapq" in combined
        assert "merged_file" in combined

    def test_merge_no_operands(self):
        lines = translate_merge([])
        assert lines == ["# MERGE: no operands"]

    def test_merge_no_using(self):
        ops = ["MERGE-FILE", "ASCENDING", "KEY", "K1", "GIVING", "OUT"]
        lines = translate_merge(ops)
        combined = "\n".join(lines)
        assert "TODO" in combined

    def test_merge_with_output_procedure(self):
        ops = ["MERGE-FILE", "ASCENDING", "KEY", "K1",
               "USING", "FILE-A", "FILE-B",
               "OUTPUT", "PROCEDURE", "IS", "WRITE-PARA"]
        lines = translate_merge(ops)
        combined = "\n".join(lines)
        assert "write_para()" in combined


class TestTranslateRelease:
    def test_release_basic(self):
        lines = translate_release(["SORT-REC"])
        combined = "\n".join(lines)
        assert "RELEASE SORT-REC" in combined
        assert "_sort_work.append" in combined
        assert "sort_rec.value" in combined

    def test_release_from(self):
        lines = translate_release(["SORT-REC", "FROM", "WS-REC"])
        combined = "\n".join(lines)
        assert "_sort_work.append" in combined

    def test_release_no_operands(self):
        lines = translate_release([])
        assert lines == ["# RELEASE: no record specified"]


class TestTranslateReturnVerb:
    def test_return_into(self):
        lines = translate_return_verb(
            ["SORT-FILE", "INTO", "WS-REC"], "RETURN SORT-FILE INTO WS-REC")
        combined = "\n".join(lines)
        assert "RETURN SORT-FILE" in combined
        assert "_sort_sorted" in combined
        assert "ws_rec" in combined

    def test_return_at_end(self):
        lines = translate_return_verb(
            ["SORT-FILE", "INTO", "WS-REC", "AT", "END", "DISPLAY", "DONE"],
            "RETURN SORT-FILE INTO WS-REC AT END DISPLAY DONE")
        combined = "\n".join(lines)
        assert "else:" in combined

    def test_return_no_operands(self):
        lines = translate_return_verb([], "RETURN")
        assert "no operands" in lines[0]

    def test_return_without_into(self):
        lines = translate_return_verb(["SORT-FILE"], "RETURN SORT-FILE")
        combined = "\n".join(lines)
        assert "_record = self._sort_sorted[0]" in combined
        assert "self._sort_sorted = self._sort_sorted[1:]" in combined
