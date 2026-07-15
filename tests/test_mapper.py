"""用户故事 → 功能点匹配测试。"""

from pathlib import Path

from req_insight.graph.loader import load_panorama
from req_insight.matching.mapper import (
    hit_function_point_ids,
    map_stories,
    match_function_points,
)
from req_insight.models import UserStory

ROOT = Path(__file__).resolve().parents[1]
PANORAMA_DIR = ROOT / "data" / "panorama"


def _panorama():
    return load_panorama(PANORAMA_DIR)


def test_keyword_match_ranks_by_score():
    matches = match_function_points("用户下单时用积分抵扣部分金额，订单计价需要分摊", _panorama())
    assert matches, "应命中至少一个功能点"
    ids = [m.fp_id for m in matches]
    assert "fp-order-price" in ids  # 计价/抵扣/分摊 多关键词命中
    top = matches[0]
    assert top.score >= 2
    assert top.matched_terms


def test_no_match_below_threshold():
    matches = match_function_points("完全无关的一段话，聊聊天气真好", _panorama())
    assert matches == []


def test_fp_name_hit_scores_high():
    matches = match_function_points("这个需求会改动提交订单的流程", _panorama())
    assert matches[0].fp_id == "fp-order-submit"


def test_map_stories_and_collect_hits():
    stories = [
        UserStory(id="US-1", title="退款回退积分", i_want="退款时回退积分", keywords=["退款", "积分回退"]),
        UserStory(id="US-2", title="闲聊", i_want="今天天气不错"),
    ]
    mappings = map_stories(stories, _panorama())
    assert mappings[0].matched
    assert not mappings[1].matched
    hits = hit_function_point_ids(mappings)
    assert "fp-refund-money" in hits
    assert len(hits) == len(set(hits))  # 去重
