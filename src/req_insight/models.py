"""核心数据模型：业务全景图（知识图谱）与需求解构产物。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 业务全景图 / 知识图谱
# ---------------------------------------------------------------------------

CRITICALITY_LEVELS = ("low", "medium", "high")


@dataclass
class FunctionPoint:
    """功能点：全景图的最小粒度，需求最终落到这里。"""

    id: str
    name: str
    capability_id: str = ""
    domain_id: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    implemented_by: list[str] = field(default_factory=list)  # -> System.id
    reads: list[str] = field(default_factory=list)           # -> Entity.id
    writes: list[str] = field(default_factory=list)          # -> Entity.id
    triggers: list[str] = field(default_factory=list)        # -> FunctionPoint.id（业务流程下游）
    criticality: str = "medium"


@dataclass
class Capability:
    """业务能力：域下的一组功能点。"""

    id: str
    name: str
    domain_id: str = ""
    description: str = ""
    function_points: list[FunctionPoint] = field(default_factory=list)


@dataclass
class Domain:
    """业务域：全景图的一级结构。"""

    id: str
    name: str
    description: str = ""
    capabilities: list[Capability] = field(default_factory=list)


@dataclass
class System:
    """系统 / 服务。"""

    id: str
    name: str
    owner: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)  # -> System.id


@dataclass
class Entity:
    """数据实体（核心业务数据）。"""

    id: str
    name: str
    description: str = ""
    owned_by: str = ""  # -> System.id


@dataclass
class Panorama:
    """业务全景图 = 域/能力/功能点 + 系统 + 数据实体。"""

    domains: list[Domain] = field(default_factory=list)
    systems: list[System] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)

    def function_points(self) -> list[FunctionPoint]:
        return [
            fp
            for dom in self.domains
            for cap in dom.capabilities
            for fp in cap.function_points
        ]

    def index(self) -> dict[str, Any]:
        idx: dict[str, Any] = {}
        for dom in self.domains:
            idx[dom.id] = dom
            for cap in dom.capabilities:
                idx[cap.id] = cap
                for fp in cap.function_points:
                    idx[fp.id] = fp
        for sys_ in self.systems:
            idx[sys_.id] = sys_
        for ent in self.entities:
            idx[ent.id] = ent
        return idx


# ---------------------------------------------------------------------------
# 原始需求与解构产物（左移部分）
# ---------------------------------------------------------------------------

SOURCE_TYPES = ("document", "demo")


@dataclass
class RawRequirement:
    """原始需求：可能是一份需求文档，也可能是一个 demo 的描述/走查记录。"""

    id: str
    title: str
    source_type: str  # document | demo
    body: str
    path: str = ""


@dataclass
class JourneyStage:
    name: str
    user_action: str = ""
    touchpoint: str = ""
    system_behavior: str = ""
    note: str = ""


@dataclass
class UserJourney:
    name: str
    persona: str = ""
    stages: list[JourneyStage] = field(default_factory=list)


@dataclass
class UserStory:
    id: str
    title: str
    as_a: str = ""
    i_want: str = ""
    so_that: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def match_text(self) -> str:
        """用于功能点匹配的文本。"""
        parts = [self.title, self.as_a, self.i_want, self.so_that]
        parts.extend(self.acceptance_criteria)
        parts.extend(self.keywords)
        return " ".join(p for p in parts if p)


@dataclass
class Artifacts:
    """需求解构产物：评估影响面、帮助开发理解需求的辅助资料。"""

    requirement_id: str
    title: str
    source_type: str = "document"
    summary: str = ""
    journeys: list[UserJourney] = field(default_factory=list)
    stories: list[UserStory] = field(default_factory=list)
    swimlane_mermaid: str = ""
    glossary: dict[str, str] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    # -- YAML/JSON 序列化 ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "title": self.title,
            "source_type": self.source_type,
            "summary": self.summary,
            "journeys": [
                {
                    "name": j.name,
                    "persona": j.persona,
                    "stages": [
                        {
                            "name": s.name,
                            "user_action": s.user_action,
                            "touchpoint": s.touchpoint,
                            "system_behavior": s.system_behavior,
                            "note": s.note,
                        }
                        for s in j.stages
                    ],
                }
                for j in self.journeys
            ],
            "stories": [
                {
                    "id": s.id,
                    "title": s.title,
                    "as_a": s.as_a,
                    "i_want": s.i_want,
                    "so_that": s.so_that,
                    "acceptance_criteria": list(s.acceptance_criteria),
                    "keywords": list(s.keywords),
                }
                for s in self.stories
            ],
            "swimlane_mermaid": self.swimlane_mermaid,
            "glossary": dict(self.glossary),
            "assumptions": list(self.assumptions),
            "open_questions": list(self.open_questions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifacts":
        journeys = [
            UserJourney(
                name=j.get("name", ""),
                persona=j.get("persona", ""),
                stages=[
                    JourneyStage(
                        name=s.get("name", ""),
                        user_action=s.get("user_action", ""),
                        touchpoint=s.get("touchpoint", ""),
                        system_behavior=s.get("system_behavior", ""),
                        note=s.get("note", ""),
                    )
                    for s in j.get("stages", [])
                ],
            )
            for j in data.get("journeys", [])
        ]
        stories = [
            UserStory(
                id=s.get("id", f"US-{i + 1}"),
                title=s.get("title", ""),
                as_a=s.get("as_a", ""),
                i_want=s.get("i_want", ""),
                so_that=s.get("so_that", ""),
                acceptance_criteria=list(s.get("acceptance_criteria", [])),
                keywords=list(s.get("keywords", [])),
            )
            for i, s in enumerate(data.get("stories", []))
        ]
        return cls(
            requirement_id=data.get("requirement_id", ""),
            title=data.get("title", ""),
            source_type=data.get("source_type", "document"),
            summary=data.get("summary", ""),
            journeys=journeys,
            stories=stories,
            swimlane_mermaid=data.get("swimlane_mermaid", ""),
            glossary=dict(data.get("glossary", {}) or {}),
            assumptions=list(data.get("assumptions", [])),
            open_questions=list(data.get("open_questions", [])),
        )
