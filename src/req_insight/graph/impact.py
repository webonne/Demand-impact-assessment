"""影响面分析：从命中的功能点出发，沿知识图谱做影响传播。

四个影响层次：

- direct      直接影响：需求命中的功能点，及其实现系统
- process     流程影响：沿 triggers 边传播到的业务流程下游功能点
- data        数据影响：改动写入的数据实体 → 该实体的其他读方（功能点）
- dependency  依赖影响：依赖受影响系统的上游系统（调用方），行为变化可能波及
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import FunctionPoint
from .loader import (
    DEPENDS_ON,
    IMPLEMENTED_BY,
    READS,
    TRIGGERS,
    WRITES,
    KnowledgeGraph,
)

LEVELS = ("direct", "process", "data", "dependency")


@dataclass
class ImpactItem:
    id: str
    name: str
    kind: str    # function_point | system | entity
    level: str   # direct | process | data | dependency
    reason: str


@dataclass
class ImpactResult:
    items: list[ImpactItem] = field(default_factory=list)
    teams: dict[str, list[str]] = field(default_factory=dict)  # team -> [system names]
    suggestions: list[str] = field(default_factory=list)

    def by_level(self, level: str) -> list[ImpactItem]:
        return [i for i in self.items if i.level == level]

    def ids(self) -> set[str]:
        return {i.id for i in self.items}


class ImpactAnalyzer:
    def __init__(self, graph: KnowledgeGraph, max_trigger_depth: int = 3):
        self.graph = graph
        self.max_trigger_depth = max_trigger_depth

    def analyze(self, hit_fp_ids: list[str]) -> ImpactResult:
        graph = self.graph
        result = ImpactResult()
        added: set[tuple[str, str]] = set()  # (id, level) 去重

        def add(node_id: str, kind: str, level: str, reason: str) -> None:
            key = (node_id, level)
            if key in added:
                return
            # 已在更高层级出现的节点不重复降级记录（direct 优先）
            if level != "direct" and (node_id, "direct") in added:
                return
            added.add(key)
            result.items.append(
                ImpactItem(id=node_id, name=graph.name_of(node_id), kind=kind, level=level, reason=reason)
            )

        # 1. 直接影响：命中的功能点 + 实现系统
        direct_fps: list[str] = []
        for fp_id in hit_fp_ids:
            fp = graph.node(fp_id)
            if not isinstance(fp, FunctionPoint):
                continue
            direct_fps.append(fp_id)
            add(fp_id, "function_point", "direct", "需求直接命中")
            for edge in graph.out_edges(fp_id, IMPLEMENTED_BY):
                add(edge.dst, "system", "direct", f"实现功能点「{graph.name_of(fp_id)}」")

        # 2. 流程影响：triggers 传播（限制深度，避免全图扩散）
        frontier = list(direct_fps)
        for depth in range(1, self.max_trigger_depth + 1):
            next_frontier: list[str] = []
            for fp_id in frontier:
                for edge in graph.out_edges(fp_id, TRIGGERS):
                    target = edge.dst
                    if (target, "direct") in added or (target, "process") in added:
                        continue
                    add(
                        target,
                        "function_point",
                        "process",
                        f"业务流程下游：由「{graph.name_of(fp_id)}」触发（{depth} 跳）",
                    )
                    for impl in graph.out_edges(target, IMPLEMENTED_BY):
                        add(impl.dst, "system", "process", f"实现下游功能点「{graph.name_of(target)}」")
                    next_frontier.append(target)
            frontier = next_frontier
            if not frontier:
                break

        # 3. 数据影响：直接功能点写入的实体 → 该实体的其他读方
        for fp_id in direct_fps:
            for w_edge in graph.out_edges(fp_id, WRITES):
                ent_id = w_edge.dst
                add(ent_id, "entity", "data", f"被「{graph.name_of(fp_id)}」写入，数据口径/结构可能变化")
                for r_edge in graph.in_edges(ent_id, READS):
                    reader = r_edge.src
                    if reader == fp_id:
                        continue
                    add(
                        reader,
                        "function_point",
                        "data",
                        f"读取数据实体「{graph.name_of(ent_id)}」，受写入方变更影响",
                    )
                    for impl in graph.out_edges(reader, IMPLEMENTED_BY):
                        add(impl.dst, "system", "data", f"实现读方功能点「{graph.name_of(reader)}」")

        # 4. 依赖影响：依赖受影响系统的上游调用方
        impacted_systems = {i.id for i in result.items if i.kind == "system"}
        for sys_id in list(impacted_systems):
            for edge in graph.in_edges(sys_id, DEPENDS_ON):
                caller = edge.src
                if caller in impacted_systems:
                    continue
                add(
                    caller,
                    "system",
                    "dependency",
                    f"依赖受影响系统「{graph.name_of(sys_id)}」，接口/行为变化可能波及",
                )

        self._collect_teams(result)
        result.suggestions = self._build_suggestions(result, direct_fps)
        return result

    # ------------------------------------------------------------------

    def _collect_teams(self, result: ImpactResult) -> None:
        for item in result.items:
            if item.kind != "system":
                continue
            node = self.graph.node(item.id)
            owner = getattr(node, "owner", "") or "（未配置 owner）"
            result.teams.setdefault(owner, [])
            if item.name not in result.teams[owner]:
                result.teams[owner].append(item.name)

    def _build_suggestions(self, result: ImpactResult, direct_fps: list[str]) -> list[str]:
        graph = self.graph
        suggestions: list[str] = []

        # 回归测试范围（同名功能点可能在多个层级出现，去重）
        regression_fps = list(
            dict.fromkeys(i.name for i in result.items if i.kind == "function_point")
        )
        if regression_fps:
            suggestions.append("回归测试范围建议覆盖功能点：" + "、".join(regression_fps))

        # 跨团队协作
        real_teams = [t for t in result.teams if t != "（未配置 owner）"]
        if len(real_teams) > 1:
            suggestions.append(
                "本需求跨 "
                + str(len(real_teams))
                + " 个团队（"
                + "、".join(real_teams)
                + "），建议在需求评审时拉通对齐排期与接口契约"
            )

        # 高关键度功能点风险提示
        for item in result.items:
            if item.kind != "function_point":
                continue
            node = graph.node(item.id)
            if getattr(node, "criticality", "") == "high":
                suggestions.append(
                    f"⚠ 功能点「{item.name}」为高关键度（{item.level} 影响），"
                    "建议增加灰度发布/开关与线上监控告警"
                )

        # 数据影响提示
        data_entities = [i.name for i in result.by_level("data") if i.kind == "entity"]
        if data_entities:
            suggestions.append(
                "涉及数据实体变更（" + "、".join(data_entities) + "），"
                "建议评估存量数据兼容、报表/下游消费口径，并确认是否需要数据订正"
            )

        # 流程影响提示
        process_fps = [i.name for i in result.by_level("process") if i.kind == "function_point"]
        if process_fps:
            suggestions.append(
                "业务流程下游（" + "、".join(process_fps) + "）虽非本需求改动目标，"
                "建议至少做冒烟验证，确认触发链路无回归"
            )
        return suggestions
