#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import mimetypes
import os
import random
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
OUTPUT_FIELDS = ["资产类型", "资产中文原名", "原始中文解析描述", "角色状态中文参考描述", "出现集号"]
VALID_TYPES = {"人物", "场景", "道具"}
VALID_KINDS = {"人物本体", "人物状态", "场景本体", "场景状态", "道具本体", "道具状态"}
TYPE_PREFIX = {"人物": "CHAR", "场景": "SCN", "道具": "PROP"}
DEFAULT_ENDPOINT = "https://api.b.ai/v1/chat/completions"
DEFAULT_EXTRACTION_MODEL = "gemini-3.6-flash"
PROMPT_VERSION = "independent-semantic-v5-two-character-audits"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"


def request_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def natural_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.stem)]


def episode_key(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"EP(\d+)", clean(value), flags=re.IGNORECASE)
    return (int(match.group(1)) if match else 999999, clean(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


WARDROBE_STATE_TERMS = (
    "服装", "造型", "穿着", "身穿", "衣", "上衣", "外套", "大衣", "披肩", "毛绒", "毛领", "皮草", "斗篷",
    "礼服", "裙", "裤", "靴", "鞋", "衬衫", "西装", "套装", "病服", "睡衣", "校服", "婚礼", "发饰",
)

WARDROBE_BOUNDARY_PATTERNS: dict[str, tuple[str, ...]] = {
    "斜肩露肩上衣": ("斜肩", "露肩", "单侧露肩", "一字肩"),
    "毛绒披肩/毛领外套": ("毛绒披肩", "毛绒大披肩", "毛领外套", "毛绒外套", "皮草外衣", "毛绒大衣"),
    "斗篷大衣": ("斗篷", "蝴蝶结大衣", "斗篷外套", "斗篷大衣"),
    "蕾丝裙装": ("蕾丝裙", "蕾丝长袖", "蕾丝花纹", "蕾丝袖"),
    "羽毛礼服": ("羽毛礼服", "羽毛发饰", "抹胸羽毛"),
    "露肩礼服": ("露肩礼服", "抹胸", "礼服"),
    "办公套装": ("办公", "小香风", "西装", "衬衫"),
    "裤装": ("长裤", "阔腿裤", "裤装", "阔腿长裤"),
    "短裙": ("短裙", "半身短裙"),
    "长裙/连衣裙": ("长裙", "连衣裙", "礼服裙"),
    "短靴": ("短靴", "白靴", "高跟短靴"),
}

WARDROBE_UPPER_PRIMARY_ORDER = (
    "斜肩露肩上衣", "羽毛礼服", "斗篷大衣", "毛绒披肩/毛领外套", "露肩礼服", "办公套装", "蕾丝裙装",
)
WARDROBE_LOWER_PRIMARY_ORDER = ("裤装", "短裙", "长裙/连衣裙")


def wardrobe_text(row: dict[str, Any]) -> str:
    parts: list[str] = [
        clean(row.get("proposed_name") or row.get("name")),
        clean(row.get("semantic_description") or row.get("description")),
    ]
    for key in ("distinguishing_features", "aliases"):
        values = row.get(key)
        if isinstance(values, list):
            parts.extend(clean(x) for x in values)
    return " ".join(part for part in parts if part)


def wardrobe_signature(row: dict[str, Any]) -> set[str]:
    text = wardrobe_text(row)
    signature: set[str] = set()
    for label, patterns in WARDROBE_BOUNDARY_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            signature.add(label)
    return signature


def first_signature(signature: set[str], order: tuple[str, ...]) -> str:
    for label in order:
        if label in signature:
            return label
    return ""


def is_wardrobe_state(row: dict[str, Any]) -> bool:
    if clean(row.get("asset_type")) != "人物" or clean(row.get("asset_kind")) != "人物状态":
        return False
    text = wardrobe_text(row)
    return any(term in text for term in WARDROBE_STATE_TERMS)


def validate_character_wardrobe_boundaries(global_assets: list[dict[str, Any]], local_by_id: dict[str, dict[str, Any]]) -> None:
    for row in global_assets:
        if clean(row.get("asset_type")) != "人物" or clean(row.get("asset_kind")) != "人物状态":
            continue
        source_rows = [local_by_id[local_id] for local_id in row["source_local_asset_ids"] if local_id in local_by_id]
        wardrobe_sources = [source for source in source_rows if is_wardrobe_state(source)]
        if len(wardrobe_sources) < 2:
            continue
        signatures = {source["local_asset_id"]: wardrobe_signature(source) for source in wardrobe_sources}
        non_empty = {local_id: signature for local_id, signature in signatures.items() if signature}
        if len(non_empty) < 2:
            continue

        upper_seen = sorted({first_signature(signature, WARDROBE_UPPER_PRIMARY_ORDER) for signature in non_empty.values()} - {""})
        lower_seen = sorted({first_signature(signature, WARDROBE_LOWER_PRIMARY_ORDER) for signature in non_empty.values()} - {""})
        conflicts: list[str] = []
        if len(upper_seen) > 1:
            conflicts.append("上装/外套结构=" + "、".join(upper_seen))
        concrete_upper = len(upper_seen) == 1 and upper_seen[0] != "办公套装"
        if len(lower_seen) > 1 and not concrete_upper:
            conflicts.append("下装结构=" + "、".join(lower_seen))
        if not conflicts:
            continue
        examples = []
        for local_id, signature in list(non_empty.items())[:8]:
            local = local_by_id[local_id]
            examples.append(f"{local_id}:{clean(local.get('proposed_name'))}({','.join(sorted(signature))})")
        raise RuntimeError(
            f"Character wardrobe-state over-merge blocked for {row['global_asset_id']} {row['name']}: "
            + "; ".join(conflicts)
            + ". Split into separate 人物状态 assets before export. Sources: "
            + " | ".join(examples)
        )


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_keys(args: argparse.Namespace) -> list[str]:
    keys: list[str] = []
    direct = clean(os.environ.get("BAI_API_KEY"))
    if direct:
        keys.append(direct)
    raw_file = args.key_pool_file or os.environ.get("BAI_KEY_POOL_FILE")
    if raw_file:
        path = Path(raw_file).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"中转站 key pool not found: {path}")
        for raw in path.read_text(encoding="utf-8-sig").replace(",", "\n").splitlines():
            value = raw.strip()
            if not value or value.startswith("#"):
                continue
            if "=" in value and value.split("=", 1)[0].strip().upper().endswith("KEY"):
                value = value.split("=", 1)[1].strip().strip('"').strip("'")
            if value and value not in keys:
                keys.append(value)
    fully_mocked = bool(args.mock_response_dir and args.mock_merge_response)
    if not keys and not fully_mocked and not args.dry_run and not args.self_test:
        raise RuntimeError("Missing 中转站 key: set BAI_API_KEY or provide --key-pool-file")
    return keys


def find_videos(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise FileNotFoundError(input_dir)
    return sorted(
        [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS],
        key=natural_key,
    )


def build_extraction_prompt(episode: str) -> str:
    return f"""你是短剧视频资产分析员。完整阅读 {episode}，只分析本集，不参考也不猜测其他剧集。

输出一个合法 JSON 对象，不要 Markdown或解释：
{{"episode":"{episode}","assets":[{{"asset_type":"人物|场景|道具","asset_kind":"人物本体|人物状态|场景本体|场景状态|道具本体|道具状态","proposed_name":"本集稳定中文候选名","semantic_description":"仅依据本集的详细中文语义描述","parent_candidate_index":0,"aliases":[],"evidence":[],"distinguishing_features":[]}}]}}

要求：
1. 人物本体写稳定身份锚点：性别呈现、年龄感、身高体型、脸型肤色、眉眼鼻口、发型发色、疤痕眼镜等；声音可辨时补充音色、口音、语速和用语；再写姿态、步态、手势、惯用手、角色关系、称谓和叙事功能。不要把临时服装绑定到人物本体。
2. 明显服装、制服、伪装、受伤、年龄时期或持续身体变化另建人物状态。状态必须复述足够身份锚点，再写服装轮廓、层次、颜色、材质、鞋和配饰。情绪、动作、机位、地点、手持物、闪回或梦境不是状态。
3. 场景是人物可进入、停留或行动的空间。写内外、用途、尺度、布局分区、楼层、出入口、走廊楼梯、相邻关系、建筑材质、固定陈设、光源、磨损、标识与叙事用途。机位不是新场景；只有火灾损毁、婚礼布置等实质持续变化才建场景状态。
4. 道具只收录被拿取、交换、操作、搜寻、损坏、作为证据或反复推动剧情的物件。写唯一/通用属性、材质、颜色、形状尺寸、结构标记、磨损、内容物、开合状态、归属位置、互动和叙事用途。持续且剧情重要的变化才建道具状态。载具是道具，发生行动的载具内部是场景。
5. parent_candidate_index 为同一 assets 数组中本体项的 1-based 序号；本体或本集未见父项时为 0。不得编造不可见文字或视频外信息。
6. 所有可辨认的说话角色或执行明确剧情动作的角色都必须建立人物本体候选，即使没有姓名、只出现一次，也要用稳定功能名命名，例如女宾客、男宾客、女佣、医生、保镖。只忽略无台词、无独立动作且无法区分的纯背景群众。
7. 输出前做一次完整覆盖复核：逐段检查每个说话人、关键行动者、场景切换，以及被特写、拿取、递交、使用或推动剧情的物件；发现遗漏必须补入 assets。每项都要有可区分语义；忽略无叙事意义的背景杂物和瞬时环境变化。"""


def build_character_audit_prompt(episode: str, accumulated_assets: list[dict[str, Any]], audit_round: int, audit_total: int) -> str:
    recognized = [
        clean(row.get("proposed_name"))
        for row in accumulated_assets
        if clean(row.get("asset_type")) == "人物" and clean(row.get("asset_kind")) == "人物本体" and clean(row.get("proposed_name"))
    ]
    focus = (
        "重点重新核对极短台词、画外音后短暂出镜、多人场面中只说一句话，以及只完成一次独立动作的人。"
        if audit_round >= 2
        else "重点核对主解析中容易被忽略的短促插话、无姓名角色和独立行动者。"
    )
    return f"""你是短剧视频人物覆盖审计员。重新完整阅读 {episode}，执行第 {audit_round}/{audit_total} 次人物补漏，只检查此前所有轮次仍遗漏的人物，不参考其他剧集。

此前所有轮次已经识别的人物本体名称：{json.dumps(recognized, ensure_ascii=False)}
{focus}

逐段完成以下复核：
1. 按每一句可听台词核对说话人，包括短促插话、画外说话后出镜的人、无姓名宾客、佣人、医生、保镖和服务人员。
2. 核对执行独立剧情动作的人，例如报信、祝酒、救人、诊治、递交或争抢物件者。
3. 对每个遗漏人物记录可见的性别呈现、年龄感、脸型五官、发型发色、体型、服装轮廓与颜色、所在场景、台词或动作证据，使用稳定功能名。
4. 不要重复此前任何轮次已经识别的人物；不要输出场景、道具或人物状态；不要把无法区分且无台词无动作的背景群众列入。

严格只输出合法 JSON，不要 Markdown 或解释：
{{"episode":"{episode}","assets":[{{"asset_type":"人物","asset_kind":"人物本体","proposed_name":"遗漏人物的稳定中文功能名","semantic_description":"详细可区分的人物描述","parent_candidate_index":0,"aliases":[],"evidence":[],"distinguishing_features":[]}}]}}
若确认没有遗漏，assets 返回空数组。"""


def candidate_name_key(value: Any) -> str:
    return re.sub(r"[\W_]+", "", clean(value).lower(), flags=re.UNICODE)


def omitted_character_bases(audit_value: dict[str, Any], accumulated_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for row in accumulated_assets:
        if clean(row.get("asset_type")) != "人物" or clean(row.get("asset_kind")) != "人物本体":
            continue
        for value in [row.get("proposed_name"), *(row.get("aliases") or [] if isinstance(row.get("aliases"), list) else [])]:
            key = candidate_name_key(value)
            if key:
                seen.add(key)
    added: list[dict[str, Any]] = []
    for raw in audit_value.get("assets", []):
        if not isinstance(raw, dict) or clean(raw.get("asset_type")) != "人物" or clean(raw.get("asset_kind")) != "人物本体":
            continue
        name_key = candidate_name_key(raw.get("proposed_name"))
        alias_keys = {
            candidate_name_key(value)
            for value in (raw.get("aliases") or [])
            if candidate_name_key(value)
        } if isinstance(raw.get("aliases"), list) else set()
        if not name_key or name_key in seen or bool(alias_keys & seen):
            continue
        row = dict(raw)
        row["parent_candidate_index"] = 0
        added.append(row)
        seen.add(name_key)
        seen.update(alias_keys)
    return added


def build_merge_prompt(candidates: list[dict[str, Any]]) -> str:
    compact = json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    return f"""你是全剧资产总监。下面是每集独立识别的全部人物、场景和道具候选。请一次性完成全剧语义归并去重。你是最终语义裁决者。

严格只输出合法 JSON：
{{"global_assets":[{{"global_asset_id":"CHAR_001|SCN_001|PROP_001","asset_type":"人物|场景|道具","asset_kind":"人物本体|人物状态|场景本体|场景状态|道具本体|道具状态","name":"全剧稳定中文名","description":"综合全部映射证据的中文描述","parent_global_asset_id":"状态所属本体ID或空字符串","aliases":[],"episodes":["EP01"],"source_local_asset_ids":["EP01_CHAR_001"]}}],"mapping":[{{"local_asset_id":"EP01_CHAR_001","global_asset_id":"CHAR_001"}}]}}

裁决规则：
1. 根据全部语义维度和剧情关系判断同一性，不得只按候选名匹配。人物可综合脸、发型、体型、声音、口音、说话习惯、姿态步态、惯用动作、身份、关系、称谓与剧情功能。
2. 人物本体与服装、制服、伪装、伤病、年龄时期等状态分开；把跨集同一状态归并。不要把情绪、动作、机位、地点、手持物、闪回或梦境当状态。
3. 服装态合并要以可见服装结构为硬边界，不能只因同一人物、同色系、同材质或同场合而合并。必须同时核对上装/外套剪裁与轮廓、层次结构、下装类型、鞋靴、主要材质纹理、标志性配饰和剧情连续性；斜肩露肩上衣+阔腿裤、白色毛绒披肩外套+短裙白靴、白色斗篷大衣、白色蕾丝裙装、白色羽毛礼服等必须拆成不同人物状态，除非证据明确证明是同一套衣服。
4. 不要因下装未完整可见、手机/手包等附带物、局部遮挡或镜头范围差异拆得过细；若主上装/外套结构一致且没有明确完整造型冲突，可合并为一个人物状态，例如斜肩露肩上衣与斜肩露肩上衣裤装可合并。
5. 也不要把“办公套装、西装、衬衫、礼服、外套、裙装”等宽泛类别当作合并依据；黑衬衫、灰西装、棕西装、酒红西装、受伤状态必须分开，除非具体颜色、剪裁、层次和配饰都证明是同一套。
6. global 人物状态的 aliases 不得把互相矛盾的服装结构藏在同一资产下；发现矛盾时拆分成更窄的状态名。
7. 场景按空间功能、布局、连接关系、结构材质、固定地标和叙事用途归并；保留实质变化的场景状态。道具按唯一性、外形材质、标记、归属、互动和剧情功能归并；保留剧情重要的持续状态。
8. 对确有依据的同一资产大胆归并；对实质不同的相似人物、空间或物品保持分离。为无姓名人物选择跨集稳定功能名。
9. 每个 local_asset_id 必须在 mapping 中恰好出现一次，也必须在对应 global asset 的 source_local_asset_ids 中恰好出现一次。不得遗漏或新增 local ID。
10. global asset 的 episodes 必须等于其所有 source local candidates 的集号并集，按集号排序。
11. 状态必须通过 parent_global_asset_id 指向同类型本体；本体 parent 为空。名称与描述均不能为空，只依据输入证据，不做英国化或英文命名。

全部单集候选：
{compact}"""


def extraction_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "episode_assets",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "episode": {"type": "string"},
                    "assets": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "asset_type": {"type": "string", "enum": sorted(VALID_TYPES)},
                            "asset_kind": {"type": "string", "enum": sorted(VALID_KINDS)},
                            "proposed_name": {"type": "string"},
                            "semantic_description": {"type": "string"},
                            "parent_candidate_index": {"type": "integer", "minimum": 0},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "distinguishing_features": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["asset_type", "asset_kind", "proposed_name", "semantic_description", "parent_candidate_index", "aliases", "evidence", "distinguishing_features"],
                        "additionalProperties": False,
                    }},
                },
                "required": ["episode", "assets"],
                "additionalProperties": False,
            },
        },
    }


