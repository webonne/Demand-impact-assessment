"""影响面分析四层传播测试。"""

from pathlib import Path

from req_insight.graph.impact import ImpactAnalyzer
from req_insight.graph.loader import build_graph, load_panorama

ROOT = Path(__file__).resolve().parents[1]
PANORAMA_DIR = ROOT / "data" / "panorama"


def _analyze(hit_ids):
    panorama = load_panorama(PANORAMA_DIR)
    graph = build_graph(panorama)
    return ImpactAnalyzer(graph).analyze(hit_ids)


def test_direct_impact_includes_fp_and_system():
    result = _analyze(["fp-order-price"])
    direct_ids = {i.id for i in result.by_level("direct")}
    assert "fp-order-price" in direct_ids
    assert "svc-order" in direct_ids


def test_process_impact_follows_triggers():
    # 提交订单 triggers 支付单创建
    result = _analyze(["fp-order-submit"])
    process_ids = {i.id for i in result.by_level("process")}
    assert "fp-pay-create" in process_ids
    assert "svc-pay" in process_ids


def test_process_impact_multi_hop():
    # 支付回调 → 积分获取/发货（1 跳），传播有界
    result = _analyze(["fp-pay-callback"])
    process_ids = {i.id for i in result.by_level("process")}
    assert {"fp-points-earn", "fp-ship"} <= process_ids


def test_data_impact_finds_other_readers():
    # 订单计价写 ent-order；支付单创建/发货/售后申请等读 ent-order
    result = _analyze(["fp-order-price"])
    data_ids = {i.id for i in result.by_level("data")}
    assert "ent-order" in data_ids
    assert "fp-refund-apply" in data_ids


def test_dependency_impact_finds_callers():
    # svc-order 受影响 → 依赖它的 svc-pay / svc-aftersale / app-h5 为上游波及
    result = _analyze(["fp-order-price"])
    dep_ids = {i.id for i in result.by_level("dependency")}
    assert "app-h5" in dep_ids


def test_teams_and_suggestions():
    result = _analyze(["fp-order-price", "fp-points-account", "fp-refund-money"])
    assert "交易组" in result.teams
    assert "营销组" in result.teams
    assert "售后组" in result.teams
    assert any("跨" in s and "团队" in s for s in result.suggestions)
    assert any("高关键度" in s for s in result.suggestions)


def test_unknown_fp_ignored():
    result = _analyze(["fp-not-exist"])
    assert result.items == []
