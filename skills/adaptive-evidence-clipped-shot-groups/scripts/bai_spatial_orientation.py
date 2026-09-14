#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

from bai_compact_timeline import atomic_json, extract_json, image_data_url, read_keys, response_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a focused image-only spatial orientation pass on automatic contact sheets.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--context-sheet", type=Path, action="append", required=True)
    parser.add_argument("--key-pool-file", type=Path, required=True)
    parser.add_argument("--key-offset", type=int, default=0)
    parser.add_argument("--target-start", type=float, required=True)
    parser.add_argument("--target-end", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--endpoint", default="https://api.b.ai/v1/chat/completions")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-output-tokens", type=int, default=12000)
    args = parser.parse_args()

    timeline = json.loads(args.input.read_text(encoding="utf-8-sig"))
    records = [
        record for record in (timeline.get("records") or [])
        if float(record.get("start_seconds", 0)) < args.target_end + 0.01
        and float(record.get("end_seconds", 0)) > args.target_start - 0.01
    ]
    if not records:
        raise RuntimeError("No compact record overlaps the requested spatial range")
    evidence = []
    for record in records:
        evidence.append({
            "start_seconds": record.get("start_seconds"),
            "end_seconds": record.get("end_seconds"),
            "visible_characters": [
                {
                    "identity": person.get("identity"),
                    "appearance": person.get("appearance"),
                    "screen_position": person.get("screen_position"),
                }
                for person in (record.get("visible_characters") or [])
            ],
        })

    content = []
    for sheet in args.context_sheet:
        if not sheet.exists():
            raise RuntimeError(f"Context sheet does not exist: {sheet}")
        content.append({"type": "image_url", "image_url": {"url": image_data_url(sheet)}})
    prompt = f"""你只做人物空间朝向复核，不分析剧情、台词、身份或切镜。图片是从原视频自动生成的未镜像SHOT SPACE联系图，不是人工截图。每帧红色左边框和SCREEN LEFT表示观众画面左，蓝色右边框和SCREEN RIGHT表示观众画面右。

只检查绝对时间{args.target_start:.3f}—{args.target_end:.3f}秒对应的帧。逐人先看耳朵/后脑到鼻尖的突出方向判断head_orientation，再看肩线、胸口和衣襟轴线判断torso_orientation，再看瞳孔判断gaze_direction。鼻尖向SCREEN LEFT突出必须写头部朝画面左。人物位于另一人的左/右不能证明朝向对方。物理前后只能根据占画比例、贴边裁切、透视放大和遮挡判断；贴边大幅裁切且虚焦的人物通常是极近前景，虚焦不能证明在背景。

输入记录只用于提供时间和人物标签，不得复制其中旧朝向：
{json.dumps(evidence, ensure_ascii=False)}

仅返回JSON对象：
{{"corrections":[{{"start_seconds":24.967,"end_seconds":26.900,"visible_characters":[{{"identity":"原标签","screen_position":"画面位置","torso_orientation":"正面/背面/三分之四朝画面左或右/侧身朝画面左或右/unclear","head_orientation":"头部朝画面左/右/上/下/镜头或unclear","body_orientation":"躯干与头部的合并摘要","gaze_direction":"画面方向或unclear","gaze_target":"具体人物/物件/镜头/画外位置或unclear","depth_layer":"前景|中景|背景|unclear","relative_camera_distance":"closer_than_focus|same_plane|farther_than_focus|unclear","frame_occupancy":"dominant|large|medium|small|tiny","frame_crop":"具体贴边和裁切","occlusion_relation":"遮挡谁、被谁遮挡或none/unclear","depth_evidence":"仅写占画、裁切、透视和遮挡依据","orientation_evidence":"鼻尖、耳朵、肩线、胸口或衣襟的直接证据"}}],"relative_blocking":[{{"subject":"人物A","relative_to":"人物B","horizontal_relation":"left_of|right_of|overlapping|unclear","depth_relation":"in_front_of|behind|same_plane|unclear","occlusion":"blocks|blocked_by|none|unclear","facing_relationship":"face_to_face|same_direction|back_to_back|crossing|unclear","evidence":"直接空间与朝向证据"}}]}}],"warnings":[]}}
"""
    prompt += """

Hard validation constraints: `occlusion` must be exactly one of `blocks`, `blocked_by`, `none`, or `unclear`; never output `overlapping` as an occlusion value. If subject `blocks` relative_to, subject cannot be `behind`. If subject is `blocked_by` relative_to, subject cannot be `in_front_of`. Physical contact or overlapping silhouettes alone do not prove occlusion; use `none` or `unclear` unless one body visibly hides part of the other.
"""
    content.append({"type": "text", "text": prompt})
    keys = read_keys(args.key_pool_file.resolve())
    key = keys[args.key_offset % len(keys)]
    response = requests.post(
        args.endpoint,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8"},
        data=json.dumps({
            "model": args.model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "max_tokens": args.max_output_tokens,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }, ensure_ascii=False).encode("utf-8"),
        timeout=(60, args.timeout),
    )
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    args.raw_output.write_text(response.text, encoding="utf-8")
    if response.status_code >= 400:
        raise RuntimeError(f"中转站 returned HTTP {response.status_code}")
    parsed = extract_json(response_text(response.json()))
    atomic_json(args.output, parsed)
    print(json.dumps({"status": "complete", "corrections": len(parsed.get("corrections") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
