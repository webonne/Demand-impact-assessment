"""端到端（离线模式）测试：原始需求 + 解构产物 → 影响评估报告。"""

from pathlib import Path

from req_insight.cli import main
from req_insight.decompose.engine import load_artifacts, save_artifacts
from req_insight.decompose.prompts import build_decompose_prompt
from req_insight.graph.loader import load_panorama
from req_insight.intake.normalize import load_raw_requirement

ROOT = Path(__file__).resolve().parents[1]
PANORAMA_DIR = ROOT / "data" / "panorama"
RAW_DOC = ROOT / "examples" / "raw" / "REQ-2026-001-积分抵扣.md"
RAW_DEMO = ROOT / "examples" / "raw" / "REQ-2026-002-demo-售后进度.md"
ARTIFACTS = ROOT / "examples" / "artifacts" / "REQ-2026-001.artifacts.yaml"


def test_load_raw_document():
    raw = load_raw_requirement(RAW_DOC)
    assert raw.id == "REQ-2026-001"
    assert raw.title == "订单积分抵扣"
    assert raw.source_type == "document"
    assert "积分抵扣" in raw.body


def test_load_raw_demo_autodetect():
    raw = load_raw_requirement(RAW_DEMO)
    assert raw.source_type == "demo"


def test_decompose_prompt_variants():
    panorama = load_panorama(PANORAMA_DIR)
    doc_prompt = build_decompose_prompt(load_raw_requirement(RAW_DOC), panorama)
    demo_prompt = build_decompose_prompt(load_raw_requirement(RAW_DEMO), panorama)
    assert "需求文档" in doc_prompt
    assert "逆向还原" in demo_prompt
    # 全景图摘要注入提示词，供 LLM 对齐关键词
    assert "提交订单" in doc_prompt


def test_artifacts_yaml_roundtrip(tmp_path):
    artifacts = load_artifacts(ARTIFACTS)
    assert artifacts.requirement_id == "REQ-2026-001"
    assert len(artifacts.stories) == 4
    out = tmp_path / "roundtrip.yaml"
    save_artifacts(artifacts, out)
    again = load_artifacts(out)
    assert again.to_dict() == artifacts.to_dict()


def test_cli_run_offline_generates_report(tmp_path):
    report_path = tmp_path / "report.md"
    code = main(
        [
            "--panorama",
            str(PANORAMA_DIR),
            "run",
            str(RAW_DOC),
            "--artifacts",
            str(ARTIFACTS),
            "-o",
            str(report_path),
        ]
    )
    assert code == 0
    report = report_path.read_text(encoding="utf-8")
    # 命中的直接影响
    assert "订单计价" in report
    assert "积分账户管理" in report
    assert "退款执行" in report
    # 数据影响与依赖影响层
    assert "数据影响" in report
    assert "依赖影响" in report
    # 技术影响面：接口投影 + 接口级依赖收窄
    assert "技术影响面" in report
    assert "if-order-price" in report
    assert "需改动" in report
    assert "接口级依赖确认波及" in report
    # 跨团队建议
    assert "团队" in report
    # 泳道图与旅程
    assert "sequenceDiagram" in report
    assert "journey" in report


def test_cli_validate_and_panorama(tmp_path, capsys):
    assert main(["--panorama", str(PANORAMA_DIR), "validate"]) == 0
    captured = capsys.readouterr()
    assert "校验通过" in captured.out

    out = tmp_path / "panorama.md"
    assert main(["--panorama", str(PANORAMA_DIR), "panorama", "-o", str(out)]) == 0
    assert "flowchart LR" in out.read_text(encoding="utf-8")
