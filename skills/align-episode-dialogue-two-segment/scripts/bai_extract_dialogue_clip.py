#!/usr/bin/env python3
"""Extract a clip-local dialogue ledger through the 中转站 multimodal relay."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from pathlib import Path
from typing import Any

import requests


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_keys(path: Path) -> list[str]:
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").replace(",", "\n").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "=" in value:
            value = value.split("=", 1)[1].strip().strip('"').strip("'")
        if value and value not in values:
            values.append(value)
    if not values:
        raise RuntimeError("中转站 key pool is empty")
    return values


def response_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("relay response has no choices")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    raise RuntimeError("relay response has no text")


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.S | re.I)
    if fence:
        cleaned = fence.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("model response is not complete JSON")
    return json.loads(cleaned[start:end + 1])


def build_prompt(character_input: dict[str, Any], episode: str, part_id: str, duration: float) -> str:
    contract = {"episode": episode, "part_id": part_id, "clip_duration_seconds": duration, "characters": character_input.get("characters") or []}
    return f"""你是短剧台词解析器。输入的是整集 EP{episode} 的一个重叠片段 {part_id}，不是完整整集。
只依赖这个片段的原始音画和人物资产，找出片段内所有文字可可靠确认的可听台词，包括短问候、称呼、应答、语气词、打断、画外音、低声和重复说话。真正模糊不清的语音忽略，不凭字幕或剧情补写。

时间规则：所有 start_seconds/end_seconds 必须是相对当前片段起点的局部秒数，范围为 [0,{duration:.3f}]；禁止猜测整集绝对时间。使用半开区间。视觉切镜不是台词边界，同一句跨镜头保持一个事件；反应镜头不能把台词转给画面最显眼人物。

人物规则：结合声音连续性、明确口型、轮流说话、人物关系和资产匹配说话人。资产人物必须使用准确 character_id 和中英文名。文字清晰但人物不确定时保留台词，并使用 speaker_id/speaker_chinese_name/speaker_english_name=unclear，填写可辨识 speaker_label 和 warning。

逐句解析真实声音表现：speech_rate 只能为 very_slow/slow/medium/fast/very_fast/unclear；intonation、timbre、emotion、rhythm_pause 必须描述可听特征；pause_profile 只记录句内可听停顿，每项含 position_ratio(0..1)、duration(micro/short/medium/long)、function(breath/hesitation/emphasis/turn/reveal/unclear)，无停顿返回空数组；delivery.confidence 为 high/medium/low。

只返回完整 JSON，不要 Markdown。顶层仅含 schema_version,episode,source,analysis,characters,events,warnings,errors。每个事件仅含 dialogue_id,start_seconds,end_seconds,speaker_id,speaker_chinese_name,speaker_english_name,speaker_label,chinese_text,delivery,evidence,confidence,warnings。evidence 只能取 audible_speech,burned_subtitle,lip_sync,turn_taking,character_context,narrative_context。dialogue_id 可使用临时连续编号，最终会在本地合并时重编号。

