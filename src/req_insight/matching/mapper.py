"""用户故事 → 业务全景图功能点匹配。

默认使用确定性的关键词匹配（可解释、零依赖）：

- 功能点名称出现在故事文本中：+3 分
- 功能点 keyword 命中：每个 +1 分
- 所属能力名称命中：+0.5 分（弱信号）

匹配不到任何功能点的故事会被标记为「疑似新功能点」，
提示维护者把它补充进全景图 —— 全景图因此随需求持续生长。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Panorama, UserStory

DEFAULT_MIN_SCORE = 1.0
DEFAULT_TOP_N = 3


@dataclass
class Match:
    fp_id: str
    fp_name: str
    score: float
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class StoryMapping:
    story: UserStory
    matches: list[Match] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return bool(self.matches)


def match_function_points(
    text: str,
    panorama: Panorama,
    top_n: int = DEFAULT_TOP_N,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[Match]:
    """对一段需求文本做功能点匹配，返回按分数排序的候选。"""
    text_lower = text.lower()
    cap_names = {}
    for dom in panorama.domains:
        for cap in dom.capabilities:
            cap_names[cap.id] = cap.name

    matches: list[Match] = []
    for fp in panorama.function_points():
        score = 0.0
        terms: list[str] = []
        if fp.name and fp.name.lower() in text_lower:
            score += 3.0
            terms.append(fp.name)
        for kw in fp.keywords:
            if kw and kw.lower() in text_lower:
                score += 1.0
                terms.append(kw)
        cap_name = cap_names.get(fp.capability_id, "")
        if cap_name and cap_name.lower() in text_lower:
            score += 0.5
            terms.append(f"[能力] {cap_name}")
        if score >= min_score:
            matches.append(Match(fp_id=fp.id, fp_name=fp.name, score=score, matched_terms=terms))

    matches.sort(key=lambda m: (-m.score, m.fp_id))
    return matches[:top_n]


def map_stories(
    stories: list[UserStory],
    panorama: Panorama,
    top_n: int = DEFAULT_TOP_N,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[StoryMapping]:
    """把一组用户故事逐一映射到功能点。"""
    return [
        StoryMapping(
            story=story,
            matches=match_function_points(story.match_text(), panorama, top_n=top_n, min_score=min_score),
        )
        for story in stories
    ]


def hit_function_point_ids(mappings: list[StoryMapping]) -> list[str]:
    """汇总所有故事命中的功能点（去重、保持出现顺序）。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for mapping in mappings:
        for match in mapping.matches:
            if match.fp_id not in seen:
                seen.add(match.fp_id)
                ordered.append(match.fp_id)
    return ordered
