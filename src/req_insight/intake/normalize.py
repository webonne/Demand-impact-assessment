"""原始需求接入：把不同形态的输入归一化为 RawRequirement。

支持两类来源（source_type）：

- document  常规需求文档（markdown / 纯文本）
- demo      没有文档、直接给了一个 demo 的情况 —— 输入是对 demo 的
            走查记录：页面截图描述、交互流程、可点击的元素、状态变化等

文件可带 YAML front matter 指定元信息::

    ---
    id: REQ-2026-001
    title: 订单积分抵扣
    type: document
    ---
    正文……

未显式指定时：id 取文件名（去扩展名），title 取正文第一个标题，
文件名或 front matter 含 "demo" 时自动识别为 demo 型。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..models import SOURCE_TYPES, RawRequirement


def _split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                if isinstance(meta, dict):
                    return meta, parts[2].strip()
            except yaml.YAMLError:
                pass
    return {}, text.strip()


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def load_raw_requirement(path: str | Path, source_type: str | None = None) -> RawRequirement:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    meta, body = _split_front_matter(text)

    req_id = str(meta.get("id") or path.stem)
    title = str(meta.get("title") or _first_heading(body) or path.stem)

    detected = source_type or meta.get("type") or meta.get("source_type")
    if not detected:
        detected = "demo" if "demo" in path.stem.lower() else "document"
    if detected not in SOURCE_TYPES:
        raise ValueError(f"未知的需求来源类型: {detected}（支持 {SOURCE_TYPES}）")

    return RawRequirement(
        id=req_id,
        title=title,
        source_type=detected,
        body=body,
        path=str(path),
    )