输入契约：{json.dumps(contract, ensure_ascii=False, separators=(',', ':'))}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-file", type=Path, required=True)
    parser.add_argument("--key-pool-file", type=Path, required=True)
    parser.add_argument("--character-input", type=Path, required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--part-id", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--source-name", default="dialogue-clip")
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--endpoint", default="https://api.b.ai/v1/chat/completions")
    parser.add_argument("--max-output-tokens", type=int, default=16000)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--key-offset", type=int, default=0)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.duration <= 0:
        raise RuntimeError("duration must be positive")
    url_data = json.loads(args.url_file.read_text(encoding="utf-8-sig"))
    signed_url = url_data.get("signed_url")
    if not signed_url:
        raise RuntimeError("temporary URL file has no signed_url")
    character_input = json.loads(args.character_input.read_text(encoding="utf-8-sig"))
    episode = str(args.episode).zfill(2)
    if str(character_input.get("episode")).zfill(2) != episode:
        raise RuntimeError("character input episode does not match")
    prompt = build_prompt(character_input, episode, args.part_id, args.duration)
    keys = read_keys(args.key_pool_file.resolve())
    offset = args.key_offset % len(keys)
    keys = keys[offset:] + keys[:offset]
    if args.validate_only:
        print(json.dumps({"status": "valid", "part_id": args.part_id, "prompt_characters": len(prompt), "key_count": len(keys)}, ensure_ascii=False))
        return 0
    payload = {"model": args.model, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": signed_url}}, {"type": "text", "text": prompt}]}],
        "stream": False, "max_tokens": args.max_output_tokens, "temperature": 0, "response_format": {"type": "json_object"}}
    retryable = {429, 500, 502, 503, 504, 520, 522, 524}
    data: dict[str, Any] | None = None
    selected_key = ""
    selected_slot = 0
    last_error = ""
    for attempt in range(max(2, len(keys))):
        selected_slot = (attempt + offset) % len(keys) + 1
        selected_key = keys[attempt % len(keys)]
        try:
            response = requests.post(args.endpoint, headers={"Authorization": f"Bearer {selected_key}", "Content-Type": "application/json; charset=utf-8"},
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=(60, args.timeout))
        except requests.RequestException as exc:
            last_error = f"中转站 request error: {exc}"
            time.sleep(min(12, 2 * (attempt + 1)) + random.random())
            continue
        if response.status_code < 400:
            try:
                data = response.json()
                break
            except ValueError as exc:
                last_error = f"中转站 returned invalid JSON: {exc}"
                time.sleep(min(12, 2 * (attempt + 1)) + random.random())
                continue
        last_error = f"中转站 HTTP {response.status_code}: {response.text[:1000]}"
        quota = response.status_code == 400 and ("insufficient_user_quota" in response.text or "credit insufficient" in response.text.lower())
        if response.status_code not in retryable and response.status_code not in {401, 403} and not quota:
            raise RuntimeError(last_error)
        time.sleep(min(12, 2 * (attempt + 1)) + random.random())
    if data is None:
        raise RuntimeError(last_error or "中转站 request failed")
    text = response_text(data)
    atomic_json(args.raw_output.resolve(), {"provider": "bai-tos-url", "model": data.get("model") or args.model, "request_id": data.get("id", ""),
                "usage": data.get("usage", {}), "key_slot": selected_slot, "key_fingerprint": hashlib.sha256(selected_key.encode()).hexdigest()[:12],
                "prompt_characters": len(prompt), "input_contract": "video-clip+character-assets", "text": text})
    parsed = extract_json(text)
    allowed_fields = {"dialogue_id", "start_seconds", "end_seconds", "speaker_id", "speaker_chinese_name", "speaker_english_name", "speaker_label", "chinese_text", "delivery", "evidence", "confidence", "warnings"}
    parsed["events"] = [{key: value for key, value in event.items() if key in allowed_fields} for event in parsed.get("events") or [] if isinstance(event, dict)]
    parsed.update({"schema_version": "2.1-video-dialogue-ledger-delivery", "episode": episode, "characters": character_input.get("characters") or []})
    parsed["source"] = {"name": args.source_name, "duration_seconds": args.duration, "part_id": args.part_id, "time_basis": "clip-local"}
    parsed["analysis"] = {"backend": "bai-tos-url-dialogue-clip", "model": data.get("model") or args.model, "input_contract": "video-clip+character-assets",
                          "interval_type": "utterance", "gaps_allowed": True, "overlaps_allowed": True, "total_dialogue_events": len(parsed["events"]),
                          "unclear_speaker_events": sum(1 for event in parsed["events"] if event.get("speaker_id") == "unclear")}
    parsed.setdefault("warnings", [])
    parsed.setdefault("errors", [])
    atomic_json(args.output.resolve(), parsed)
    print(json.dumps({"status": "complete", "part_id": args.part_id, "events": len(parsed["events"]), "key_slot": selected_slot}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
