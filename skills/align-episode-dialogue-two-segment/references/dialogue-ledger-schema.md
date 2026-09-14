# Dialogue ledger schema

## Canonical JSON

```json
{
  "schema_version": "2.1-video-dialogue-ledger-delivery",
  "episode": "09",
  "source": {
    "name": "009.mp4",
    "fingerprint": "sha256:...",
    "duration_seconds": 60.7
  },
  "analysis": {
    "backend": "bai-tos-url",
    "model": "gemini-3.6-flash",
    "input_contract": "video+character-assets",
    "interval_type": "utterance",
    "gaps_allowed": true,
    "overlaps_allowed": true,
    "total_dialogue_events": 1,
    "unclear_speaker_events": 0
  },
  "characters": [
    {"character_id": "char-001", "chinese_name": "何深", "english_name": "Henry Hart"}
  ],
  "events": [
    {
      "dialogue_id": "EP09-D0001",
      "start_seconds": 1.25,
      "end_seconds": 3.8,
      "speaker_id": "char-001",
      "speaker_chinese_name": "何深",
      "speaker_english_name": "Henry Hart",
      "speaker_label": "何深",
      "chinese_text": "你要是还跟我好好的",
      "delivery": {
        "speech_rate": "medium",
        "intonation": "低平后下沉",
        "timbre": "年轻男声、清晰、略紧",
        "emotion": "克制愤怒",
        "rhythm_pause": "前半连贯，转折前短停顿",
        "pause_profile": [
          {"position_ratio": 0.58, "duration": "short", "function": "emphasis"}
        ],
        "confidence": "high"
      },
      "evidence": ["audible_speech", "lip_sync"],
      "confidence": "high",
      "warnings": []
    }
  ],
  "warnings": [],
  "errors": []
}
```

## Rules

- Use unique ordered IDs `EP{episode}-D{four digits}`.
- Store absolute seconds in half-open intervals; allow gaps and overlaps.
- Keep one continuous utterance intact across visual cuts.
- A reaction shot does not establish a speaker change. Preserve voice continuity unless changed voice, speaking mouth movement, or a clear new turn proves otherwise.
- Reference an asset `character_id`, or use exactly `unclear` names with `speaker_label` and a warning.
- Preserve actual source-language speech; do not translate, paraphrase, or invent missing words.
- Output an event only when its spoken wording is reliably intelligible. Ignore genuinely unintelligible fragments; do not create placeholder events or reconstruct them from subtitles or context.
- A clear line with an uncertain speaker is still retained using `speaker_id: unclear`, a concrete `speaker_label`, and a warning.
- Allow evidence values `audible_speech`, `burned_subtitle`, `lip_sync`, `turn_taking`, `character_context`, or `narrative_context`.
- Allow confidence values `high`, `medium`, or `low`.
- `speech_rate` is `very_slow`, `slow`, `medium`, `fast`, `very_fast`, or `unclear`.
- `intonation`, `timbre`, `emotion`, and `rhythm_pause` describe audible qualities only.
- `pause_profile` records audible intra-utterance pauses ordered by `position_ratio` from 0 to 1.
- Do not include subtitle audit, OCR candidates, voiceprints, shot boundaries, pose, position, camera, translation, or generation prompts.
