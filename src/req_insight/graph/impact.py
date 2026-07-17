"""影响面分析：从命中的功能点出发，沿知识图谱做影响传播。

业务视角 —— 四个影响层次：

- direct      直接影响：需求命中的功能点，及其实现系统
- process     流程影响：沿 triggers 边传播到的业务流程下游功能点
- data        数据影响：改动写入的数据实体 → 该实体的其他读方（功能点）
- dependency  依赖影响：依赖受影响系统的上游系统（调用方），行为变化可能波及

技术视角 —— 业务影响面在接口/模块层的投影（不做新的遍历）：

- 受影响功能点沿 exposes 边投影到接口（direct → 需改动，process/data → 回归验证）
- 接口沿 implemented_in 边定位到模块
- 依赖影响精确化：调用方声明了接口级 calls 时，只有调用到「需改动接口」
  才计入依赖影响；一条 calls 都没有的调用方降级回系统级判断（与旧行为一致）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import FunctionPoint, Module
from .loader import (
    CALLS,
    DEPENDS_ON,
    EXPOSES,
    IMPLEMENTED_BY,
    IMPLEMENTED_IN,
    READS,
    TRIGGERS,
    WRITES,
    KnowledgeGraph,
)

LEVELS = ("direct", "process", "data", "dependency")

TECH_SCOPES = ("change", "regression")  # 需改动 / 回归验证


@dataclass
class ImpactItem:
    id: str
    name: str
    kind: str    # function_point | system | entity
    level: str   # direct | process | data | dependency
    reason: str


@dataclass
class TechInterfaceItem:
    """技术视角：受影响的接口。"""

    id: str
    name: str
    kind: str        # http | rpc | mq | job
    ref: str         # 契约标识
    system_id: str
    system_name: str
    scope: str       # change | regression
    reason: str
    callers: list[str] = field(default_factory=list)  # 调用方展示名（含模块粒度）


@dataclass
class TechModuleItem:
    """技术视角：受影响的模块。"""

    id: str
    name: str
    system_name: str
    path: str
    scope: str       # change | regression
    reason: str


@dataclass
class TechImpact:
    """技术视角影响面：业务影响面在接口/模块层的投影。"""

    has_interface_data: bool = False
    interfaces: list[TechInterfaceItem] = field(default_factory=list)
    modules: list[TechModuleItem] = field(default_factory=list)
    # 因接口级依赖收窄而排除的调用方（依赖了受影响系统，但没调用受影响接口）
    excluded_callers: list[str] = field(default_factory=list)

    def by_scope(self, scope: str) -> list[TechInterfaceItem]:
        return [i for i in self.interfaces if i.scope == scope]


@dataclass
class ImpactResult:
    items: list[ImpactItem] = field(default_factory=list)
    teams: dict[str, list[str]] = field(default_factory=dict)  # team -> [system names]
    suggestions: list[str] = field(default_factory=list)
    tech: TechImpact = field(default_factory=TechImpact)

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

        # 技术视角投影（需在依赖层之前：依赖影响按「需改动接口」收窄）
        result.tech = self._project_tech(result)

        # 4. 依赖影响：依赖受影响系统的上游调用方。
        #    调用方声明了对该系统的接口级 calls 时按接口收窄，否则降级回系统级。
        #    一个调用方可能关联多个受影响系统，接口级结论优先于系统级结论，
        #    排除只对「在所有受影响系统上都被排除」的调用方生效。
        change_ifs_by_sys = self._change_interfaces_by_system(result.tech)
        refinable_systems = self._refinable_systems(direct_fps, change_ifs_by_sys)
        impacted_systems = {i.id for i in result.items if i.kind == "system"}
        precise: dict[str, list[str]] = {}
        fallback: dict[str, str] = {}
        excluded: dict[str, list[str]] = {}
        for sys_id in list(impacted_systems):
            for edge in graph.in_edges(sys_id, DEPENDS_ON):
                caller = edge.src
                if caller in impacted_systems:
                    continue
                called_ifs = self._called_interfaces(caller, sys_id)
                if called_ifs and sys_id in refinable_systems:
                    hit = sorted(called_ifs & change_ifs_by_sys[sys_id])
                    if hit:
                        names = "、".join(f"「{graph.name_of(i)}」" for i in hit)
                        precise.setdefault(caller, []).append(names)
                    else:
                        excluded.setdefault(caller, []).append(
                            f"「{graph.name_of(caller)}」依赖「{graph.name_of(sys_id)}」，"
                            "但其调用的接口均不在本次需改动接口内，按接口级依赖排除"
                        )
                else:
                    fallback.setdefault(
                        caller,
                        f"依赖受影响系统「{graph.name_of(sys_id)}」，接口/行为变化可能波及",
                    )
        for caller, names in precise.items():
            add(
                caller,
                "system",
                "dependency",
                f"调用了需改动接口{'、'.join(names)}（接口级依赖确认波及）",
            )
        for caller, reason in fallback.items():
            if caller not in precise:
                add(caller, "system", "dependency", reason)
        for caller, texts in excluded.items():
            if caller not in precise and caller not in fallback:
                result.tech.excluded_callers.extend(texts)

        self._collect_teams(result)
        result.suggestions = self._build_suggestions(result, direct_fps)
        result.suggestions.extend(self._build_tech_suggestions(result))
        return result

    # -- 技术视角投影 ---------------------------------------------------

    def _project_tech(self, result: ImpactResult) -> TechImpact:
        """业务影响面 → 接口/模块层投影。direct 功能点的接口是「需改动」，
        process/data 功能点的接口是「回归验证」；change 优先于 regression。"""
        graph = self.graph
        tech = TechImpact(has_interface_data=bool(graph.panorama.interfaces))
        if not tech.has_interface_data:
            return tech

        interfaces: dict[str, TechInterfaceItem] = {}
        modules: dict[str, TechModuleItem] = {}

        def add_module(mod_id: str, scope: str, reason: str) -> None:
            existing = modules.get(mod_id)
            if existing is not None and (existing.scope == "change" or existing.scope == scope):
                return
            mod = graph.node(mod_id)
            sys_name = graph.name_of(getattr(mod, "system", ""))
            modules[mod_id] = TechModuleItem(
                id=mod_id,
                name=graph.name_of(mod_id),
                system_name=sys_name,
                path=getattr(mod, "path", ""),
                scope=scope,
                reason=reason,
            )

        for item in result.items:
            if item.kind != "function_point":
                continue
            scope = "change" if item.level == "direct" else "regression"
            for edge in graph.out_edges(item.id, EXPOSES):
                itf = graph.node(edge.dst)
                if itf is None:
                    continue
                existing = interfaces.get(itf.id)
                if existing is not None and (existing.scope == "change" or existing.scope == scope):
                    continue
                if scope == "change":
                    reason = f"由需求命中功能点「{item.name}」暴露，契约可能变更"
                else:
                    reason = f"承载{item.level}层影响功能点「{item.name}」，建议回归验证"
                callers = [
                    self._caller_display(c.src) for c in graph.in_edges(itf.id, CALLS)
                ]
                interfaces[itf.id] = TechInterfaceItem(
                    id=itf.id,
                    name=itf.name,
                    kind=itf.kind,
                    ref=itf.ref,
                    system_id=itf.system,
                    system_name=graph.name_of(itf.system),
                    scope=scope,
                    reason=reason,
                    callers=callers,
                )

        # 接口 → 实现模块；需改动接口的调用方模块需要适配/回归
        for t in list(interfaces.values()):
            for edge in graph.out_edges(t.id, IMPLEMENTED_IN):
                add_module(edge.dst, t.scope, f"实现受影响接口「{t.name}」")
            if t.scope == "change":
                for edge in graph.in_edges(t.id, CALLS):
                    if isinstance(graph.node(edge.src), Module):
                        add_module(
                            edge.src, "regression", f"调用了需改动接口「{t.name}」，需适配/回归"
                        )

        order = {"change": 0, "regression": 1}
        tech.interfaces = sorted(interfaces.values(), key=lambda t: order[t.scope])
        tech.modules = sorted(modules.values(), key=lambda m: order[m.scope])
        return tech

    def _caller_display(self, caller_id: str) -> str:
        """调用方展示名：模块显示为「系统·模块」，系统显示系统名。"""
        node = self.graph.node(caller_id)
        if isinstance(node, Module):
            return f"{self.graph.name_of(node.system)}·{node.name}"
        return self.graph.name_of(caller_id)

    def _change_interfaces_by_system(self, tech: TechImpact) -> dict[str, set[str]]:
        by_sys: dict[str, set[str]] = {}
        for t in tech.interfaces:
            if t.scope == "change":
                by_sys.setdefault(t.system_id, set()).add(t.id)
        return by_sys

    def _refinable_systems(
        self, direct_fps: list[str], change_ifs_by_sys: dict[str, set[str]]
    ) -> set[str]:
        """依赖收窄只对「接口信息完整」的系统生效：该系统的每个直接命中
        功能点都配置了 exposes 映射。部分映射时收窄可能漏报，宁可降级。"""
        graph = self.graph
        fp_has_exposes: dict[str, bool] = {
            fp_id: bool(graph.out_edges(fp_id, EXPOSES)) for fp_id in direct_fps
        }
        refinable: set[str] = set()
        for sys_id in change_ifs_by_sys:
            sys_direct_fps = [
                fp_id
                for fp_id in direct_fps
                if any(e.dst == sys_id for e in graph.out_edges(fp_id, IMPLEMENTED_BY))
            ]
            if sys_direct_fps and all(fp_has_exposes[fp] for fp in sys_direct_fps):
                refinable.add(sys_id)
        return refinable

    def _called_interfaces(self, caller_sys_id: str, target_sys_id: str) -> set[str]:
        """调用方系统（含其模块）调用的、归属目标系统的接口集合。"""
        graph = self.graph
        caller_ids = [caller_sys_id] + [
            m.id for m in graph.panorama.modules if m.system == caller_sys_id
        ]
        called: set[str] = set()
        for cid in caller_ids:
            for edge in graph.out_edges(cid, CALLS):
                itf = graph.node(edge.dst)
                if itf is not None and getattr(itf, "system", "") == target_sys_id:
                    called.add(edge.dst)
        return called

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

    def _build_tech_suggestions(self, result: ImpactResult) -> list[str]:
        """技术视角建议：跨团队契约变更、MQ 消息兼容性。"""
        graph = self.graph
        suggestions: list[str] = []

        cross_team: list[str] = []
        for t in result.tech.by_scope("change"):
            if t.kind == "mq":  # MQ 有专门的消息兼容性建议，不进契约建议
                continue
            owner = getattr(graph.node(t.system_id), "owner", "")
            caller_teams: set[str] = set()
            for edge in graph.in_edges(t.id, CALLS):
                caller = graph.node(edge.src)
                caller_sys = caller.system if isinstance(caller, Module) else edge.src
                caller_owner = getattr(graph.node(caller_sys), "owner", "")
                if caller_owner and caller_owner != owner:
                    caller_teams.add(caller_owner)
            if caller_teams:
                cross_team.append(
                    f"「{t.name}」（{owner or t.system_name}）被 {'、'.join(sorted(caller_teams))} 调用"
                )
        if cross_team:
            suggestions.append(
                "跨团队接口契约可能变更：" + "；".join(cross_team)
                + " —— 建议接口评审对齐，并补充契约测试（contract test）"
            )

        mq_changed = [t for t in result.tech.by_scope("change") if t.kind == "mq"]
        for t in mq_changed:
            consumers = "、".join(t.callers) if t.callers else "（未登记消费方）"
            suggestions.append(
                f"MQ 消息「{t.name}」（{t.ref}）的生产方受影响，消费方：{consumers}。"
                "建议评估消息体兼容性（新旧版本共存期只增不改不删字段）"
            )
        return suggestions
