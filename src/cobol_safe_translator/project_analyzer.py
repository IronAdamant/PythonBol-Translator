"""Cross-program CALL graph analysis for COBOL project directories.

Analyzes all COBOL files in a directory, builds a project-wide CALL graph,
identifies entry points, and generates a unified Python package with proper
cross-module imports.

Pipeline: Directory -> discover -> parse/analyze each -> ProjectMap -> Package
"""

from __future__ import annotations

from pathlib import Path

from .batch import discover_cobol_files
from .parser import parse_cobol_file
from .analyzer import analyze
from .models import ProjectMap, SoftwareMap
from .utils import _to_python_name


def analyze_project(
    directory: Path,
    recursive: bool = False,
    copy_paths: list[str] | None = None,
    config_path: str | None = None,
) -> ProjectMap:
    """Analyze all COBOL files in a directory and build a project-wide map.

    Returns a ProjectMap with cross-program CALL graph, entry points,
    and unresolved external references.
    """
    files = discover_cobol_files(directory, recursive=recursive)

    programs: dict[str, SoftwareMap] = {}

    # Parse and analyze each file
    for f in files:
        try:
            program = parse_cobol_file(f, copy_paths=copy_paths)
            smap = analyze(program, config_path=config_path)
            pid = (program.program_id or f.stem).upper()
            programs[pid] = smap
        except Exception:
            continue  # skip unparseable files

    # Build CALL graph
    all_program_ids = set(programs.keys())
    call_graph: dict[str, list[str]] = {}
    unresolved: dict[str, list[str]] = {}
    called_programs: set[str] = set()

    for pid, smap in programs.items():
        callees: list[str] = []
        unresolved_callees: list[str] = []
        for dep in smap.dependencies:
            target = dep.call_target.upper().strip('"').strip("'")
            if target in all_program_ids:
                callees.append(target)
                called_programs.add(target)
            else:
                unresolved_callees.append(target)
        if callees:
            call_graph[pid] = callees
        if unresolved_callees:
            unresolved[pid] = unresolved_callees

    # Entry points = programs not called by anyone else
    entry_points = sorted(all_program_ids - called_programs)

    return ProjectMap(
        programs=programs,
        call_graph=call_graph,
        entry_points=entry_points,
        unresolved_calls=unresolved,
    )


def generate_package(
    project_map: ProjectMap,
    output_dir: Path,
    package_name: str = "cobol_project",
) -> list[Path]:
    """Generate a unified Python package from a ProjectMap.

    Creates:
      output_dir/
        package_name/
          __init__.py    -- package init with entry point imports
          program_a.py   -- translated program A
          program_b.py   -- translated program B
          ...
          CALL_GRAPH.txt -- call graph report

    CALL statements between known programs become Python imports.
    """
    from .mapper import generate_python

    pkg_dir = output_dir / package_name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    module_names: dict[str, str] = {}  # PROGRAM-ID -> python module name

    # Generate module name mapping
    for pid in project_map.programs:
        module_names[pid] = _to_python_name(pid)

    # Generate each program module
    for pid, smap in project_map.programs.items():
        mod_name = module_names[pid]
        source = generate_python(smap)

        # Patch CALL stubs: replace TODO comments with actual imports
        for callee_pid, callee_mod in module_names.items():
            if callee_pid == pid:
                continue
            # Match the exact stub format from translate_call()
            call_target = callee_pid.strip('"').strip("'")
            py_target = _to_python_name(call_target)
            # The stub may include arguments, so match the prefix
            old_stub = f"# TODO(high): implement or import {py_target}"
            if old_stub in source:
                class_name = _to_python_name(callee_pid).title().replace("_", "")
                new_import = (
                    f"from .{callee_mod} import {class_name}Program\n"
                    f"        {py_target}_instance = {class_name}Program()\n"
                    f"        {py_target}_instance.run()"
                )
                source = source.replace(old_stub, new_import)

        mod_path = pkg_dir / f"{mod_name}.py"
        mod_path.write_text(source, encoding="utf-8")
        written.append(mod_path)

    # Generate __init__.py with entry point imports
    init_lines = [
        f'"""COBOL project package -- translated from {len(project_map.programs)} programs."""',
        '',
    ]
    for ep in project_map.entry_points:
        mod = module_names[ep]
        class_name = _to_python_name(ep).title().replace("_", "")
        init_lines.append(f'from .{mod} import {class_name}Program')

    init_lines.extend(['', ''])
    init_path = pkg_dir / "__init__.py"
    init_path.write_text('\n'.join(init_lines), encoding='utf-8')
    written.append(init_path)

    # Generate call graph report
    report_lines = [
        f'# CALL Graph for {package_name}',
        f'# {len(project_map.programs)} programs, {len(project_map.entry_points)} entry points',
        '',
        '# Entry points (not called by any other program):',
    ]
    for ep in project_map.entry_points:
        report_lines.append(f'#   {ep}')
    report_lines.append('')
    report_lines.append('# CALL relationships:')
    for caller, callees in sorted(project_map.call_graph.items()):
        for callee in callees:
            report_lines.append(f'#   {caller} -> {callee}')
    if project_map.unresolved_calls:
        report_lines.append('')
        report_lines.append('# Unresolved external CALLs:')
        for prog, targets in sorted(project_map.unresolved_calls.items()):
            for t in targets:
                report_lines.append(f'#   {prog} -> {t} (NOT FOUND)')

    report_path = pkg_dir / "CALL_GRAPH.txt"
    report_path.write_text('\n'.join(report_lines), encoding='utf-8')
    written.append(report_path)

    return written
