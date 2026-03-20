# Next Session Plan — PythonBol-Translator

> **Updated:** 2026-03-21 (Session 27, v1.0.1)
> **Purpose:** Reminder file for next work session. Delete after completing.

## Current State

- **Version:** 1.0.1
- **Tests:** 1,033 pass, 2 skipped
- **Corpus:** 5,288/5,288 valid Python (100%) across 32 projects
- **Source:** 45 modules, ~14.4K LOC
- **Intrinsics:** 41 functions

## Priority 1: Complexity Hotspots

### mapper_codegen.py (821 LOC, +64% over guideline)
- `_program_class()` has 7 nesting levels and 114 lines
- `_data_class()` has 5 nesting levels
- Primary candidate for decomposition into smaller helpers

### translate_evaluate_block (159 lines, 32 branches)
- Multi-subject EVALUATE complexity in evaluate_translator.py
- Could benefit from extracting WHEN clause parsing into helper

### generate_cics_template (162 lines, 15 branches)
- cics_translator.py — Large template generation function

## Priority 2: Code Quality

| Item | Notes |
|------|-------|
| Broad Exception catches | 8 `except Exception` — 6 in indexed_file_adapter.py. Narrow to OSError/IOError where failure mode is known |
| Function docstrings | ~41% of functions lack docstrings (mostly _prefixed helpers) |
| 500 LOC guideline | 6 files exceed limit (mapper_codegen 821, parser 633, cli 615, condition_translator 558, exec_block_handler 540, mapper_verbs 508) |

## Priority 3: Future Enhancements

| Category | Notes |
|----------|-------|
| Expression tree walker | Complex COMPUTE expressions — would reduce largest TODO category |
| Condition edge cases | Deeply nested IF/EVALUATE with implied subjects |
| Variable-length OCCURS | OCCURS DEPENDING ON arrays still fixed-size (guard in place for REDEFINES) |

## Housekeeping

- [x] Full codebase review pass (Session 27)
- [x] Dead code removal (Session 27 — 6 items removed)
- [x] README/SUPPORTED_SUBSET metrics refresh (Session 27)
- [x] Remove legacy docs — Stele now handles indexing
- [ ] Update GLOBAL_AGENTS.md to reflect Stele replacing legacy doc requirements (do when working on Stele project)
