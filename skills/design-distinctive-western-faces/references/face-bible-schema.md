# Face identity bible schema

Use UTF-8 JSON with this shape:

```json
{
  "schema_version": "1.0-distinctive-western-cast-faces",
  "project": "Project name",
  "casting_context": "contemporary British photorealistic television casting",
  "characters": [
    {
      "source_name": "角色中文名",
      "localized_name": "Canonical English name",
      "role": "narrative role",
      "age_band": "late twenties",
      "family_group": "family id or none",
      "family_traits": ["shared trait, if blood-relative"],
      "feature_axes": {
        "outline": "face silhouette",
        "forehead": "height, width, slope",
        "cheekbones": "height and projection",
        "jaw": "width, angle, taper",
        "chin": "width, length, cleft or projection",
        "brows": "weight, shape, spacing",
        "eyes": "shape, depth, spacing, colour",
        "nose": "bridge, profile, tip, width",
        "mouth": "width, cupid bow, upper/lower lip ratio",
        "skin_detail": "undertone, texture, freckles, lines",
        "hairline": "shape, recession, density",
        "hair_colour": "non-black natural hair colour family",
        "asymmetry": "one subtle stable marker"
      },
      "must_preserve": ["stable identity invariants"],
      "must_avoid": ["collision and beautification risks"],
      "contrast_against": [
        {"localized_name": "Another character", "differences": ["at least four visible axes"]}
      ],
      "prompt_injection": "Complete reusable identity-face paragraph",
      "negative_prompt": "Identity-specific exclusions"
    }
  ]
}
```

## Axis rules

- Fill every `feature_axes` field with observable structure, not an adjective such as beautiful, noble, villainous, or Western.
- Describe eye colour only as a supporting cue; shape, spacing, and depth matter more.
- Keep skin tone within natural casting variation without using it as the sole differentiator.
- For this workflow, prefer very fair, cool ivory, porcelain-fair, pale rose, or very fair milk-toned natural skin with visible texture and age evidence. Explicitly avoid tan, warm olive, golden beige, medium beige, or bronzed skin.
- Character hair must not be pure black, jet black, blue-black, ink-black, or flat black; use visible brown, chestnut, auburn, dark-blonde, ash-brown, greying, or salt-and-pepper families instead.
- Use scars, moles, dental differences, or pronounced asymmetry only when appropriate. Prefer subtle brow height, nasal deviation, eyelid, smile-line, or chin asymmetry.
- Do not assign identical values across the cast merely by changing synonyms.

## Family rules

- Use the same `family_group` only for blood relatives.
- Share one or two traits such as a long straight nasal bridge or hooded grey-blue eyes.
- Preserve age transformation: an older relative may share the structure while adding hairline recession, lid hooding, jowling, wrinkles, or loss of facial volume.
- Require three or more counter-traits between relatives so they remain individually recognizable.

## Prompt rules

Each `prompt_injection` must:

- name the character once;
- state the target casting context;
- describe the full outline plus at least six internal feature axes;
- include very fair or pale ivory natural skin texture, age evidence, hairline, non-black hair colour, and stable asymmetry;
- say that the geometry is identity-locked across all wardrobe and story states;
- forbid face averaging with other cast members, celebrity likeness, source-actor carryover, doll skin, and generic beauty smoothing.

Use the injection unchanged for all state assets. Keep expression, pose, wardrobe, wetness, illness, and lighting outside the identity injection.