def merge_schema() -> dict[str, Any]:
    asset_properties = {
        "global_asset_id": {"type": "string"}, "asset_type": {"type": "string", "enum": sorted(VALID_TYPES)},
        "asset_kind": {"type": "string", "enum": sorted(VALID_KINDS)}, "name": {"type": "string"},
        "description": {"type": "string"}, "parent_global_asset_id": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "episodes": {"type": "array", "items": {"type": "string"}},
        "source_local_asset_ids": {"type": "array", "items": {"type": "string"}},
    }
    return {"type": "json_schema", "json_schema": {"name": "global_assets", "strict": True, "schema": {
        "type": "object", "properties": {
            "global_assets": {"type": "array", "items": {"type": "object", "properties": asset_properties, "required": list(asset_properties), "additionalProperties": False}},
            "mapping": {"type": "array", "items": {"type": "object", "properties": {"local_asset_id": {"type": "string"}, "global_asset_id": {"type": "string"}}, "required": ["local_asset_id", "global_asset_id"], "additionalProperties": False}},
        }, "required": ["global_assets", "mapping"], "additionalProperties": False,
    }}}


def video_data_url(path: Path, max_mb: float) -> str:
    size = path.stat().st_size
    if max_mb > 0 and size > max_mb * 1024 * 1024:
        raise RuntimeError(f"Video exceeds inline limit: {path.name} is {size / 1048576:.2f} MB; limit {max_mb:.2f} MB")
    mime = mimetypes.guess_type(str(path))[0] or "video/mp4"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def response_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    raise RuntimeError("中转站 response content is empty")


