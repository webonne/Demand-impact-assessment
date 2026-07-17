"""技术视角影响面（接口/模块投影 + 依赖收窄）测试。"""

from pathlib import Path

import yaml

from req_insight.graph.impact import ImpactAnalyzer
from req_insight.graph.loader import build_graph, load_panorama, validate_panorama

ROOT = Path(__file__).resolve().parents[1]
PANORAMA_DIR = ROOT / "data" / "panorama"


def _analyze(hit_ids, panorama_dir=PANORAMA_DIR):
    panorama = load_panorama(panorama_dir)
    graph = build_graph(panorama)
    return ImpactAnalyzer(graph).analyze(hit_ids)


# ---------------------------------------------------------------------------
# 投影：功能点 → 接口 → 模块
# ---------------------------------------------------------------------------


def test_direct_fp_projects_to_change_interface_and_module():
    result = _analyze(["fp-order-price"])
    assert result.tech.has_interface_data
    change_ids = {t.id for t in result.tech.by_scope("change")}
    assert "if-order-price" in change_ids
    module_ids = {m.id: m.scope for m in result.tech.modules}
    assert module_ids.get("mod-order-pricing") == "change"


def test_process_fp_projects_to_regression_interface():
    # 提交订单 triggers 支付单创建（process 层）→ 其接口为回归验证
    result = _analyze(["fp-order-submit"])
    scopes = {t.id: t.scope for t in result.tech.interfaces}
    assert scopes["if-order-submit"] == "change"
    assert scopes["if-order-detail"] == "change"
    assert scopes["if-pay-create"] == "regression"


def test_change_scope_wins_over_regression():
    # fp-pay-create 同时是直接命中和流程下游时，接口按「需改动」记
    result = _analyze(["fp-order-submit", "fp-pay-create"])
    scopes = {t.id: t.scope for t in result.tech.interfaces}
    assert scopes["if-pay-create"] == "change"


def test_caller_display_includes_module_granularity():
    result = _analyze(["fp-order-price"])
    itf = next(t for t in result.tech.interfaces if t.id == "if-order-price")
    assert "商城前端·结算页模块" in itf.callers


# ---------------------------------------------------------------------------
# 依赖收窄
# ---------------------------------------------------------------------------


def test_dependency_refined_by_interface_calls():
    # 商城前端的结算页模块调用了需改动接口「订单试算」→ 依赖影响带接口级依据
    result = _analyze(["fp-order-price"])
    dep = {i.id: i.reason for i in result.by_level("dependency")}
    assert "app-h5" in dep
    assert "需改动接口" in dep["app-h5"]


