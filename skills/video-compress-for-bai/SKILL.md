---
name: video-compress-for-bai
description: Prepare short-drama episode videos for 中转站 workflows by batch-normalizing local MP4, MOV, MKV, WEBM, AVI, or M4V files into current-project compressed MP4 copies with size targets, preserved duration/audio, natural episode ordering, and a manifest. Use before 中转站 asset, dialogue, or shot-group parsing when source videos are too large or when a project needs a clean compressed-video directory. Do not use for shot-range clipping, dialogue segmentation, or final video generation.
---

# 中转站视频压缩准备

Prepare project-local compressed episode videos for downstream 中转站 parsing skills. Treat this as a deterministic local preparation step, not as semantic video analysis.

## Inputs

Require:

- a source video directory or explicit video file list;
- a current project root;
- a writable output directory under the current project root;
- an installed FFmpeg/FFprobe, either in PATH or supplied explicitly.

Default output directory:

```text
<project_root>/资产输出/01_BAI压缩视频
```

Default target size is 10 MB per episode unless the user specifies another limit. Default behavior is to overwrite each source video after that episode has compressed successfully and passed the size check, so downstream workflows can keep using the original video directory without carrying a second compressed-input path. Failed, oversized, and dry-run rows must never replace the source file. Use `--keep-source` only when the user explicitly wants to keep originals and hand off the compressed output directory instead.

## Workflow

1. Resolve the current project root and source videos. Sort videos naturally by episode number or filename.
2. Verify every output path stays under the current project root. Stop if the requested output directory points to another project.
3. Probe each source video with FFprobe and record duration, resolution, stream availability, original size, and SHA256.
4. For each video, create a compressed `.mp4` candidate using H.264/AAC, keeping duration, aspect ratio, audio, and vertical/horizontal orientation. Do not crop. Default to height 854 and fps 24 unless the user requests otherwise. By default, after validation, replace the source file with the compressed candidate.
5. Use bitrate targeting from duration and target MB. If a result exceeds the size limit, retry with a lower safety factor before accepting. If it still exceeds the limit, keep the failed artifact for inspection and mark that episode failed in the manifest.
6. Write `video_compress_manifest.json` and `video_compress_manifest.csv` with source path, compressed candidate path, final video path, episode label, duration, original size, compressed size, target MB, resolution, fps, SHA256 before/after replacement, status, replacement status, and error if any.
7. Report only paths, counts, sizes, and failures. Do not upload videos and do not call 中转站/TOS from this skill.

## Frame-rate tradeoff under a fixed size limit

For 1–2 minute episodes that start at hundreds of MB, the tested relay target is under 10 MB. At the same duration and output size, dense multi-person shots can lose more recognizable detail than a simple one-person shot. When a source is 60 fps and this happens, compare the default 24 fps output with a `--fps 20` candidate at the same size target. Fewer encoded frames can leave more bits per frame, but may miss brief gaze, mouth, or fast-cut changes. Inspect matched timestamps in the output and original before selecting the candidate; do not claim that lower fps is always clearer. Keep the source with `--keep-source` when downstream local visual evidence must use original frames.

## Handoff contract

Downstream skills should use the compressed output directory as their video input when the user wants 中转站-friendly small files:

- `$bai-video-chinese-assets` may use this directory for whole-episode asset parsing.
- `$align-episode-dialogue-two-segment` may use compressed files only if the user accepts compressed audio/video for dialogue parsing; otherwise prefer original video for audio fidelity.
- `$episode-shotgroup-preflight-orchestrator` and `$adaptive-evidence-clipped-shot-groups` should prefer original videos for geometry/evidence unless the user explicitly chooses compressed inputs.

For whole-project orchestration, this skill can run first and hand its output directory plus manifest to later stages. It must not modify the database; use `$workbench-project-db-import` later if the compressed video directory should become a project data source.

## Safety rules

- Default mode replaces source videos after successful compression. Replace only after a successful size-checked candidate exists. Never replace failed, oversized, or dry-run rows. If the user explicitly asks to keep originals, run with `--keep-source`.
- Never write outside the current project root.
- In default overwrite mode, downstream 中转站 parsing should use the original video directory because it now contains compressed files. In `--keep-source` mode, downstream 中转站 parsing should use the compressed output directory.
- If a video is already under the target size, mark it `already_under_limit` and do not rewrite it unless the user requests forced normalization. Keep downstream ordering stable.
- Treat compression as a visual/audio tradeoff. For dialogue-critical parsing, warn when audio bitrate, source quality, or aggressive size limits may harm transcription.

## Helper script

Use the bundled script for batch compression:

```powershell
python scripts/compress_videos_for_bai.py --input-dir <source_videos> --project-root <project_root> --output-dir <project_root>/资产输出/01_BAI压缩视频 --target-mb 10 --workers 2
```

Useful options:

```powershell
python scripts/compress_videos_for_bai.py --input-dir <source_videos> --project-root <project_root> --target-mb 10 --height 854 --fps 24 --audio-kbps 64 --workers 2 --ffmpeg <ffmpeg_path> --ffprobe <ffprobe_path>

# Keep originals only when explicitly requested:
python scripts/compress_videos_for_bai.py --input-dir <source_videos> --project-root <project_root> --target-mb 10 --keep-source
```

Run `--dry-run` first when checking a new project or migration package.

## Completion criteria

Complete only when every selected episode has either `compressed_and_replaced`, `already_under_limit`, `compressed_keep_source`, or an explicit `failed` row in both manifests. In default overwrite mode, report how many source files were replaced and state that downstream stages should use the original video directory. In `--keep-source` mode, state the compressed directory that downstream stages should use.
