"""全景图 / 影响面的 mermaid 渲染。"""

from __future__ import annotations

import re

from ..models import Panorama
from .impact import ImpactResult
from .loader import IMPLEMENTED_BY, KnowledgeGraph


def _mid(node_id: str) -> str:
    """mermaid 节点 id（去掉非法字符）。"""
    return re.sub(r"[^0-9A-Za-z_]", "_", node_id)


def render_panorama_mermaid(panorama: Panorama) -> str:
    """业务全景图总览：域 → 能力 → 功能点。"""
    lines = ["flowchart LR"]
    for dom in panorama.domains:
        lines.append(f'  subgraph {_mid(dom.id)}["{dom.name}"]')
        for cap in dom.capabilities:
            lines.append(f'    subgraph {_mid(cap.id)}["{cap.name}"]')
            for fp in cap.function_points:
                lines.append(f'      {_mid(fp.id)}["{fp.name}"]')
            lines.append("    end")
        lines.append("  end")
    # 跨域触发链路
    for fp in panorama.function_points():
        for target in fp.triggers:
            lines.append(f"  {_mid(fp.id)} -.->|触发| {_mid(target)}")
    return "\n".join(lines)


def render_impact_mermaid(graph: KnowledgeGraph, result: ImpactResult) -> str:
    """影响面图：按影响层级着色。同一节点出现在多个层级时取最高层级。"""
    lines = ["flowchart LR"]
    shape = {
        "function_point": ('["', '"]'),
        "system": ('[["', '"]]'),
        "entity": ('[("', '")]'),
    }
    priority = {"direct": 0, "process": 1, "data": 2, "dependency": 3}
    nodes: dict[str, tuple] = {}
    for item in result.items:
        existing = nodes.get(item.id)
        if existing is None or priority[item.level] < priority[existing[0]]:
            nodes[item.id] = (item.level, item.kind, item.name)
    for node_id, (level, kind, name) in nodes.items():
        left, right = shape.get(kind, ('["', '"]'))
        lines.append(f"  {_mid(node_id)}{left}{name}{right}:::{level}")

    impacted = result.ids()
    drawn: set[tuple[str, str]] = set()
    for item in result.items:
        for edge in graph.out_edges(item.id):
            if edge.dst not in impacted:
                continue
            key = (edge.src, edge.dst)
            if key in drawn:
                continue
            drawn.add(key)
            label = {
                IMPLEMENTED_BY: "实现",
                "triggers": "触发",
                "reads": "读",
                "writes": "写",
                "depends_on": "依赖",
            }.get(edge.type, edge.type)
            lines.append(f"  {_mid(edge.src)} -->|{label}| {_mid(edge.dst)}")

    lines += [
        "  classDef direct fill:#ffdddd,stroke:#cc0000,stroke-width:2px",
        "  classDef process fill:#fff3cd,stroke:#cc8800",
        "  classDef data fill:#d6e9ff,stroke:#0055cc",
        "  classDef dependency fill:#eeeeee,stroke:#666666,stroke-dasharray: 4 4",
    ]
    return "\n".join(lines)


def render_journey_mermaid(journey) -> str:
    """用户旅程渲染为 mermaid journey 图。"""
    lines = ["journey", f"  title {journey.name}"]
    actor = journey.persona or "用户"
    for stage in journey.stages:
        lines.append(f"  section {stage.name}")
        action = stage.user_action or stage.name
        lines.append(f"    {action}: 3: {actor}")
    return "\n".join(lines)
