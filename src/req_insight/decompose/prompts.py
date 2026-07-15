"""需求解构提示词：从原始需求生成用户旅程 / 用户故事 / 泳道图。

提示词把业务全景图摘要一并交给模型，让解构产物的用语尽量贴近
全景图的功能点命名与关键词，从而提升后续匹配的命中率。
"""

from __future__ import annotations

from ..models import Panorama, RawRequirement

# 结构化输出 JSON Schema（与 Artifacts.from_dict 对应）
ARTIFACTS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "需求一句话概述 + 关键背景（3~5 句）"},
        "journeys": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "persona": {"type": "string"},
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "user_action": {"type": "string"},
                                "touchpoint": {"type": "string"},
                                "system_behavior": {"type": "string"},
                                "note": {"type": "string"},
                            },
                            "required": ["name", "user_action", "touchpoint", "system_behavior", "note"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "persona", "stages"],
                "additionalProperties": False,
            },
        },
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "as_a": {"type": "string"},
                    "i_want": {"type": "string"},
                    "so_that": {"type": "string"},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "as_a", "i_want", "so_that", "acceptance_criteria", "keywords"],
                "additionalProperties": False,
            },
        },
        "swimlane_mermaid": {"type": "string", "description": "mermaid sequenceDiagram 或 flowchart 源码"},
        "glossary": {"type": "string", "description": "术语表，格式：每行「术语: 解释」，无则为空字符串"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary",
        "journeys",
        "stories",
        "swimlane_mermaid",
        "glossary",
        "assumptions",
        "open_questions",
    ],
    "additionalProperties": False,
}


def _panorama_digest(panorama: Panorama) -> str:
    """全景图摘要：域/能力/功能点及关键词，供模型对齐用语。"""
    lines: list[str] = []
    for dom in panorama.domains:
        lines.append(f"- 业务域：{dom.name}")
        for cap in dom.capabilities:
            lines.append(f"  - 能力：{cap.name}")
            for fp in cap.function_points:
                kw = "、".join(fp.keywords) if fp.keywords else "—"
                lines.append(f"    - 功能点：{fp.name}（关键词：{kw}）")
    return "\n".join(lines)


_DEMO_GUIDANCE = """\
本需求的输入不是需求文档，而是一个 demo 的走查记录（页面/交互描述）。请先做逆向还原，再产出解构产物：
1. 从 demo 描述中枚举出：涉及的页面/界面、可交互元素、状态与状态变化、展示的数据字段；
2. 由此反推用户想完成的任务和业务规则（demo 只体现了「怎么做」，你要还原「为什么做」）；
3. demo 通常只覆盖主流程 —— 把 demo 没有体现的分支、异常、边界情况写入 open_questions，
   把你不得不做的推断写入 assumptions，不要凭空当成确定需求。"""

_DOCUMENT_GUIDANCE = """\
本需求的输入是一份需求文档。请忠实于文档内容进行解构；文档中含糊、缺失、互相矛盾之处
写入 open_questions，你做出的补充推断写入 assumptions。"""


def build_decompose_prompt(raw: RawRequirement, panorama: Panorama) -> str:
    guidance = _DEMO_GUIDANCE if raw.source_type == "demo" else _DOCUMENT_GUIDANCE
    return f"""\
你是一名资深业务分析师。请把下面的原始需求解构为结构化的需求分析产物，用于：
(a) 帮助研发在开发前理解需求全貌；(b) 后续把需求映射到业务全景图的功能点上做影响面评估。

{guidance}

【解构要求】
- journeys：用户旅程，按阶段列出用户动作、触点（页面/端）、系统行为；1~2 条即可，覆盖核心场景。
- stories：用户故事，格式为「作为(as_a)…我希望(i_want)…以便(so_that)…」，每条附验收标准
  (acceptance_criteria) 和 keywords。keywords 非常重要：请优先复用下方业务全景图里出现的
  功能点名称与关键词（命中才能算影响面），再补充需求特有的词。
- swimlane_mermaid：泳道图，用 mermaid sequenceDiagram 表达「用户/前端/各后端系统」之间的交互，
  参与方命名尽量与全景图中的系统对应。
- glossary：需求中的业务术语及解释，每行一条，格式「术语: 解释」。
- assumptions / open_questions：如实记录，宁多勿少，这是需求评审时最有价值的部分。
- 全部使用中文输出。

【业务全景图摘要】
{_panorama_digest(panorama)}

【原始需求】（类型：{"Demo 走查记录" if raw.source_type == "demo" else "需求文档"}）
标题：{raw.title}

{raw.body}
"""
