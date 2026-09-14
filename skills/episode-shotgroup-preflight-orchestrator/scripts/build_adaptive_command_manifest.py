#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


SKILLS_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ADAPTIVE = SKILLS_ROOT / "adaptive-evidence-clipped-shot-groups" / "scripts"
DEFAULT_TRAJECTORY = SKILLS_ROOT / "person-trajectory-evidence" / "scripts" / "track_people.py"
DEFAULT_NODE = Path(shutil.which("node") or "node")


def p(path: Path) -> str:
    return str(path)


def py(script: Path, *args: object) -> list[str]:
    return ["python", "-X", "utf8", p(script), *map(str, args)]


def cmd(command_id: str, argv: list[str]) -> dict:
    return {"id": command_id, "argv": argv}


def stage(name: str, kind: str, commands: list[dict], workers: int | None = None) -> dict:
    data = {"name": name, "kind": kind, "commands": commands}
    if workers is not None:
        data["workers"] = workers
    return data


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_episode(
    project: Path,
    episode: str,
    video: Path,
    preflight_root: Path,
    final_root: Path,
    asset_workbook: Path,
    key_pool: Path,
    tos_env: Path,
    adaptive_scripts: Path,
    trajectory_script: Path,
    node: Path,
    local_workers: int,
    range_workers: int,
) -> tuple[dict, Path]:
    ep_num = f"{int(''.join(ch for ch in episode if ch.isdigit()) or '1'):02d}"
    preflight_ep = preflight_root / episode
    local_prepare = preflight_ep / "adaptive_local_prepare"
    ranges_file = local_prepare / "ranges.json"
    clip_manifest = local_prepare / "clip_manifest.json"
    boundaries = local_prepare / "boundaries.json"
    probe = local_prepare / "probe.json"
    dialogue_ledger = project / "资产输出" / "04_完整台词台账" / episode / "dialogue_ledger.json"
    output = final_root / "orchestrated_auto" / episode

    for required in [video, ranges_file, clip_manifest, boundaries, dialogue_ledger, asset_workbook, key_pool, tos_env]:
        if not required.exists():
            raise RuntimeError(f"{episode}: missing required input: {required}")
    ranges_doc = load_json(ranges_file)
    clip_doc = load_json(clip_manifest)
    clips = {item["id"]: item for item in clip_doc.get("ranges", [])}
    ranges = ranges_doc.get("ranges") or []
    if not ranges:
        raise RuntimeError(f"{episode}: no ranges in {ranges_file}")
    duration = None
    if probe.exists():
        probe_doc = load_json(probe)
        videos = probe_doc.get("videos") or []
        if videos:
            duration = float(videos[0].get("duration_seconds"))
    if duration is None:
        duration = float(ranges_doc.get("duration_seconds") or clip_doc.get("source", {}).get("duration_seconds") or 0)
    if duration <= 0:
        raise RuntimeError(f"{episode}: cannot determine duration")
    if max(float(item["end_seconds"]) for item in ranges) > duration + 0.01:
        raise RuntimeError(f"{episode}: range end exceeds duration")

    output.mkdir(parents=True, exist_ok=True)
    derived_ledger = output / "dialogue_ledger.derived.json"
    derived_audit = output / "dialogue_ledger.derived.audit.json"
    key_preflight = output / "key_preflight.json"

    stages: list[dict] = [
        stage("preflight", "local", [
            cmd("derive-dialogue-ledger", py(adaptive_scripts / "derive_dialogue_ledger.py", "--input-ledger", dialogue_ledger, "--output-ledger", derived_ledger, "--audit", derived_audit)),
            cmd("key-preflight", py(adaptive_scripts / "preflight_bai_key_pool.py", "--key-pool-file", key_pool, "--output", key_preflight, "--workers", "4", "--cache-seconds", "0")),
        ], workers=min(2, local_workers)),
    ]

    buckets: dict[str, list[dict]] = {
        "dialogue": [], "context": [], "pose": [], "pose_gate": [], "trajectory": [],
        "trajectory_page": [], "evidence_pack": [], "transport": [], "primary": [],
        "validate_compact": [],
    }
    compact_inputs: list[str] = []

    for item in ranges:
        rid = str(item["id"])
        clip = clips.get(rid)
        if not clip:
            raise RuntimeError(f"{episode}: missing clip entry for {rid}")
        clip_path = Path(str(clip["clip_path"]))
        if not clip_path.exists():
            raise RuntimeError(f"{episode}: missing clip file for {rid}: {clip_path}")
        rdir = output / rid
        rdir.mkdir(parents=True, exist_ok=True)
        start = str(item["start_seconds"])
        end = str(item["end_seconds"])
        context_dir = rdir / "context"
        context_manifest = context_dir / "context_manifest.json"
        pose_dir = rdir / "pose"
        pose_manifest = pose_dir / "pose_evidence_manifest.json"
        pose_gate = rdir / "pose_gate.json"
        traj_dir = rdir / "trajectory"
        traj_json = traj_dir / "person_trajectory.json"
        traj_page = rdir / "page_05_person_trajectory.jpg"
        evidence_dir = rdir / "evidence_pack"
        evidence_manifest = evidence_dir / "evidence_pack_manifest.json"
        dialogue_injection = rdir / "dialogue_injection.json"
        tos_manifest = rdir / "tos_manifest.json"
        tos_url = rdir / "tos_signed_url.json"
        compact_json = rdir / "compact_timeline.json"
        compact_raw = rdir / "compact_timeline.raw.json"
        compact_inputs.append(p(compact_json))

        buckets["dialogue"].append(cmd(f"dialogue-{rid}", py(adaptive_scripts / "build_dialogue_injection.py", "--ledger", derived_ledger, "--start", start, "--end", end, "--output", dialogue_injection, "--context-events", "6")))
        buckets["context"].append(cmd(f"context-{rid}", py(adaptive_scripts / "build_context_sheet.py", "--input", video, "--ranges-file", ranges_file, "--boundaries-file", boundaries, "--duration", duration, "--range-start", start, "--range-end", end, "--output-dir", context_dir, "--manifest", context_manifest)))
        buckets["pose"].append(cmd(f"pose-{rid}", py(adaptive_scripts / "build_pose_evidence.py", "--input", video, "--boundaries", boundaries, "--start", start, "--end", end, "--output-dir", pose_dir)))
        buckets["pose_gate"].append(cmd(f"pose-gate-{rid}", py(adaptive_scripts / "score_pose_complexity.py", "--cv-evidence", context_manifest, "--event-manifest", pose_manifest, "--output", pose_gate)))
        buckets["trajectory"].append(cmd(f"trajectory-{rid}", py(trajectory_script, "--input", video, "--boundaries", boundaries, "--start", start, "--end", end, "--output", traj_json, "--output-dir", traj_dir)))
        buckets["trajectory_page"].append(cmd(f"trajectory-page-{rid}", py(adaptive_scripts / "assemble_trajectory_page.py", "--trajectory-json", traj_json, "--output", traj_page)))
        buckets["evidence_pack"].append(cmd(f"evidence-{rid}", py(adaptive_scripts / "assemble_adaptive_evidence_pack.py", "--range-edges", pose_dir / "range_edges.jpg", "--event-keyframes", pose_dir / "event_keyframes.jpg", "--motion-triplets", pose_dir / "motion_triplets.jpg", "--spatial-page", context_dir / "spatial_page_001.jpg", "--trajectory-page", traj_page, "--trajectory-json", traj_json, "--gate-file", pose_gate, "--pose-page", pose_dir / "pose_evidence.jpg", "--output-dir", evidence_dir, "--manifest", evidence_manifest)))
        buckets["transport"].append(cmd(f"tos-{rid}", py(adaptive_scripts / "tos_video_transport.py", "--input", clip_path, "--env-file", tos_env, "--manifest", tos_manifest, "--url-output", tos_url, "--prefix", f"codex-orchestrator-production/{project.name}/{episode}/{rid}", "--expires", "21600")))
        buckets["primary"].append(cmd(rid, ["python", "-X", "utf8", p(adaptive_scripts / "run_with_relay_lease.py"), "--preflight", p(key_preflight), "--per-key-concurrency", "1", "--global-limit", str(range_workers), "--owner", f"{episode}-{rid}-production", "--phase", "primary", "--command-attempts", "1", "--", "python", "-X", "utf8", p(adaptive_scripts / "bai_compact_timeline.py"), "--url-file", p(tos_url), "--key-pool-file", p(key_pool), "--key-offset", "{key_offset}", "--single-key-only", "--episode", ep_num, "--duration", f"{duration:.3f}", "--output", p(compact_json), "--raw-output", p(compact_raw), "--boundaries-file", p(boundaries), "--evidence-pack", p(evidence_manifest), "--assets-workbook", p(asset_workbook), "--dialogue-injection", p(dialogue_injection), "--dialogue-ledger", p(derived_ledger), "--clip-manifest", p(clip_manifest), "--range-id", rid, "--range-start", start, "--range-end", end, "--timeout", "1000", "--max-output-tokens", "30000"]))
        buckets["validate_compact"].append(cmd(f"validate-{rid}", py(adaptive_scripts / "validate_compact_timeline.py", "--input", compact_json, "--duration", f"{duration:.3f}", "--boundaries-file", boundaries, "--range-start", start, "--range-end", end)))

    stages.extend([
        stage("dialogue", "local", buckets["dialogue"], workers=min(2, local_workers)),
        stage("context", "local", buckets["context"], workers=min(2, local_workers)),
        stage("pose", "local", buckets["pose"], workers=min(2, local_workers)),
        stage("pose_gate", "local", buckets["pose_gate"], workers=min(2, local_workers)),
        stage("trajectory", "local", buckets["trajectory"], workers=min(2, local_workers)),
        stage("trajectory_page", "local", buckets["trajectory_page"], workers=min(2, local_workers)),
        stage("evidence_pack", "local", buckets["evidence_pack"], workers=min(2, local_workers)),
        stage("transport", "local", buckets["transport"], workers=min(4, range_workers)),
        stage("primary", "relay", buckets["primary"], workers=range_workers),
        stage("validate_compact", "local", buckets["validate_compact"], workers=min(2, local_workers)),
    ])
    return {"episode": episode, "stages": stages}, output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a production adaptive command manifest from orchestrator preflight outputs.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--episode", action="append", default=[])
    parser.add_argument("--video", action="append", default=[])
    parser.add_argument("--preflight-root", type=Path)
    parser.add_argument("--final-root", type=Path)
    parser.add_argument("--asset-workbook", type=Path)
    parser.add_argument("--key-pool", type=Path)
    parser.add_argument("--tos-env", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--adaptive-scripts", type=Path, default=DEFAULT_ADAPTIVE)
    parser.add_argument("--trajectory-script", type=Path, default=DEFAULT_TRAJECTORY)
    parser.add_argument("--node", type=Path, default=DEFAULT_NODE)
    parser.add_argument("--local-workers", type=int, default=2)
    parser.add_argument("--range-workers", type=int, default=4)
    args = parser.parse_args()
    project = args.project_root.resolve()
    preflight_root = (args.preflight_root or project / "资产输出" / "06_镜头组预处理调度").resolve()
    final_root = (args.final_root or project / "资产输出" / "05_自适应证据镜头组").resolve()
    asset_workbook = (args.asset_workbook or project / "资产输出" / "02_英国本地化资产" / "全剧_英国本地化资产表.xlsx").resolve()
    key_pool = (args.key_pool or project / "bai_key_pool.txt").resolve()
    videos = [Path(v).resolve() for v in args.video]
    episodes = args.episode
    if not episodes:
        episodes = sorted([p.name for p in preflight_root.iterdir() if p.is_dir() and p.name.upper().startswith("EP")])
    if not videos:
        videos = sorted([p.resolve() for p in project.iterdir() if p.suffix.lower() in {".mp4", ".mov", ".mkv"}])
    video_by_episode = {f"EP{index:02d}": video for index, video in enumerate(videos, 1)}
    manifest_episodes = []
    output_roots = {}
    for ep in episodes:
        video = video_by_episode.get(ep)
        if not video:
            raise RuntimeError(f"{ep}: no source video discovered")
        episode_manifest, episode_output = build_episode(project, ep, video, preflight_root, final_root, asset_workbook, key_pool, args.tos_env.resolve(), args.adaptive_scripts.resolve(), args.trajectory_script.resolve(), args.node.resolve(), args.local_workers, args.range_workers)
        manifest_episodes.append(episode_manifest)
        output_roots[ep] = str(episode_output)
    payload = {"schema_version": "1.0-adaptive-batch-command-manifest", "episodes": manifest_episodes, "orchestrator_output_roots": output_roots}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "episodes": episodes, "output_roots": output_roots}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
