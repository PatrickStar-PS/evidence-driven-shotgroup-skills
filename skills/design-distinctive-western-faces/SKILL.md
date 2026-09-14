---
name: design-distinctive-western-faces
description: Design and validate a whole-drama cast face-identity bible for photorealistic British, European, or North-American remakes, with structurally distinct face shapes, features, age markers, controlled family resemblance, collision checks, and reusable prompt injections. Use when character images look alike, Western facial casting is weak or generic, identity faces drift across wardrobe states, or Codex needs to prepare distinctive face specifications before batch character-image generation from an asset workbook or generation manifest.
---

# Design Distinctive Western Faces

Create a cast-level face system before regenerating any character images. Treat face design as identity architecture, not as a collection of isolated beauty prompts.

## Inputs

Require:

- the current project's character asset workbook or manifest;
- the target country/period and realism level;
- every base character identity, collapsed across wardrobe and story states.

Use existing identity-reference images when present to audit collisions, but do not preserve a weak or duplicated generated face merely because it already exists. Do not read another project's cast or prompts as fallback.

## Workflow

1. Extract all person rows and collapse state assets onto one base identity. Keep exact source and localized names.
2. Build a cast matrix by age band, gender presentation, family, narrative role, and screen importance. Do not infer ethnicity, health, morality, or personality from facial appearance.
3. Design the principal cast first. Assign each person a distinct face silhouette and then define brow, eyes, nose, mouth, jaw/chin, skin detail, hairline, age markers, and one subtle asymmetry marker.
4. Require every pair of similar age/presentation to differ on at least eight visible axes, including at least five structural axes among outline, forehead, cheekbones, jaw, eyes, and nose. Hair, clothing, makeup, expression, and accessories do not count as structural separation.
5. For blood relatives, share only one or two stable family traits, then require at least three individual contrasts. Marriage, employment, or social proximity does not create family resemblance.
6. Use region-appropriate contemporary casting through concrete anatomy, age, grooming, and social styling. Skin tone is a hard identity constraint: specify cool porcelain-fair, cool pale ivory, pale rose ivory, or very fair milk-toned skin with subtle pink/cool undertones, realistic pores, age texture, and slight natural unevenness. Explicitly reject yellow cast, warm beige, peach beige, golden beige, medium beige, tan, warm olive, bronzed, sun-kissed, or studio-warm skin. If a reference image appears warm/yellow, treat that as a generation defect to correct, not a target to preserve. Character hair must not be pure black, jet black, blue-black, ink-black, or flat black; use visibly brown, chestnut, auburn, dark-blonde, ash-brown, greying, or salt-and-pepper families instead. Never use vague prompts such as `Western face`, `European beauty`, `handsome CEO`, or `high-class features` as the identity definition.
7. Write one reusable `prompt_injection` per base identity, and also write a Chinese `prompt_injection_cn` for Chinese prompt workflows. Put the cool-fair skin rule and non-black hair rule in the first half of every injection so downstream image generators cannot bury it behind wardrobe or lighting. State assets must inherit the same identity geometry and change only wardrobe, wetness, injury, makeup, hair arrangement, or story condition.
8. Add pairwise `contrast_against` notes for likely collision pairs. Explicitly forbid blended, averaged, celebrity, doll-like, or source-actor carryover faces.
9. Save `face_identity_bible.json`. Read [references/face-bible-schema.md](references/face-bible-schema.md) for the exact contract.
10. Run:

```powershell
python scripts/validate_face_bible.py --input <face_identity_bible.json> --normalized-json <validated.json> --prompt-csv <prompt_injections.csv> --collision-csv <collision_report.csv>
```

Stop when validation reports an error. Warnings require review before production generation.

## Generation prompt contract

Place the face injection immediately after the character name and before wardrobe or scene text. Require a neutral, unobstructed three-quarter portrait plus front and profile evidence for the base identity.

Preserve:

- exact craniofacial proportions and feature relationships;
- cool porcelain-fair or cool pale ivory natural skin, subtle rose undertone, pores, fine asymmetry, age-appropriate lines, and non-uniform tone; never warm yellow, peach beige, golden beige, tan, bronzed, or sun-kissed;
- non-black natural hair colour family;
- the same eye spacing, nasal bridge/profile, philtrum, lip ratio, jaw angle, chin, hairline, and ear placement across states.

Reject:

- generic symmetrical fashion-model faces;
- same-template soft oval faces with similar gentle brows, small noses, warm beige/yellow skin, and warm brunette styling across young women;
- identical high cheekbones, small noses, pointed chins, or almond eyes across the cast;
- face differences created only by hair colour, hairstyle, makeup, clothing, expression, or lighting;
- exaggerated ethnic caricature or nationality stereotypes;
- beautification, whitening filters, or studio glamour lighting that erases age, pores, asymmetry, cool undertone, or distinctive structure;
- more than one person in a base identity image.


## Skin-tone and contrast QA

Before accepting a face bible or prompt-injection CSV, audit the generated wording against these failure modes:

- If any principal character uses `warm beige`, `peach beige`, `golden beige`, `sun-kissed`, `tan`, `olive`, or equivalent Chinese wording such as `暖黄`, `米黄`, `蜜色`, `小麦色`, `健康肤色`, mark it as a defect and rewrite it to a cool fair family.
- For Chinese prompt workflows, prefer explicit phrases such as `冷调瓷白皮肤`, `浅象牙白皮肤`, `带轻微玫瑰血色的冷白皮`, `真实毛孔与自然肤色细节`, and add `不要暖黄、不要米黄、不要金棕、不要晒黑感`.
- When two generated faces still look like the same base template, strengthen bone-structure contrasts first: face outline, forehead height/width, cheekbone placement, jaw angle, chin shape, eye spacing/tilt, nasal bridge/profile, philtrum length, and lip ratio. Do not solve collisions by only changing hair colour, makeup, jewellery, expression, or clothing.
- If a generated image comes back with a yellow or warm studio cast despite the prompt, keep the identity but regenerate with a corrective prefix: `cool porcelain-fair skin, no yellow beige cast, no warm golden undertone, neutral daylight white balance` / `冷调瓷白皮肤，禁止暖黄米色肤色，禁止金色暖调，白平衡为中性日光`.
## Deliverables

Return:

- validated face bible JSON;
- prompt-injection CSV for the image-generation workflow, including both `face_prompt_injection_cn` and `face_prompt_injection`; Chinese workflows must consume the Chinese column first;
- pairwise collision report;
- a short cast QA summary identifying the closest remaining face pairs.

Do not overwrite an asset workbook or existing identity images unless the user explicitly requests it. Generate new identity references into versioned folders so the existing set remains recoverable.
