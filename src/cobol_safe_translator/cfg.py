"""Control Flow Graph builder for COBOL procedure divisions.

Builds a lightweight paragraph-level CFG to support:
  - GO TO target resolution
  - ALTER verb tracking (dynamic GO TO target modification)
  - Unreachable code detection
  - PERFORM call graph analysis
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from .models import CobolProgram, Paragraph


class EdgeType(Enum):
    SEQUENTIAL = auto()  # fall-through to next paragraph
    GOTO = auto()  # GO TO target
    PERFORM = auto()  # PERFORM target (call + return)
    ALTER = auto()  # ALTER modifies a GO TO target


@dataclass
class CfgEdge:
    """An edge in the control flow graph."""
    source: str  # paragraph name
    target: str  # paragraph name
    edge_type: EdgeType
    is_unconditional: bool = False  # True for simple GO TO


@dataclass
class CfgNode:
    """A node (paragraph) in the control flow graph."""
    name: str
    outgoing: list[CfgEdge] = field(default_factory=list)
    incoming: list[CfgEdge] = field(default_factory=list)
    has_unconditional_goto: bool = False
    has_stop_run: bool = False


@dataclass
class AlterMapping:
    """Tracks an ALTER verb that modifies a GO TO target."""
    source_paragraph: str  # paragraph containing the ALTER
    altered_paragraph: str  # paragraph whose GO TO is modified
    new_target: str  # the new GO TO target


@dataclass
class ControlFlowGraph:
    """Paragraph-level control flow graph for a COBOL program."""
    nodes: dict[str, CfgNode] = field(default_factory=dict)
    edges: list[CfgEdge] = field(default_factory=list)
    alter_mappings: list[AlterMapping] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)


def build_cfg(program: CobolProgram) -> ControlFlowGraph:
    """Build a paragraph-level control flow graph from a CobolProgram."""
    cfg = ControlFlowGraph()

    # Create nodes for each paragraph
    para_names = [p.name.upper() for p in program.paragraphs]
    for para in program.paragraphs:
        cfg.nodes[para.name.upper()] = CfgNode(name=para.name)

    # Walk statements to build edges
    for idx, para in enumerate(program.paragraphs):
        node = cfg.nodes[para.name.upper()]

        for stmt in para.statements:
            verb = stmt.verb
            upper_ops = [o.upper() for o in stmt.operands]

            if verb == "GO":
                _process_goto(cfg, node, para, stmt.operands, upper_ops)
            elif verb == "PERFORM":
                _process_perform(cfg, node, para, upper_ops)
            elif verb == "ALTER":
                _process_alter(cfg, para, stmt.operands, upper_ops)
            elif verb in ("STOP", "GOBACK"):
                node.has_stop_run = True

        # Sequential fall-through edge (unless paragraph ends with unconditional GO TO or STOP)
        if not node.has_unconditional_goto and not node.has_stop_run:
            if idx + 1 < len(program.paragraphs):
                next_para = program.paragraphs[idx + 1]
                edge = CfgEdge(
                    source=para.name, target=next_para.name,
                    edge_type=EdgeType.SEQUENTIAL,
                )
                cfg.edges.append(edge)
                node.outgoing.append(edge)
                cfg.nodes[next_para.name.upper()].incoming.append(edge)

    # Detect unreachable paragraphs
    cfg.unreachable = _find_unreachable(cfg, para_names)

    return cfg


def _process_goto(
    cfg: ControlFlowGraph, node: CfgNode,
    para: Paragraph, ops: list[str], upper_ops: list[str],
) -> None:
    """Process a GO TO statement and add edges."""
    filtered = [o for i, o in enumerate(ops) if upper_ops[i] not in ("TO", "DEPENDING", "ON")]
    for target in filtered:
        if target.upper() in cfg.nodes:
            edge = CfgEdge(
                source=para.name, target=target,
                edge_type=EdgeType.GOTO,
                is_unconditional=(len(filtered) == 1 and "DEPENDING" not in upper_ops),
            )
            cfg.edges.append(edge)
            node.outgoing.append(edge)
            cfg.nodes[target.upper()].incoming.append(edge)

    # Simple GO TO (single target, no DEPENDING) is unconditional
    if len(filtered) == 1 and "DEPENDING" not in upper_ops:
        node.has_unconditional_goto = True


def _process_perform(
    cfg: ControlFlowGraph, node: CfgNode,
    para: Paragraph, upper_ops: list[str],
) -> None:
    """Process a PERFORM statement and add edges."""
    if not upper_ops:
        return
    target = upper_ops[0]
    if target in cfg.nodes:
        edge = CfgEdge(
            source=para.name, target=target,
            edge_type=EdgeType.PERFORM,
        )
        cfg.edges.append(edge)
        node.outgoing.append(edge)
        cfg.nodes[target].incoming.append(edge)


def _process_alter(
    cfg: ControlFlowGraph,
    para: Paragraph, ops: list[str], upper_ops: list[str],
) -> None:
    """Process an ALTER statement: ALTER para-1 TO PROCEED TO para-2."""
    # ALTER paragraph-1 TO [PROCEED TO] paragraph-2
    filtered = [o for i, o in enumerate(ops)
                if upper_ops[i] not in ("TO", "PROCEED")]
    if len(filtered) >= 2:
        altered = filtered[0]
        new_target = filtered[1]
        cfg.alter_mappings.append(AlterMapping(
            source_paragraph=para.name,
            altered_paragraph=altered,
            new_target=new_target,
        ))
        # Add an ALTER edge
        if altered.upper() in cfg.nodes:
            edge = CfgEdge(
                source=para.name, target=altered,
                edge_type=EdgeType.ALTER,
            )
            cfg.edges.append(edge)


def _find_unreachable(
    cfg: ControlFlowGraph, para_names: list[str],
) -> list[str]:
    """Find paragraphs with no incoming edges (except the first one)."""
    if not para_names:
        return []

    unreachable: list[str] = []
    first = para_names[0]
    for name in para_names[1:]:
        node = cfg.nodes.get(name)
        if node and not node.incoming:
            unreachable.append(node.name)
    return unreachable