def post_chat(messages: list[dict[str, Any]], model: str, key: str, args: argparse.Namespace, schema: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "max_tokens": args.max_output_tokens, "temperature": args.temperature}
    if args.response_format == "json_schema":
        payload["response_format"] = schema
    elif args.response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    retryable = {429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(1, args.retry_attempts + 1):
        request = urllib.request.Request(args.endpoint, data=body, headers=request_headers(key), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
                return {"text": response_text(data), "provider": "bai", "model": clean(data.get("model")) or model, "request_id": clean(data.get("id")), "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {}}
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", errors="replace")
            last_error = RuntimeError(f"中转站 HTTP {exc.code}: {detail}")
            if exc.code not in retryable or attempt >= args.retry_attempts:
                raise last_error
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = RuntimeError(f"中转站 network error: {exc}")
            if attempt >= args.retry_attempts:
                raise last_error
        delay = args.retry_base_seconds * (2 ** (attempt - 1))
        time.sleep(delay + random.uniform(0, min(1.0, delay * 0.1)))
    raise last_error or RuntimeError("中转站 request failed")


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Response does not contain a JSON object")
        value = json.loads(stripped[start:end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("Response JSON root must be an object")
    return value


def validate_episode_output(value: dict[str, Any], episode: str) -> list[dict[str, Any]]:
    assets = value.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError(f"{episode}: response must contain assets array")
    output: list[dict[str, Any]] = []
    counters = {asset_type: 0 for asset_type in VALID_TYPES}
    for index, raw in enumerate(assets, start=1):
        if not isinstance(raw, dict):
            raise RuntimeError(f"{episode}: asset {index} is not an object")
        asset_type, asset_kind = clean(raw.get("asset_type")), clean(raw.get("asset_kind"))
        name, description = clean(raw.get("proposed_name")), clean(raw.get("semantic_description"))
        if asset_type not in VALID_TYPES or asset_kind not in VALID_KINDS or not asset_kind.startswith(asset_type):
            raise RuntimeError(f"{episode}: invalid type/kind at asset {index}")
        if not name or not description:
            raise RuntimeError(f"{episode}: name/description required at asset {index}")
        parent_index = raw.get("parent_candidate_index", 0)
        if not isinstance(parent_index, int) or parent_index < 0 or parent_index >= index:
            raise RuntimeError(f"{episode}: invalid parent_candidate_index at asset {index}")
        counters[asset_type] += 1
        local_id = f"{episode}_{TYPE_PREFIX[asset_type]}_{counters[asset_type]:03d}"
        parent_local_id = ""
        if parent_index:
            parent = output[parent_index - 1]
            if parent["asset_type"] != asset_type or not parent["asset_kind"].endswith("本体"):
                raise RuntimeError(f"{episode}: parent type/kind mismatch at asset {index}")
            parent_local_id = parent["local_asset_id"]
        output.append({
            "local_asset_id": local_id, "asset_type": asset_type, "asset_kind": asset_kind,
            "proposed_name": name, "semantic_description": description, "parent_local_asset_id": parent_local_id,
            "aliases": [clean(x) for x in raw.get("aliases", []) if clean(x)] if isinstance(raw.get("aliases", []), list) else [],
            "evidence": [clean(x) for x in raw.get("evidence", []) if clean(x)] if isinstance(raw.get("evidence", []), list) else [],
            "distinguishing_features": [clean(x) for x in raw.get("distinguishing_features", []) if clean(x)] if isinstance(raw.get("distinguishing_features", []), list) else [],
            "episode": episode,
        })
    return output


def models_endpoint(args: argparse.Namespace) -> str:
    explicit = clean(os.environ.get("BAI_MODELS_ENDPOINT"))
    if explicit:
        return explicit
    parsed = urllib.parse.urlsplit(args.endpoint)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/v1/models", "", ""))


def list_models(key: str, args: argparse.Namespace) -> list[str]:
    request = urllib.request.Request(models_endpoint(args), headers=request_headers(key), method="GET")
    with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("中转站 /v1/models response has no data array")
    return [clean(row.get("id")) for row in rows if isinstance(row, dict) and clean(row.get("id"))]


def model_rank(model_id: str) -> tuple[tuple[int, ...], str]:
    lower = model_id.lower()
    numbers = tuple(int(x) for x in re.findall(r"\d+", lower))
    return (numbers, lower)


def select_merge_model(keys: list[str], args: argparse.Namespace) -> tuple[str, list[str]]:
    available = list_models(keys[0], args)
    requested = clean(args.merge_model)
    if requested:
        if requested not in available:
            raise RuntimeError(f"Requested merge model is unavailable: {requested}. Available: {', '.join(available)}")
        return requested, available
    pro_models = [model for model in available if "gemini" in model.lower() and "pro" in model.lower()]
    if not pro_models:
        raise RuntimeError(f"No Pro model available. Account models: {', '.join(available)}")
    return max(pro_models, key=model_rank), available


def extract_one(episode: str, video: Path, key: str, args: argparse.Namespace, response_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if args.mock_response_dir:
        raw_text = (args.mock_response_dir / f"{episode}.json").read_text(encoding="utf-8-sig")
        provider = {"text": raw_text, "provider": "mock", "model": "mock", "request_id": "", "usage": {}}
        combined_value = extract_json(raw_text)
    else:
        video_url = video_data_url(video, args.max_inline_video_mb)
        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": video_url}},
            {"type": "text", "text": build_extraction_prompt(episode)},
        ]}]
        provider = post_chat(messages, args.model, key, args, extraction_schema())
        raw_text = provider["text"]
        primary_value = extract_json(raw_text)
        primary_assets = primary_value.get("assets") if isinstance(primary_value.get("assets"), list) else []
        accumulated_assets = list(primary_assets)
        character_audits: list[dict[str, Any]] = []
        for audit_index in range(args.character_audit_passes):
            audit_round = audit_index + 1
            audit_messages = [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": video_url}},
                {"type": "text", "text": build_character_audit_prompt(episode, accumulated_assets, audit_round, args.character_audit_passes)},
            ]}]
            audit_provider = post_chat(audit_messages, args.model, key, args, extraction_schema())
            audit_value = extract_json(audit_provider["text"])
            audit_assets = omitted_character_bases(audit_value, accumulated_assets)
            accumulated_assets.extend(audit_assets)
            character_audits.append({
                "round": audit_round,
                "provider": audit_provider.get("provider"),
                "model": audit_provider.get("model"),
                "request_id": audit_provider.get("request_id"),
                "usage": audit_provider.get("usage", {}),
                "text": audit_provider.get("text"),
                "recognized_character_count_before": len([
                    row for row in accumulated_assets[:-len(audit_assets) or None]
                    if clean(row.get("asset_type")) == "人物" and clean(row.get("asset_kind")) == "人物本体"
                ]),
                "added_candidate_count": len(audit_assets),
            })
        combined_value = {"episode": episode, "assets": accumulated_assets}
        provider["primary_text"] = raw_text
        provider["character_audits"] = character_audits
        provider["text"] = json.dumps(combined_value, ensure_ascii=False)
    atomic_json(response_path, {"episode": episode, "provider": provider.get("provider"), "model": provider.get("model"), "request_id": provider.get("request_id"), "usage": provider.get("usage", {}), "primary_text": provider.get("primary_text", provider.get("text")), "character_audits": provider.get("character_audits", []), "text": provider.get("text")})
    assets = validate_episode_output(combined_value, episode)
    return provider, assets


def validate_global_merge(value: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    globals_raw, mapping_raw = value.get("global_assets"), value.get("mapping")
    if not isinstance(globals_raw, list) or not isinstance(mapping_raw, list):
        raise RuntimeError("Global merge requires global_assets and mapping arrays")
    local_by_id = {row["local_asset_id"]: row for row in candidates}
    if len(local_by_id) != len(candidates):
        raise RuntimeError("Duplicate local_asset_id in candidates")
    global_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(globals_raw, start=1):
        if not isinstance(raw, dict):
            raise RuntimeError(f"Global asset {index} is not an object")
        gid, asset_type, kind = clean(raw.get("global_asset_id")), clean(raw.get("asset_type")), clean(raw.get("asset_kind"))
        name, description = clean(raw.get("name")), clean(raw.get("description"))
        if not gid or gid in global_by_id or asset_type not in VALID_TYPES or kind not in VALID_KINDS or not kind.startswith(asset_type) or not name or not description:
            raise RuntimeError(f"Invalid global asset {index}")
        source_ids = raw.get("source_local_asset_ids")
        episodes = raw.get("episodes")
        if not isinstance(source_ids, list) or not source_ids or len(source_ids) != len(set(source_ids)) or not isinstance(episodes, list):
            raise RuntimeError(f"Invalid source IDs/episodes for {gid}")
        row = {
            "global_asset_id": gid, "asset_type": asset_type, "asset_kind": kind, "name": name, "description": description,
            "parent_global_asset_id": clean(raw.get("parent_global_asset_id")),
            "aliases": [clean(x) for x in raw.get("aliases", []) if clean(x)] if isinstance(raw.get("aliases", []), list) else [],
            "episodes": sorted(set(clean(x).upper() for x in episodes if clean(x)), key=episode_key),
            "source_local_asset_ids": [clean(x) for x in source_ids],
        }
        global_by_id[gid] = row
    mapping: dict[str, str] = {}
    for raw in mapping_raw:
        if not isinstance(raw, dict):
            raise RuntimeError("Mapping row is not an object")
        local_id, global_id = clean(raw.get("local_asset_id")), clean(raw.get("global_asset_id"))
        if local_id in mapping:
            raise RuntimeError(f"Local ID mapped more than once: {local_id}")
        mapping[local_id] = global_id
    missing, extra = sorted(set(local_by_id) - set(mapping)), sorted(set(mapping) - set(local_by_id))
    if missing or extra:
        raise RuntimeError(f"Mapping coverage mismatch; missing={missing[:10]}, extra={extra[:10]}")
    for local_id, global_id in mapping.items():
        if global_id not in global_by_id:
            raise RuntimeError(f"Mapped global ID does not exist: {global_id}")
    source_owner: dict[str, str] = {}
    for gid, row in global_by_id.items():
        for local_id in row["source_local_asset_ids"]:
            if local_id in source_owner:
                raise RuntimeError(f"Source local ID listed more than once: {local_id}")
            source_owner[local_id] = gid
            if local_id not in local_by_id or mapping.get(local_id) != gid:
                raise RuntimeError(f"Source list disagrees with mapping: {local_id}")
            if local_by_id[local_id]["asset_type"] != row["asset_type"]:
                raise RuntimeError(f"Asset type mismatch for {local_id}")
        expected_episodes = sorted({local_by_id[x]["episode"] for x in row["source_local_asset_ids"]}, key=episode_key)
        if row["episodes"] != expected_episodes:
            raise RuntimeError(f"Episode list mismatch for {gid}: expected {expected_episodes}")
    if set(source_owner) != set(local_by_id):
        raise RuntimeError("Global source lists do not cover every local ID")
    for gid, row in global_by_id.items():
        parent_id = row["parent_global_asset_id"]
        is_state = row["asset_kind"].endswith("状态")
        if is_state and (not parent_id or parent_id not in global_by_id):
            raise RuntimeError(f"State has no valid parent: {gid}")
        if not is_state and parent_id:
            raise RuntimeError(f"Base asset must not have a parent: {gid}")
        if parent_id and (parent_id == gid or global_by_id[parent_id]["asset_type"] != row["asset_type"] or not global_by_id[parent_id]["asset_kind"].endswith("本体")):
            raise RuntimeError(f"Invalid parent relation: {gid} -> {parent_id}")
    validate_character_wardrobe_boundaries(list(global_by_id.values()), local_by_id)
    return list(global_by_id.values())


def character_references(assets: list[dict[str, Any]]) -> dict[str, str]:
    groups: dict[str, list[str]] = {}
    for row in assets:
        if row["asset_type"] != "人物":
            continue
        root = row["parent_global_asset_id"] or row["global_asset_id"]
        groups.setdefault(root, []).append(row["name"])
    return {row["global_asset_id"]: "；".join(dict.fromkeys(groups.get(row["parent_global_asset_id"] or row["global_asset_id"], []))) for row in assets if row["asset_type"] == "人物"}


def export_csv(path: Path, assets: list[dict[str, Any]]) -> None:
    refs = character_references(assets)
    rows = [{
        "资产类型": row["asset_type"], "资产中文原名": row["name"], "原始中文解析描述": row["description"],
        "角色状态中文参考描述": refs.get(row["global_asset_id"], "") if row["asset_type"] == "人物" else "",
        "出现集号": "、".join(row["episodes"]),
    } for row in assets]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_self_test() -> int:
    primary_for_audit = [
        {"asset_type": "人物", "asset_kind": "人物本体", "proposed_name": "男主", "aliases": ["总裁"]},
        {"asset_type": "场景", "asset_kind": "场景本体", "proposed_name": "办公室", "aliases": []},
    ]
    audit_one = {"assets": [
        {"asset_type": "人物", "asset_kind": "人物本体", "proposed_name": "总裁", "semantic_description": "重复人物", "parent_candidate_index": 0, "aliases": [], "evidence": [], "distinguishing_features": []},
        {"asset_type": "人物", "asset_kind": "人物本体", "proposed_name": "女宾客", "semantic_description": "说过一句祝酒词的女宾客", "parent_candidate_index": 0, "aliases": [], "evidence": [], "distinguishing_features": []},
    ]}
    added_one = omitted_character_bases(audit_one, primary_for_audit)
    audit_two = {"assets": [
        {"asset_type": "人物", "asset_kind": "人物本体", "proposed_name": "女宾客", "semantic_description": "重复人物", "parent_candidate_index": 0, "aliases": [], "evidence": [], "distinguishing_features": []},
        {"asset_type": "人物", "asset_kind": "人物本体", "proposed_name": "急救医生", "semantic_description": "短暂出镜并下达医嘱的医生", "parent_candidate_index": 0, "aliases": [], "evidence": [], "distinguishing_features": []},
        {"asset_type": "道具", "asset_kind": "道具本体", "proposed_name": "听诊器", "semantic_description": "错误类型", "parent_candidate_index": 0, "aliases": [], "evidence": [], "distinguishing_features": []},
    ]}
    added_two = omitted_character_bases(audit_two, primary_for_audit + added_one)
    if [row["proposed_name"] for row in added_one + added_two] != ["女宾客", "急救医生"]:
        raise AssertionError("Two-round character audit accumulation or duplicate filtering failed")
    ep1 = validate_episode_output({"episode": "EP01", "assets": [
        {"asset_type": "人物", "asset_kind": "人物本体", "proposed_name": "西装男子", "semantic_description": "二十多岁男子，黑色短发，清晰下颌线。", "parent_candidate_index": 0, "aliases": ["何先生"], "evidence": ["00:01"], "distinguishing_features": ["黑色短发"]},
        {"asset_type": "人物", "asset_kind": "人物状态", "proposed_name": "西装男子-灰色西装", "semantic_description": "同一男子穿灰色三件套西装。", "parent_candidate_index": 1, "aliases": [], "evidence": ["00:03"], "distinguishing_features": ["灰色三件套"]},
        {"asset_type": "场景", "asset_kind": "场景本体", "proposed_name": "设计公司办公室", "semantic_description": "开放式现代办公室。", "parent_candidate_index": 0, "aliases": [], "evidence": ["00:04"], "distinguishing_features": ["开放工位"]},
    ]}, "EP01")
    ep2 = validate_episode_output({"episode": "EP02", "assets": [
        {"asset_type": "人物", "asset_kind": "人物本体", "proposed_name": "何工", "semantic_description": "二十多岁男子，黑色短发，清晰下颌线，说话沉稳。", "parent_candidate_index": 0, "aliases": [], "evidence": ["00:02"], "distinguishing_features": ["下颌线清晰"]},
        {"asset_type": "道具", "asset_kind": "道具本体", "proposed_name": "设计图纸", "semantic_description": "白色大幅建筑设计图。", "parent_candidate_index": 0, "aliases": [], "evidence": ["00:07"], "distinguishing_features": ["大幅图纸"]},
    ]}, "EP02")
    candidates = ep1 + ep2
    merged = {"global_assets": [
        {"global_asset_id": "CHAR_001", "asset_type": "人物", "asset_kind": "人物本体", "name": "何深", "description": "二十多岁黑色短发男子，下颌线清晰，说话沉稳。", "parent_global_asset_id": "", "aliases": ["何先生", "何工"], "episodes": ["EP01", "EP02"], "source_local_asset_ids": ["EP01_CHAR_001", "EP02_CHAR_001"]},
        {"global_asset_id": "CHAR_002", "asset_type": "人物", "asset_kind": "人物状态", "name": "何深-灰色西装", "description": "何深穿灰色三件套西装。", "parent_global_asset_id": "CHAR_001", "aliases": [], "episodes": ["EP01"], "source_local_asset_ids": ["EP01_CHAR_002"]},
        {"global_asset_id": "SCN_001", "asset_type": "场景", "asset_kind": "场景本体", "name": "设计公司办公室", "description": "开放式现代办公室。", "parent_global_asset_id": "", "aliases": [], "episodes": ["EP01"], "source_local_asset_ids": ["EP01_SCN_001"]},
        {"global_asset_id": "PROP_001", "asset_type": "道具", "asset_kind": "道具本体", "name": "设计图纸", "description": "白色大幅建筑设计图。", "parent_global_asset_id": "", "aliases": [], "episodes": ["EP02"], "source_local_asset_ids": ["EP02_PROP_001"]},
    ], "mapping": [
        {"local_asset_id": "EP01_CHAR_001", "global_asset_id": "CHAR_001"}, {"local_asset_id": "EP01_CHAR_002", "global_asset_id": "CHAR_002"},
        {"local_asset_id": "EP01_SCN_001", "global_asset_id": "SCN_001"}, {"local_asset_id": "EP02_CHAR_001", "global_asset_id": "CHAR_001"},
        {"local_asset_id": "EP02_PROP_001", "global_asset_id": "PROP_001"},
    ]}
    assets = validate_global_merge(merged, candidates)
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "全剧_中文资产解析表.csv"
        export_csv(output, assets)
        rows = list(csv.DictReader(output.open("r", encoding="utf-8-sig", newline="")))
        if list(rows[0]) != OUTPUT_FIELDS or len(rows) != 4 or "何深-灰色西装" not in rows[0]["角色状态中文参考描述"]:
            raise AssertionError("Five-column export contract failed")
    print("Self-test passed: two-round character audit, independent candidates, complete global mapping, five-column export")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse episodes independently through 中转站, then merge locally by default or optionally through 中转站 Pro")
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--key-pool-file", type=Path)
    parser.add_argument("--endpoint", default=os.environ.get("BAI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default=os.environ.get("BAI_MODEL", DEFAULT_EXTRACTION_MODEL))
    parser.add_argument("--merge-model", default=os.environ.get("BAI_MERGE_MODEL", ""))
    parser.add_argument("--merge-mode", choices=["local", "pro"], default="local")
    parser.add_argument("--local-merge-response", type=Path, help="Codex-authored global merge JSON to validate and export in local mode")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--character-audit-passes", type=int, default=int(os.environ.get("BAI_CHARACTER_AUDIT_PASSES", "2")), help="Same-episode character-only coverage audits after primary extraction (default: 2)")
    parser.add_argument("--max-inline-video-mb", type=float, default=float(os.environ.get("BAI_MAX_INLINE_VIDEO_MB", "20")))
    parser.add_argument("--max-output-tokens", type=int, default=65536)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--timeout-seconds", type=int, default=1000)
    parser.add_argument("--retry-attempts", type=int, default=3)
    parser.add_argument("--retry-base-seconds", type=float, default=5.0)
    parser.add_argument("--response-format", choices=["json_schema", "json_object", "none"], default="json_schema")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--end-index", type=int)
    parser.add_argument("--mock-response-dir", type=Path)
    parser.add_argument("--mock-merge-response", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if not args.input_dir or not args.output_dir:
        raise RuntimeError("--input-dir and --output-dir are required")
    if not str(args.endpoint).lower().startswith("https://") or args.concurrency < 1:
        raise RuntimeError("中转站 endpoint must use HTTPS and concurrency must be positive")
    if args.character_audit_passes < 0 or args.character_audit_passes > 5:
        raise RuntimeError("--character-audit-passes must be between 0 and 5")
    videos = find_videos(args.input_dir.resolve())
    if not videos:
        raise RuntimeError("No supported video files found")
    end_index = args.end_index or len(videos)
    selected = [(index, video) for index, video in enumerate(videos, start=1) if args.start_index <= index <= end_index]
    if not selected:
        raise RuntimeError("Episode selection is empty")
    keys = read_keys(args)
    output_dir = args.output_dir.resolve()
    candidate_dir, response_dir = output_dir / "episode_candidates", output_dir / "responses"
    manifest_path = output_dir / "manifest.json"
    manifest = load_json(manifest_path, {"provider": "bai", "prompt_version": PROMPT_VERSION, "episodes": {}})
    manifest.update({"provider": "bai", "extraction_model": args.model, "prompt_version": PROMPT_VERSION, "concurrency": args.concurrency, "character_audit_passes": args.character_audit_passes})
    manifest.setdefault("episodes", {})
    pending: list[tuple[int, str, Path, str]] = []
    all_assets_by_episode: dict[str, list[dict[str, Any]]] = {}
    for position, (index, video) in enumerate(selected):
        episode, digest = f"EP{index:02d}", sha256_file(video)
        size_mb = video.stat().st_size / 1048576
        print(f"{episode} {video.name} {size_mb:.2f} MB")
        if args.max_inline_video_mb > 0 and size_mb > args.max_inline_video_mb:
            raise RuntimeError(f"{episode} exceeds --max-inline-video-mb")
        candidate_path = candidate_dir / f"{episode}.json"
        previous = manifest["episodes"].get(episode, {})
        reusable = previous.get("status") == "complete" and previous.get("sha256") == digest and previous.get("model") == args.model and previous.get("prompt_version") == PROMPT_VERSION and previous.get("character_audit_passes") == args.character_audit_passes and candidate_path.exists()
        if reusable:
            saved = load_json(candidate_path, {})
            all_assets_by_episode[episode] = saved.get("assets", [])
            print("  extraction already complete; source hash and prompt match")
        else:
            pending.append((position, episode, video, digest))
            manifest["episodes"][episode] = {"status": "planned" if args.dry_run else "pending", "source": str(video.resolve()), "sha256": digest, "size_bytes": video.stat().st_size, "model": args.model, "prompt_version": PROMPT_VERSION, "character_audit_passes": args.character_audit_passes}
    atomic_json(manifest_path, manifest)
    if args.dry_run:
        print(f"Planned {len(selected)} episodes; {len(pending)} require extraction")
        return 0
    errors: list[str] = []
    execution_keys = keys or ["mock"]
    response_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=min(args.concurrency, max(1, len(pending)))) as pool:
        futures = {pool.submit(extract_one, episode, video, execution_keys[position % len(execution_keys)], args, response_dir / f"{episode}.json"): (episode, video, digest) for position, episode, video, digest in pending}
        for future in as_completed(futures):
            episode, video, digest = futures[future]
            try:
                provider, assets = future.result()
                response_path = response_dir / f"{episode}.json"
                atomic_json(response_path, {"episode": episode, "provider": provider.get("provider"), "model": provider.get("model"), "request_id": provider.get("request_id"), "usage": provider.get("usage", {}), "primary_text": provider.get("primary_text", provider.get("text")), "character_audits": provider.get("character_audits", []), "text": provider.get("text"), "parsed_assets": assets})
                candidate_path = candidate_dir / f"{episode}.json"
                atomic_json(candidate_path, {"episode": episode, "model": provider.get("model"), "prompt_version": PROMPT_VERSION, "assets": assets})
                all_assets_by_episode[episode] = assets
                manifest["episodes"][episode] = {"status": "complete", "source": str(video.resolve()), "sha256": digest, "size_bytes": video.stat().st_size, "model": args.model, "prompt_version": PROMPT_VERSION, "character_audit_passes": args.character_audit_passes, "candidate_file": str(candidate_path), "response": str(response_path)}
                print(f"  {episode} complete: {len(assets)} independent candidates")
            except Exception as exc:
                manifest["episodes"][episode]["status"] = "failed"
                manifest["episodes"][episode]["error"] = clean(exc)[:2000]
                errors.append(f"{episode}: {exc}")
            atomic_json(manifest_path, manifest)
    if errors:
        raise RuntimeError("Episode extraction failed; global merge not run:\n" + "\n".join(errors))
    ordered_episodes = [f"EP{index:02d}" for index, _ in selected]
    candidates = [asset for episode in ordered_episodes for asset in all_assets_by_episode.get(episode, [])]
    if not candidates:
        raise RuntimeError("No episode candidates were produced")
    combined = {"prompt_version": PROMPT_VERSION, "episodes": ordered_episodes, "assets": candidates}
    combined_path = output_dir / "全剧_单集资产候选.json"
    atomic_json(combined_path, combined)
    candidate_hash = sha256_json(combined)
    if args.merge_mode == "local" and not args.local_merge_response:
        manifest["merge"] = {
            "status": "awaiting_local_semantic_merge",
            "method": "codex_local_skill_semantic_merge",
            "candidate_sha256": candidate_hash,
            "candidate_count": len(candidates),
            "candidate_file": str(combined_path),
        }
        atomic_json(manifest_path, manifest)
        print(f"Local semantic merge ready: {len(candidates)} candidates")
        print(f"Author a complete global merge JSON, then rerun with --local-merge-response PATH: {combined_path}")
        return 0
    if args.merge_mode == "local":
        parsed_merge = load_json(args.local_merge_response.resolve(), {})
        merge_model, available_models = "codex-local-skill", []
        merge_response_path = args.local_merge_response.resolve()
    elif args.mock_merge_response:
        merge_model, available_models = "mock-pro", []
        raw_text = args.mock_merge_response.read_text(encoding="utf-8-sig")
        provider = {"text": raw_text, "provider": "mock", "model": merge_model, "request_id": "", "usage": {}}
    else:
        merge_model, available_models = select_merge_model(keys, args)
        provider = post_chat([{"role": "user", "content": build_merge_prompt(candidates)}], merge_model, keys[0], args, merge_schema())
        raw_text = provider["text"]
    if args.merge_mode == "pro":
        merge_response_path = response_dir / "global_merge_response.json"
        atomic_json(merge_response_path, {"provider": provider.get("provider"), "model": provider.get("model"), "request_id": provider.get("request_id"), "usage": provider.get("usage", {}), "text": raw_text})
        parsed_merge = extract_json(raw_text)
    global_assets = validate_global_merge(parsed_merge, candidates)
    global_merge_path = output_dir / "global_merge.json"
    atomic_json(global_merge_path, parsed_merge)
    atomic_json(output_dir / "asset_state.json", global_assets)
    csv_path = output_dir / "全剧_中文资产解析表.csv"
    export_csv(csv_path, global_assets)
    merge_method = "codex_local_skill_semantic_merge" if args.merge_mode == "local" else "bai_pro_semantic_merge"
    manifest["merge"] = {"status": "complete", "method": merge_method, "model": merge_model, "available_models": available_models, "candidate_sha256": candidate_hash, "candidate_count": len(candidates), "global_asset_count": len(global_assets), "global_merge": str(global_merge_path), "response": str(merge_response_path)}
    atomic_json(manifest_path, manifest)
    print(f"One global merge complete with {merge_model}: {len(candidates)} candidates -> {len(global_assets)} assets")
    print(f"Wrote: {csv_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
