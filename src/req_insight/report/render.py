"""影响评估报告渲染（markdown）。

报告结构：
1. 需求概要
2. 用户旅程（mermaid journey）
3. 用户故事 → 功能点映射（含未匹配故事 = 疑似新功能点）
4. 影响面分析（四层：直接/流程/数据/依赖 + 影响面图 + 涉及团队）
5. 泳道图
6. 建议 / 假设 / 待澄清问题
"""

from __future__ import annotations

from ..graph.impact import ImpactResult
from ..graph.loader import KnowledgeGraph
from ..graph.render import render_impact_mermaid, render_journey_mermaid
from ..matching.mapper import StoryMapping
from ..models import Artifacts

_LEVEL_TITLES = {
    "direct": "直接影响（需求改动点）",
    "process": "流程影响（业务链路下游）",
    "data": "数据影响（共享数据实体）",
    "dependency": "依赖影响（上游调用方）",
}

_KIND_NAMES = {"function_point": "功能点", "system": "系统", "entity": "数据实体"}


def render_report(
    artifacts: Artifacts,
    mappings: list[StoryMapping],
    result: ImpactResult,
    graph: KnowledgeGraph,
) -> str:
    lines: list[str] = []
    add = lines.append

    source_label = "Demo 走查" if artifacts.source_type == "demo" else "需求文档"
    add(f"# 需求影响评估报告：{artifacts.title}")
    add("")
    add(f"- 需求编号：`{artifacts.requirement_id}`")
    add(f"- 原始输入类型：{source_label}")
    add("")

    # 1. 概要
    add("## 1. 需求概要")
    add("")
    add(artifacts.summary or "（无）")
    add("")

    # 2. 用户旅程
    add("## 2. 用户旅程")
    add("")
    if artifacts.journeys:
        for journey in artifacts.journeys:
            add(f"### {journey.name}（{journey.persona or '用户'}）")
            add("")
            add("```mermaid")
            add(render_journey_mermaid(journey))
            add("```")
            add("")
            add("| 阶段 | 用户动作 | 触点 | 系统行为 | 备注 |")
            add("| --- | --- | --- | --- | --- |")
            for s in journey.stages:
                add(
                    f"| {s.name} | {s.user_action} | {s.touchpoint} | "
                    f"{s.system_behavior} | {s.note} |"
                )
            add("")
    else:
        add("（无）")
        add("")

    # 3. 用户故事映射
    add("## 3. 用户故事 → 功能点映射")
    add("")
    add("| 故事 | 内容 | 命中功能点 | 匹配依据 |")
    add("| --- | --- | --- | --- |")
    unmatched: list[StoryMapping] = []
    for m in mappings:
        story = m.story
        desc = f"作为{story.as_a}，我希望{story.i_want}，以便{story.so_that}"
        if m.matched:
            fps = "<br>".join(f"`{x.fp_id}` {x.fp_name}（{x.score:.1f}）" for x in m.matches)
            terms = "<br>".join("、".join(x.matched_terms) for x in m.matches)
        else:
            fps, terms = "**未匹配**", "—"
            unmatched.append(m)
        add(f"| {story.id} {story.title} | {desc} | {fps} | {terms} |")
    add("")
    if unmatched:
        add("> ⚠ **疑似新功能点**：以下故事未能匹配到全景图中的任何功能点，")
        add("> 可能是全景图缺失或本需求引入了新能力，建议评审后把新功能点补充进全景图：")
        for m in unmatched:
            add(f"> - {m.story.id} {m.story.title}")
        add("")

    # 4. 影响面
    add("## 4. 影响面分析")
    add("")
    if result.items:
        add("```mermaid")
        add(render_impact_mermaid(graph, result))
        add("```")
        add("")
        for level, title in _LEVEL_TITLES.items():
            items = result.by_level(level)
            if not items:
                continue
            add(f"### {title}")
            add("")
            add("| 对象 | 类型 | 原因 |")
            add("| --- | --- | --- |")
            for item in items:
                add(f"| `{item.id}` {item.name} | {_KIND_NAMES.get(item.kind, item.kind)} | {item.reason} |")
            add("")
        if result.teams:
            add("### 涉及团队")
            add("")
            add("| 团队 | 相关系统 |")
            add("| --- | --- |")
            for team, systems in result.teams.items():
                add(f"| {team} | {'、'.join(systems)} |")
            add("")
    else:
        add("（未识别到影响面 —— 所有故事均未匹配到功能点，请先完善全景图关键词）")
        add("")

    # 5. 泳道图
    add("## 5. 泳道图")
    add("")
    if artifacts.swimlane_mermaid.strip():
        add("```mermaid")
        add(artifacts.swimlane_mermaid.strip())
        add("```")
    else:
        add("（无）")
    add("")

    # 6. 建议与待办
    add("## 6. 建议")
    add("")
    if result.suggestions:
        for s in result.suggestions:
            add(f"- {s}")
    else:
        add("（无）")
    add("")

    if artifacts.glossary:
        add("## 附：术语表")
        add("")
        add("| 术语 | 解释 |")
        add("| --- | --- |")
        for term, meaning in artifacts.glossary.items():
            add(f"| {term} | {meaning} |")
        add("")

    if artifacts.assumptions:
        add("## 附：假设（需评审确认）")
        add("")
        for a in artifacts.assumptions:
            add(f"- {a}")
        add("")

    if artifacts.open_questions:
        add("## 附：待澄清问题")
        add("")
        for q in artifacts.open_questions:
            add(f"- [ ] {q}")
        add("")

    return "\n".join(lines)
