#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import requests


def read_keys(path: Path) -> list[str]:
    keys = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not keys:
        raise RuntimeError("中转站 key pool is empty")
    return keys


def response_text(data: dict[str, Any]) -> str:
    return str(data["choices"][0]["message"]["content"])


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("seam audit response contains no JSON object")
    return json.loads(text[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one lightweight semantic audit for an overlap-clipped range seam.")
    parser.add_argument("--url-file", type=Path, required=True)
    parser.add_argument("--key-pool-file", type=Path, required=True)
    parser.add_argument("--key-offset", type=int, default=0)
    parser.add_argument("--single-key-only", action="store_true", help="Use only the leased key selected by --key-offset")
    parser.add_argument("--previous-timeline", type=Path, required=True)
    parser.add_argument("--current-timeline", type=Path, required=True)
    parser.add_argument("--continuity-injection", type=Path, required=True)
    parser.add_argument("--clip-manifest", type=Path, required=True)
    parser.add_argument("--range-id", required=True)
    parser.add_argument("--seam-seconds", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--endpoint", default="https://api.b.ai/v1/chat/completions")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    url_data = json.loads(args.url_file.read_text(encoding="utf-8-sig"))
    signed_url = str(url_data.get("signed_url") or "")
    if not signed_url:
        raise RuntimeError("Temporary URL file has no signed_url")
    manifest = json.loads(args.clip_manifest.read_text(encoding="utf-8-sig"))
    matches = [item for item in manifest.get("ranges") or [] if str(item.get("id")) == args.range_id]
    if len(matches) != 1:
        raise RuntimeError("clip manifest range id is missing or duplicated")
    mapping = matches[0]
    previous = json.loads(args.previous_timeline.read_text(encoding="utf-8-sig"))
    current = json.loads(args.current_timeline.read_text(encoding="utf-8-sig"))
    continuity = json.loads(args.continuity_injection.read_text(encoding="utf-8-sig"))
    if str(continuity.get("target_range_id") or "") != args.range_id:
        raise RuntimeError("continuity injection target_range_id does not match --range-id")
    if abs(float(continuity.get("source_end_seconds", -999.0)) - args.seam_seconds) > 0.02:
        raise RuntimeError("continuity injection source_end_seconds does not match --seam-seconds")
    previous_records = sorted(previous.get("records") or [], key=lambda item: float(item["end_seconds"]))
    current_records = sorted(current.get("records") or [], key=lambda item: float(item["start_seconds"]))
    if not previous_records or not current_records:
        raise RuntimeError("seam audit requires records on both sides")
    before_subject = str(previous_records[-1].get("primary_visible_subject") or "before subject")
    after_subject = str(current_records[0].get("primary_visible_subject") or "after subject")
    local_seam = args.seam_seconds - float(mapping["clip_start_seconds"])
    continuity_context = json.dumps(continuity, ensure_ascii=False, separators=(",", ":"))
    prompt = f"""You are auditing one transport seam in a short-drama video clip. The clip begins at original absolute {float(mapping['clip_start_seconds']):.3f}s. Inspect the visual transition at clip-local {local_seam:.3f}s, original absolute {args.seam_seconds:.3f}s. Decide only whether the pixels show keep_cut, keep_reframe, or merge_false. Also classify the textual state handoff as continuous_action, same_scene_cut, scene_transition, time_jump, or unclear. Use inherit_state only when the current pixels support carrying scene/character/action state forward; use new_scene for a visible scene transition or time jump; otherwise use verify_from_video. Dialogue continuity is not visual-cut or state-continuity evidence. Do not analyze the rest of the episode and do not rewrite any shot record. The following continuity injection is observation context from the immediately preceding normalized range, not authority to override the pixels: {continuity_context}. Compare its scene state, action handoff, character pose/contact, and screen order against the current range entrance. Use these exact adjacent record labels in the JSON: before_visible_subject={json.dumps(before_subject, ensure_ascii=False)}, after_visible_subject={json.dumps(after_subject, ensure_ascii=False)}. Set same_shot_evidence=true only for merge_false and explain direct pixel continuity. Return exactly one JSON object: {{"candidate_seconds":{args.seam_seconds:.3f},"decision":"keep_cut|keep_reframe|merge_false","observed_seconds":{args.seam_seconds:.3f},"same_shot_evidence":false,"seam_type":"continuous_action|same_scene_cut|scene_transition|time_jump|unclear","continuity_mode":"inherit_state|new_scene|verify_from_video","scene_match":"true|false|unclear","action_continues":"true|false|unclear","character_state_continues":"true|false|unclear","reason":"concise visible evidence"}}."""
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": signed_url}},
            {"type": "text", "text": prompt},
        ]}],
        "stream": False,
        "max_tokens": 1200,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    keys = read_keys(args.key_pool_file.resolve())
    keys = keys[args.key_offset % len(keys):] + keys[:args.key_offset % len(keys)]
    if args.single_key_only:
        keys = keys[:1]
    retryable = {429, 500, 502, 503, 504, 520, 522, 524}
    data = None
    error = ""
    for attempt, key in enumerate(keys, 1):
        response = requests.post(
            args.endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=(60, args.timeout),
        )
        if response.status_code < 400:
            data = response.json()
            break
        error = f"中转站 HTTP {response.status_code}: {response.text[:1000]}"
        if response.status_code not in retryable or attempt == len(keys):
            raise RuntimeError(error)
        time.sleep(2 * attempt + random.random())
    if data is None:
        raise RuntimeError(error or "seam audit request failed")
    text = response_text(data)
    parsed = extract_json(text)
    decision = str(parsed.get("decision") or "")
    if decision not in {"keep_cut", "keep_reframe", "merge_false"}:
        raise RuntimeError(f"invalid seam decision: {decision}")
    same_shot = bool(parsed.get("same_shot_evidence"))
    if decision == "merge_false" and not same_shot:
        raise RuntimeError("merge_false seam audit lacks same_shot_evidence")
    seam_type = str(parsed.get("seam_type") or "unclear")
    if seam_type not in {"continuous_action", "same_scene_cut", "scene_transition", "time_jump", "unclear"}:
        raise RuntimeError(f"invalid seam_type: {seam_type}")
    continuity_mode = str(parsed.get("continuity_mode") or "verify_from_video")
    if continuity_mode not in {"inherit_state", "new_scene", "verify_from_video"}:
        raise RuntimeError(f"invalid continuity_mode: {continuity_mode}")
    if seam_type in {"scene_transition", "time_jump"} and continuity_mode == "inherit_state":
        raise RuntimeError("scene transition/time jump cannot inherit prior state")
    state_flags = {}
    for field in ("scene_match", "action_continues", "character_state_continues"):
        value = parsed.get(field, "unclear")
        if isinstance(value, bool):
            value = "true" if value else "false"
        value = str(value).lower()
        if value not in {"true", "false", "unclear"}:
            raise RuntimeError(f"invalid {field}: {value}")
        state_flags[field] = value
    audit = {
        "candidate_seconds": round(args.seam_seconds, 3),
        "decision": decision,
        "observed_seconds": round(args.seam_seconds, 3),
        "before_visible_subject": before_subject,
        "after_visible_subject": after_subject,
        "same_shot_evidence": same_shot if decision == "merge_false" else False,
        "continuity_decision": {
            "seam_type": seam_type,
            "continuity_mode": continuity_mode,
            **state_flags,
        },
        "reason": str(parsed.get("reason") or "overlap clip visual seam audit"),
    }
    if decision == "merge_false" and before_subject != after_subject:
        raise RuntimeError("merge_false conflicts with different stable adjacent subjects")
    # A transport seam is owned by transport.start_seam_audit. It is not an
    # internal visual-boundary candidate and must not be inserted into
    # boundary_audit, where the compact validator would require a second
    # record boundary at the logical-core start.
    current.setdefault("transport", {})["start_seam_audit"] = audit
    current["transport"]["continuity_injection"] = str(args.continuity_injection)
    args.output.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    args.raw_output.write_text(json.dumps({"model": data.get("model") or args.model, "usage": data.get("usage", {}), "continuity_injection": str(args.continuity_injection), "text": text}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"range_id": args.range_id, "seam_seconds": args.seam_seconds, "decision": decision}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
