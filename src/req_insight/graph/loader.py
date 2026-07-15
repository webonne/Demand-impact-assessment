"""业务全景图加载与知识图谱构建。

全景图以「图谱即代码」的方式维护在 YAML 文件中（默认 data/panorama/）：

- domains.yaml   业务域 → 业务能力 → 功能点
- systems.yaml   系统/服务、数据实体

加载后构建为有向图（节点 + 类型化边），供影响面分析遍历。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..models import (
    Capability,
    Domain,
    Entity,
    FunctionPoint,
    Panorama,
    System,
)

# 边类型
CONTAINS = "contains"            # domain -> capability -> function_point
IMPLEMENTED_BY = "implemented_by"  # function_point -> system
DEPENDS_ON = "depends_on"        # system -> system（调用/依赖方向）
READS = "reads"                  # function_point -> entity
WRITES = "writes"                # function_point -> entity
TRIGGERS = "triggers"            # function_point -> function_point（业务流程下游）


@dataclass
class Edge:
    src: str
    dst: str
    type: str


@dataclass
class KnowledgeGraph:
    """全景图对应的知识图谱视图。"""

    panorama: Panorama
    nodes: dict[str, Any] = field(default_factory=dict)
    _out: dict[str, list[Edge]] = field(default_factory=dict)
    _in: dict[str, list[Edge]] = field(default_factory=dict)

    def add_edge(self, src: str, dst: str, type_: str) -> None:
        edge = Edge(src, dst, type_)
        self._out.setdefault(src, []).append(edge)
        self._in.setdefault(dst, []).append(edge)

    def out_edges(self, node_id: str, type_: str | None = None) -> list[Edge]:
        edges = self._out.get(node_id, [])
        return [e for e in edges if type_ is None or e.type == type_]

    def in_edges(self, node_id: str, type_: str | None = None) -> list[Edge]:
        edges = self._in.get(node_id, [])
        return [e for e in edges if type_ is None or e.type == type_]

    def node(self, node_id: str) -> Any:
        return self.nodes.get(node_id)

    def name_of(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        return getattr(node, "name", node_id) if node else node_id


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_function_point(data: dict[str, Any], cap: Capability, dom: Domain) -> FunctionPoint:
    return FunctionPoint(
        id=data["id"],
        name=data.get("name", data["id"]),
        capability_id=cap.id,
        domain_id=dom.id,
        description=data.get("description", ""),
        keywords=list(data.get("keywords", [])),
        implemented_by=list(data.get("implemented_by", [])),
        reads=list(data.get("reads", [])),
        writes=list(data.get("writes", [])),
        triggers=list(data.get("triggers", [])),
        criticality=data.get("criticality", "medium"),
    )


def load_panorama(directory: str | Path) -> Panorama:
    """从目录加载全景图 YAML。"""
    directory = Path(directory)
    domains_data = _load_yaml(directory / "domains.yaml")
    systems_data = _load_yaml(directory / "systems.yaml")

    domains: list[Domain] = []
    for d in domains_data.get("domains", []):
        dom = Domain(id=d["id"], name=d.get("name", d["id"]), description=d.get("description", ""))
        for c in d.get("capabilities", []):
            cap = Capability(
                id=c["id"],
                name=c.get("name", c["id"]),
                domain_id=dom.id,
                description=c.get("description", ""),
            )
            for fp_data in c.get("function_points", []):
                cap.function_points.append(_parse_function_point(fp_data, cap, dom))
            dom.capabilities.append(cap)
        domains.append(dom)

    systems = [
        System(
            id=s["id"],
            name=s.get("name", s["id"]),
            owner=s.get("owner", ""),
            description=s.get("description", ""),
            depends_on=list(s.get("depends_on", [])),
        )
        for s in systems_data.get("systems", [])
    ]
    entities = [
        Entity(
            id=e["id"],
            name=e.get("name", e["id"]),
            description=e.get("description", ""),
            owned_by=e.get("owned_by", ""),
        )
        for e in systems_data.get("entities", [])
    ]
    return Panorama(domains=domains, systems=systems, entities=entities)


def build_graph(panorama: Panorama) -> KnowledgeGraph:
    """由全景图构建知识图谱（有向图）。"""
    graph = KnowledgeGraph(panorama=panorama)
    graph.nodes = panorama.index()

    for dom in panorama.domains:
        for cap in dom.capabilities:
            graph.add_edge(dom.id, cap.id, CONTAINS)
            for fp in cap.function_points:
                graph.add_edge(cap.id, fp.id, CONTAINS)
                for sys_id in fp.implemented_by:
                    graph.add_edge(fp.id, sys_id, IMPLEMENTED_BY)
                for ent_id in fp.reads:
                    graph.add_edge(fp.id, ent_id, READS)
                for ent_id in fp.writes:
                    graph.add_edge(fp.id, ent_id, WRITES)
                for target in fp.triggers:
                    graph.add_edge(fp.id, target, TRIGGERS)

    for sys_ in panorama.systems:
        for dep in sys_.depends_on:
            graph.add_edge(sys_.id, dep, DEPENDS_ON)

    return graph


def validate_panorama(panorama: Panorama) -> tuple[list[str], list[str]]:
    """校验全景图：返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []

    idx = panorama.index()
    seen: set[str] = set()
    for node_id in _all_ids(panorama):
        if node_id in seen:
            errors.append(f"ID 重复: {node_id}")
        seen.add(node_id)

    system_ids = {s.id for s in panorama.systems}
    entity_ids = {e.id for e in panorama.entities}
    fp_ids = {fp.id for fp in panorama.function_points()}

    for fp in panorama.function_points():
        for sys_id in fp.implemented_by:
            if sys_id not in system_ids:
                errors.append(f"功能点 {fp.id} 引用了不存在的系统: {sys_id}")
        for ent_id in fp.reads + fp.writes:
            if ent_id not in entity_ids:
                errors.append(f"功能点 {fp.id} 引用了不存在的数据实体: {ent_id}")
        for target in fp.triggers:
            if target not in fp_ids:
                errors.append(f"功能点 {fp.id} 触发了不存在的功能点: {target}")
        if not fp.keywords:
            warnings.append(f"功能点 {fp.id}（{fp.name}）没有配置 keywords，需求将难以匹配到它")
        if not fp.implemented_by:
            warnings.append(f"功能点 {fp.id}（{fp.name}）没有关联实现系统")

    for sys_ in panorama.systems:
        for dep in sys_.depends_on:
            if dep not in system_ids:
                errors.append(f"系统 {sys_.id} 依赖了不存在的系统: {dep}")
        if not sys_.owner:
            warnings.append(f"系统 {sys_.id}（{sys_.name}）没有配置 owner 团队")

    for ent in panorama.entities:
        if ent.owned_by and ent.owned_by not in system_ids:
            errors.append(f"数据实体 {ent.id} 归属了不存在的系统: {ent.owned_by}")

    del idx
    return errors, warnings


def _all_ids(panorama: Panorama) -> list[str]:
    ids: list[str] = []
    for dom in panorama.domains:
        ids.append(dom.id)
        for cap in dom.capabilities:
            ids.append(cap.id)
            ids.extend(fp.id for fp in cap.function_points)
    ids.extend(s.id for s in panorama.systems)
    ids.extend(e.id for e in panorama.entities)
    return ids