def _write_synthetic_panorama(tmp_path, *, fp_a3_exposes=True, with_interfaces=True):
    (tmp_path / "domains.yaml").write_text(
        yaml.safe_dump(
            {
                "domains": [
                    {
                        "id": "dom-x",
                        "name": "X域",
                        "capabilities": [
                            {
                                "id": "cap-x",
                                "name": "X能力",
                                "function_points": [
                                    {"id": "fp-a", "name": "功能A", "keywords": ["a"], "implemented_by": ["svc-a"]},
                                    {"id": "fp-a2", "name": "功能A2", "keywords": ["a2"], "implemented_by": ["svc-a"]},
                                    {"id": "fp-a3", "name": "功能A3", "keywords": ["a3"], "implemented_by": ["svc-a"]},
                                ],
                            }
                        ],
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "systems.yaml").write_text(
        yaml.safe_dump(
            {
                "systems": [
                    {"id": "svc-a", "name": "A服务", "owner": "A组"},
                    {"id": "svc-b", "name": "B服务", "owner": "B组", "depends_on": ["svc-a"]},
                    {"id": "svc-c", "name": "C服务", "owner": "C组", "depends_on": ["svc-a"]},
                    {"id": "svc-d", "name": "D服务", "owner": "D组", "depends_on": ["svc-a"]},
                ],
                "entities": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    if with_interfaces:
        interfaces = [
            {
                "id": "if-a1",
                "name": "接口A1",
                "kind": "rpc",
                "system": "svc-a",
                "exposed_by": ["fp-a"],
                "called_by": ["svc-b"],
            },
            {
                "id": "if-a2",
                "name": "接口A2",
                "kind": "rpc",
                "system": "svc-a",
                "exposed_by": ["fp-a2"],
                "called_by": ["svc-c"],
            },
        ]
        if fp_a3_exposes:
            interfaces.append(
                {
                    "id": "if-a3",
                    "name": "接口A3",
                    "kind": "rpc",
                    "system": "svc-a",
                    "exposed_by": ["fp-a3"],
                }
            )
        (tmp_path / "interfaces.yaml").write_text(
            yaml.safe_dump({"modules": [], "interfaces": interfaces}, allow_unicode=True),
            encoding="utf-8",
        )


def test_dependency_excluded_when_calls_miss_changed_interfaces(tmp_path):
    _write_synthetic_panorama(tmp_path)
    result = _analyze(["fp-a"], panorama_dir=tmp_path)
    dep_ids = {i.id for i in result.by_level("dependency")}
    # svc-b 调用了需改动接口 if-a1 → 计入；svc-c 只调 if-a2 → 排除；
    # svc-d 没有任何 calls 声明 → 降级为系统级计入
    assert "svc-b" in dep_ids
    assert "svc-c" not in dep_ids
    assert "svc-d" in dep_ids
    assert any("C服务" in text for text in result.tech.excluded_callers)


def test_partial_interface_mapping_falls_back_to_system_level(tmp_path):
    # fp-a3 没有 exposes 映射时，svc-a 的接口信息视为不完整，不做依赖收窄
    _write_synthetic_panorama(tmp_path, fp_a3_exposes=False)
    result = _analyze(["fp-a", "fp-a3"], panorama_dir=tmp_path)
    dep_ids = {i.id for i in result.by_level("dependency")}
    assert {"svc-b", "svc-c", "svc-d"} <= dep_ids
    assert result.tech.excluded_callers == []


def test_no_interface_data_degrades_gracefully(tmp_path):
    _write_synthetic_panorama(tmp_path, with_interfaces=False)
    result = _analyze(["fp-a"], panorama_dir=tmp_path)
    assert not result.tech.has_interface_data
    assert result.tech.interfaces == []
    dep_ids = {i.id for i in result.by_level("dependency")}
    assert {"svc-b", "svc-c", "svc-d"} <= dep_ids


# ---------------------------------------------------------------------------
# 技术建议
# ---------------------------------------------------------------------------


def test_mq_change_triggers_compatibility_suggestion():
    result = _analyze(["fp-pay-callback"])
    mq = [s for s in result.suggestions if "消息体兼容性" in s]
    assert mq
    assert "履约服务" in mq[0] and "积分服务" in mq[0]


def test_cross_team_interface_triggers_contract_suggestion():
    result = _analyze(["fp-order-price"])
    assert any("契约测试" in s for s in result.suggestions)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def test_validate_detects_broken_interface_references(tmp_path):
    _write_synthetic_panorama(tmp_path)
    (tmp_path / "interfaces.yaml").write_text(
        yaml.safe_dump(
            {
                "modules": [{"id": "mod-x", "name": "X模块", "system": "svc-missing"}],
                "interfaces": [
                    {
                        "id": "if-bad",
                        "name": "坏接口",
                        "kind": "graphql",
                        "system": "svc-missing",
                        "module": "mod-missing",
                        "exposed_by": ["fp-missing"],
                        "called_by": ["svc-ghost"],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    panorama = load_panorama(tmp_path)
    errors, _ = validate_panorama(panorama)
    joined = "\n".join(errors)
    assert "kind 非法" in joined
    assert "svc-missing" in joined
    assert "mod-missing" in joined
    assert "fp-missing" in joined
    assert "svc-ghost" in joined


def test_validate_warns_on_dependency_inconsistency(tmp_path):
    _write_synthetic_panorama(tmp_path)
    # svc-d 声明了 depends_on svc-a，改成让接口被一个未声明依赖的系统调用
    (tmp_path / "interfaces.yaml").write_text(
        yaml.safe_dump(
            {
                "modules": [],
                "interfaces": [
                    {
                        "id": "if-a1",
                        "name": "接口A1",
                        "kind": "rpc",
                        "system": "svc-b",
                        "exposed_by": ["fp-a"],
                        "called_by": ["svc-c"],  # svc-c 未声明 depends_on svc-b
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    panorama = load_panorama(tmp_path)
    errors, warnings = validate_panorama(panorama)
    assert errors == []
    assert any("两级依赖不一致" in w for w in warnings)


def test_sample_interfaces_are_valid():
    panorama = load_panorama(PANORAMA_DIR)
    errors, warnings = validate_panorama(panorama)
    assert errors == []
    assert not [w for w in warnings if "两级依赖不一致" in w]
