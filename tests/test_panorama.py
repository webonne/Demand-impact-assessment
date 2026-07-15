"""全景图加载与校验测试。"""

from pathlib import Path

import yaml

from req_insight.graph.loader import build_graph, load_panorama, validate_panorama

ROOT = Path(__file__).resolve().parents[1]
PANORAMA_DIR = ROOT / "data" / "panorama"


def test_load_sample_panorama():
    panorama = load_panorama(PANORAMA_DIR)
    assert len(panorama.domains) == 5
    assert len(panorama.systems) == 9
    assert len(panorama.entities) == 9
    fps = panorama.function_points()
    assert len(fps) >= 10
    idx = panorama.index()
    assert idx["fp-order-submit"].name == "提交订单"


def test_sample_panorama_is_valid():
    panorama = load_panorama(PANORAMA_DIR)
    errors, _warnings = validate_panorama(panorama)
    assert errors == []


def test_graph_edges():
    panorama = load_panorama(PANORAMA_DIR)
    graph = build_graph(panorama)
    # fp-pay-callback 触发 积分获取 和 发货
    targets = {e.dst for e in graph.out_edges("fp-pay-callback", "triggers")}
    assert targets == {"fp-points-earn", "fp-ship"}
    # 订单实体的读方里应包含支付单创建
    readers = {e.src for e in graph.in_edges("ent-order", "reads")}
    assert "fp-pay-create" in readers


def test_validate_detects_broken_references(tmp_path):
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
                                    {
                                        "id": "fp-x",
                                        "name": "X功能",
                                        "keywords": ["x"],
                                        "implemented_by": ["svc-missing"],
                                        "writes": ["ent-missing"],
                                        "triggers": ["fp-missing"],
                                    }
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
    (tmp_path / "systems.yaml").write_text("systems: []\nentities: []\n", encoding="utf-8")

    panorama = load_panorama(tmp_path)
    errors, _ = validate_panorama(panorama)
    joined = "\n".join(errors)
    assert "svc-missing" in joined
    assert "ent-missing" in joined
    assert "fp-missing" in joined
