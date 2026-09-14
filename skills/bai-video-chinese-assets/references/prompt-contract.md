# Prompt contracts

## Independent episode extraction

Do not provide other episodes or an existing global asset library. Ask for one JSON object containing independent episode-local candidates.

### People

Create a `人物本体` candidate for every reusable identity and separate `人物状态` candidates for meaningful wardrobe, uniform, disguise, injury, age-period, or persistent physical state. Distinguish people using only supported evidence across:

Also create a base candidate for every distinguishable speaking role or character performing a clear narrative action, even when unnamed or appearing only once. Use a stable functional name such as guest, maid, doctor, or guard. Exclude only indistinguishable background crowd members with no dialogue and no independent action.

- sex presentation, age impression, height/build, face shape, skin tone;
- eyebrows, eyes, nose, mouth, facial hair, scars, marks, eyewear;
- hairline, hairstyle, length, texture, and color;
- voice quality, accent, speech rhythm, habitual wording when audible;
- posture, gait, gestures, handedness, habitual movement;
- role, relationships, titles, recurring actions, and narrative function;
- clothing silhouette, layers, colors, materials, footwear, accessories for state rows.

Do not turn emotion, action, camera angle, location, held prop, flashback, or dream into a state.

### Scenes

A scene is a space people can enter, remain in, or act within. Extract reusable narrative spaces, not every camera angle. Distinguish scenes by:

- interior/exterior, spatial function, scale, floor plan, zones, levels;
- entrances, exits, corridors, stairs, windows, adjacency and connectivity;
- architecture, walls, floors, ceilings, fixed furniture, landmarks;
- lighting sources, time cues, weather exposure, wear and cleanliness;
- signage or readable identifiers without inventing text;
- recurring occupants, actions, and narrative function.

Use `场景状态` only for a material transformation of the same space, such as fire damage, wedding dressing, or persistent renovation—not time of day, angle, or temporary crowding alone.

### Props

Extract objects that are handled, exchanged, worn as plot evidence, operated, searched for, damaged, or repeatedly important. Distinguish props by:

- unique versus generic role;
- material, color, shape, dimensions, construction, markings;
- wear, damage, contents, open/closed or assembled state;
- owner, carrier, storage location, interaction and narrative function;
- relationships to containers, sets, duplicates, and vehicles.

Use `道具状态` only when the same prop undergoes a plot-significant persistent change. Treat vehicles as props and vehicle interiors used for action as scenes. Exclude generic clutter.

Before returning, perform a coverage sweep over every speaking role, key actor, scene transition, and object that is featured, handled, exchanged, operated, or plot-driving. Add any omitted supported candidate before emitting JSON.

After the primary extraction, run two sequential same-episode character-only audits against the complete video by default. The first audit receives the primary character-base names. The second receives the accumulated character-base names from the primary extraction and first audit, and focuses on extremely short lines, off-screen voices that later appear, brief speaking roles in group scenes, and one-action characters. Each audit returns omitted character-base rows only. Reject exact name/alias duplicates locally, append valid new rows, and assign episode-local IDs only after both audits. Do not pass assets from another episode into either audit. Allow `--character-audit-passes` to override the default for controlled cost or testing.

## Whole-series semantic merge

Provide every episode candidate with its immutable local ID. By default, Codex local semantic reasoning uses all semantic dimensions and narrative evidence, not names alone. Optional 中转站 Pro merge follows the same contract. The semantic authority must:

1. create canonical global assets for people, scenes, and props;
2. merge cross-episode identities and equivalent states;
3. preserve genuinely distinct lookalikes, spaces, or objects;
4. select stable Chinese names and evidence-grounded composite descriptions;
5. link each state to its global base asset where applicable;
6. calculate episode appearances from mapped source candidates;
7. return every local ID exactly once in both a source list and explicit mapping.

### Character wardrobe-state merge boundary

For `人物状态` rows whose state is driven by clothing, wardrobe, uniform, disguise, or styling, treat the visible outfit construction as a hard merge boundary, not a soft similarity hint. Do not merge two states merely because they belong to the same character and share a colour, fabric family, social occasion, or general elegance level.

Only merge cross-episode wardrobe states when the candidate evidence is materially consistent across all of these visible anchors:

- upper-body silhouette and cut, such as off-shoulder, one-shoulder, cape, coat, blazer, knitwear, collar size, sleeve length, cropped versus long;
- layer structure, such as dress alone, coat over dress, cape over blouse, top with trousers, top with skirt;
- lower-body garment when clearly visible and state-defining, such as trousers, short skirt, long skirt, dress, shorts, boots, heels;
- dominant material and texture, such as faux fur, lace, satin, tweed, wool, leather;
- distinctive accessories that define the state, such as handbag, earrings, necklace, headpiece, gloves, veil, bandage;
- stable narrative continuity or repeated use of the exact same outfit.

If any of those anchors conflict, split the candidates into separate `人物状态` assets even when names or colours are similar. Examples that must remain separate unless direct evidence proves they are the exact same outfit: white one-shoulder top with a clearly different formal dress silhouette; white fur-collar coat with short skirt and boots; white bow cape coat with lace sleeves; white lace dress outfit; white feather formal dress.

Do not split too finely when the primary upper-body wardrobe structure is the same and the apparent difference comes only from partial framing, incomplete lower-body visibility, held props, phone/handbag presence, or a generic lower-body note. For example, `斜肩露肩上衣` and `斜肩露肩上衣裤装` can be one state when both describe the same white off-shoulder/one-shoulder top structure and no clearly different full outfit is established. Keep separate only when the lower-body or layer structure is visually decisive, such as off-shoulder top versus full-length formal dress, fur-collar coat with short skirt, cape coat with lace dress, or feather formal dress.

When a global `人物状态` contains multiple source candidates, its aliases must not hide contradictory outfit structures. Prefer narrower canonical names over a broad name such as “白色造型” or “白色毛绒外套” when the sources differ.

Broad wardrobe category words such as `办公套装`, `西装`, `衬衫`, `礼服`, `外套`, or `裙装` are not enough to prove two states are identical. Use colour, cut, layer structure, fabric, accessories, and narrative continuity to decide. For example, black shirt, grey suit, brown suit, burgundy suit, and wounded state must remain separate even if all look like businesswear; two rows named with the same broad class may merge only when the visible specific outfit is materially the same.

The selected merge authority is semantically authoritative. Default to Codex local semantic reasoning; use a 中转站 Pro result only when the user explicitly requests remote Pro merge. The validator checks schema, referential integrity, coverage, and episode consistency without silently changing semantic decisions.
