"""req-insight 命令行入口。

子命令：
- validate    校验业务全景图 YAML
- panorama    渲染全景图总览（mermaid）
- decompose   原始需求 → 解构产物（LLM 生成，或 --print-prompt 离线使用）
- impact      解构产物 → 影响评估报告
- run         端到端：原始需求 → 解构 → 影响评估报告
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .decompose.engine import (
    DEFAULT_MODEL,
    decompose_with_llm,
    load_artifacts,
    save_artifacts,
)
from .decompose.prompts import build_decompose_prompt
from .graph.impact import ImpactAnalyzer
from .graph.loader import build_graph, load_panorama, validate_panorama
from .graph.render import render_panorama_mermaid
from .intake.normalize import load_raw_requirement
from .matching.mapper import hit_function_point_ids, map_stories
from .report.render import render_report


def _find_panorama_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("REQ_INSIGHT_PANORAMA")
    if env:
        return Path(env)
    # 从当前目录向上找 data/panorama
    cur = Path.cwd()
    for candidate in [cur, *cur.parents]:
        p = candidate / "data" / "panorama"
        if p.is_dir():
            return p
    raise SystemExit("未找到业务全景图目录，请用 --panorama 指定（默认查找 data/panorama）")


def _write_or_print(content: str, out: str | None) -> None:
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"已写入 {path}")
    else:
        print(content)


def cmd_validate(args: argparse.Namespace) -> int:
    panorama = load_panorama(_find_panorama_dir(args.panorama))
    errors, warnings = validate_panorama(panorama)
    fps = panorama.function_points()
    print(
        f"全景图统计：{len(panorama.domains)} 个业务域 / "
        f"{sum(len(d.capabilities) for d in panorama.domains)} 个能力 / "
        f"{len(fps)} 个功能点 / {len(panorama.systems)} 个系统 / "
        f"{len(panorama.entities)} 个数据实体"
    )
    for w in warnings:
        print(f"[警告] {w}")
    for e in errors:
        print(f"[错误] {e}")
    if errors:
        return 1
    print("校验通过 ✔")
    return 0


def cmd_panorama(args: argparse.Namespace) -> int:
    panorama = load_panorama(_find_panorama_dir(args.panorama))
    mermaid = render_panorama_mermaid(panorama)
    content = f"# 业务全景图\n\n```mermaid\n{mermaid}\n```\n"
    _write_or_print(content, args.out)
    return 0


def cmd_decompose(args: argparse.Namespace) -> int:
    panorama = load_panorama(_find_panorama_dir(args.panorama))
    raw = load_raw_requirement(args.raw, source_type=args.type)

    if args.print_prompt:
        print(build_decompose_prompt(raw, panorama))
        return 0

    artifacts = decompose_with_llm(raw, panorama, model=args.model)
    out = args.out or f"{raw.id}.artifacts.yaml"
    save_artifacts(artifacts, out)
    print(f"解构完成：{len(artifacts.stories)} 条用户故事 / {len(artifacts.journeys)} 条用户旅程")
    print(f"已写入 {out}")
    return 0


def _impact_report(artifacts, panorama) -> str:
    graph = build_graph(panorama)
    mappings = map_stories(artifacts.stories, panorama)
    hit_ids = hit_function_point_ids(mappings)
    result = ImpactAnalyzer(graph).analyze(hit_ids)
    return render_report(artifacts, mappings, result, graph)


def cmd_impact(args: argparse.Namespace) -> int:
    panorama = load_panorama(_find_panorama_dir(args.panorama))
    artifacts = load_artifacts(args.artifacts)
    report = _impact_report(artifacts, panorama)
    _write_or_print(report, args.out)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    panorama = load_panorama(_find_panorama_dir(args.panorama))
    raw = load_raw_requirement(args.raw, source_type=args.type)

    if args.artifacts:
        artifacts = load_artifacts(args.artifacts)
    else:
        artifacts = decompose_with_llm(raw, panorama, model=args.model)
        artifacts_out = args.save_artifacts or f"{raw.id}.artifacts.yaml"
        save_artifacts(artifacts, artifacts_out)
        print(f"解构产物已写入 {artifacts_out}")

    report = _impact_report(artifacts, panorama)
    _write_or_print(report, args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="req-insight",
        description="需求影响评估：原始需求 → 解构产物 → 全景图匹配 → 影响面报告",
    )
    parser.add_argument("--panorama", help="业务全景图目录（默认向上查找 data/panorama）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="校验业务全景图")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("panorama", help="渲染业务全景图总览（mermaid）")
    p.add_argument("-o", "--out", help="输出文件（默认打印到 stdout）")
    p.set_defaults(func=cmd_panorama)

    p = sub.add_parser("decompose", help="原始需求 → 用户旅程/故事/泳道图")
    p.add_argument("raw", help="原始需求文件（markdown，支持 front matter）")
    p.add_argument("--type", choices=["document", "demo"], help="需求来源类型（默认自动识别）")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"LLM 模型（默认 {DEFAULT_MODEL}）")
    p.add_argument("--print-prompt", action="store_true", help="只打印提示词，不调用 LLM（离线模式）")
    p.add_argument("-o", "--out", help="解构产物 YAML 输出路径")
    p.set_defaults(func=cmd_decompose)

    p = sub.add_parser("impact", help="解构产物 → 影响评估报告")
    p.add_argument("artifacts", help="解构产物 YAML")
    p.add_argument("-o", "--out", help="报告输出路径（默认打印到 stdout）")
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser("run", help="端到端：原始需求 → 解构 → 影响评估报告")
    p.add_argument("raw", help="原始需求文件")
    p.add_argument("--type", choices=["document", "demo"], help="需求来源类型（默认自动识别）")
    p.add_argument("--artifacts", help="已有解构产物 YAML（提供则跳过 LLM 解构）")
    p.add_argument("--save-artifacts", help="LLM 解构产物保存路径")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"LLM 模型（默认 {DEFAULT_MODEL}）")
    p.add_argument("-o", "--out", help="报告输出路径（默认打印到 stdout）")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
