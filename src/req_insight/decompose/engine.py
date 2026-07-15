"""需求解构引擎。

两种工作方式：

1. LLM 模式（decompose_with_llm）：调用 Claude 直接生成解构产物；
2. 离线模式：用 --print-prompt 拿到提示词，人工投喂任意模型（或完全人工编写），
   再把产物 YAML 交给流水线继续做影响面分析。

产物统一以 YAML 存档（load_artifacts / save_artifacts），作为需求资产沉淀。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..models import Artifacts, Panorama, RawRequirement
from .prompts import ARTIFACTS_SCHEMA, build_decompose_prompt

DEFAULT_MODEL = "claude-opus-4-8"


def _parse_glossary(text: str) -> dict[str, str]:
    glossary: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-").strip()
        if not line:
            continue
        for sep in ("：", ":"):
            if sep in line:
                term, _, meaning = line.partition(sep)
                glossary[term.strip()] = meaning.strip()
                break
    return glossary


def decompose_with_llm(
    raw: RawRequirement,
    panorama: Panorama,
    model: str = DEFAULT_MODEL,
) -> Artifacts:
    """调用 Claude 把原始需求解构为结构化产物。

    需要安装 `anthropic`（pip install req-insight[llm]）并配置好凭据
    （ANTHROPIC_API_KEY，或 `ant auth login` 登录的 profile）。
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "LLM 模式需要 anthropic SDK：pip install 'req-insight[llm]'；"
            "或改用离线模式：--print-prompt 生成提示词后人工产出 artifacts YAML"
        ) from exc

    prompt = build_decompose_prompt(raw, panorama)
    client = anthropic.Anthropic()

    with client.messages.stream(
        model=model,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": ARTIFACTS_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise RuntimeError("模型拒绝了本次请求（stop_reason=refusal），请检查需求文本内容")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("模型输出被截断（stop_reason=max_tokens），请精简需求文本后重试")

    text = next(b.text for b in message.content if b.type == "text")
    data = json.loads(text)

    artifacts = Artifacts.from_dict(
        {
            **data,
            "requirement_id": raw.id,
            "title": raw.title,
            "source_type": raw.source_type,
            "glossary": {},
        }
    )
    artifacts.glossary = _parse_glossary(data.get("glossary", ""))
    return artifacts


def save_artifacts(artifacts: Artifacts, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(artifacts.to_dict(), f, allow_unicode=True, sort_keys=False, width=100)


def load_artifacts(path: str | Path) -> Artifacts:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Artifacts.from_dict(data)
