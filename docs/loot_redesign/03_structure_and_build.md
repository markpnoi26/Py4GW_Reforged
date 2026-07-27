# Loot Config — Structure & Build Order

The shape of the code and the order to build it. Mirrors `agent_recolor`. See `01` for the design,
`02` for how looting works today.

> **BUILT — as-shipped.** The whole thing is implemented and Pyright-clean; see
> **§ As built** at the end for exactly what landed, where, and the three deviations from this plan.

## Module layout (mirror `agent_recolor`)

New package `Py4GWCoreLib/py4gwcorelib_src/loot/` (name TBD), same four-file split as `agent_recolor`:

| file | holds | depends on |
|---|---|---|
| `model.py` | **pure data + serialization**: `Condition`, `Filter`, `MarkRule`, and the config container (rarity toggles, List selection, Materials selection, Filters, mark rules). `to_dict`/`from_dict`. No ImGui / Settings / native imports. | nothing game-side |
| `catalog.py` | the **derived data layer**: enumerate `ModelID` + textures + the **grouping table** → the List's groups; `MaterialMap` + the **salvage table** → the Materials surface. One place that turns the shipped tables into what the engine + UI read. | the two data tables |
| `store.py` | **persistence**: global doc (`JsonFactory`) for the shared ruleset (List/Materials/Filters/mark rules); per-account doc (`Settings`) for master-enable + rarity toggles + quick-access choices. `load_*`/`save_*`. | JsonFactory/Settings |
| `controller.py` | the **singleton engine (the brain)**: holds the config; **produces the loot array** (read each ground item once, run the four surfaces, return the ids); **pushes the recolour rules** to native when the config changes (not per-frame — see below); runs the **beacon** pass; holds the **transitional runtime state** (bot adds, skip list — never saved); handles the **cross-account reload** message. | model, catalog, store, Item.Mods, AgentRecolor |
| `config_ui.py` | the **System Settings editor** (`add_sections`: List / Materials / Filters / Marking) **and** the **quick-access window** (`draw_quick_access`, two view modes). Only transient UI buffers live here. | controller |
| `data/` | the two shipped tables: `grouping.json` (category→items) and `salvage.json` (item→materials). | — |

**Supporting changes outside the package:**
- `Lootconfig_src.py`: `LootConfig` becomes a **thin facade over the controller** — keeps
  `GetfilteredLootArray(...)` and the runtime-add methods (`AddToWhitelist`, `AddItemIDToBlacklist` =
  the actor's skip list) so the ~20 callers are untouched.
- `AgentRecolor.py`: add the **item** surface (`EnableItems` + the `set_item_*_color` wrappers) —
  native already has it, the wrapper doesn't.
- `system_settings/model.py` + `config_ui.py`: register a **`loot` category** (the lazy-import/error-
  surfaced branch, like `agents`).
- `Widgets/System/Messaging.py` + `Multiboxing_enums.py`: add a **loot-reload command** + its route.
- Beacon: lift `light_beacon.py`'s draw logic into a small helper the controller calls.

## How the pieces answer the two jobs
- **Loot array (decision):** a consumer calls `LootConfig().GetfilteredLootArray(distance)` → facade →
  `controller.filtered_loot(distance)`: snapshot each eligible ground item once (`PyItem` + one
  `mods_core.decode_item`), test the four surfaces (rarity / List / Materials-via-salvage-table /
  Filters), return the ids. **No walking, no "when".**
- **Recolour (applied, not scanned):** when the config changes, push the rule table to native
  (`set_item_rarity_color` / `set_item_type_color` / `set_item_model_color` / `set_item_name_color`,
  plus per-item setters). The game's own item-label detour matches and colours each item at render
  time, with native precedence `agent_id > item_id > model_id > name > type > rarity`. **No per-frame
  Python pass.** (Unlike agents, which do need one.)
- **Beacon (drawn):** the only per-frame part — each frame, ground items matching a beacon rule, capped
  to the nearest few, drawn by the lifted beacon renderer.

## Build order

1. **Data tables** — extract + **your review**: `grouping.json` (from `LootGroups`) and `salvage.json`
   (from frenkey `items.json`, the clean `item → material ids`). These are the foundation.
2. **`model.py`** — the config shapes + serialization. Pure and testable.
3. **Engine core** (`controller.filtered_loot` + read-once snapshot + the four-surface test) and the
   **`LootConfig` facade** wiring, keeping `GetfilteredLootArray`. Validate against real ground items
   with the dump widget — **no UI, no marking, no persistence yet.** Nothing downstream breaks here.
4. **`store.py`** — global ruleset + per-account toggles (mirror `agent_recolor/store.py`).
5. **`catalog.py`** — derive the List (ModelID + textures + grouping) and Materials (MaterialMap +
   salvage table).
6. **`config_ui.py` editor** — List / Materials / Filters tabs in System Settings; register the
   category.
7. **Quick-access window** — the two view modes (texture grid / checkbox table) + the user-configurable
   subset; opened from the settings module, drawn by the always-on host.
8. **Marking** — surface the item setters in `AgentRecolor.py`; add the mark rules (keyed rarity /
   type / model / name) and push them to native on change; then the beacon pass (lift `light_beacon`,
   nearest-N cap). Marking tab in the editor.
9. **Cross-account reload** — the message command + route + broadcast-on-save.
10. **Cleanup** — remove the dead `multibox_loot`/`allow_unasigned_loot` params; retire the old Loot
    Manager / Inventory+ config paths once the new editor covers them.

Each step is usable on its own: after step 3 the game loots exactly as before but through the new
engine; every step after only adds.

---

## As built

Everything above landed. Pyright: **0 errors** across the new package, the facade, `AgentRecolor`,
`system_settings`, and the loot consumers.

### What exists now
| path | what |
|---|---|
| `Py4GWCoreLib/py4gwcorelib_src/loot/model.py` | the saved shapes: `Filter` (a list of conditions, all must match), `MarkRule`, `LootRules` (global), `LootToggles` (per-account), the `FACTS` table |
| `.../loot/catalog.py` | derived data: groups, materials (`MaterialMap`), the salvage table + its inverse, Nick's schedule (reuses `NICHOLAS_CYCLE`), name/texture per model |
| `.../loot/store.py` | global ruleset via `JsonFactory` (`Widgets/System/Loot.json`), per-account toggles via `Settings` (`Widgets/System/Loot.ini`) |
| `.../loot/controller.py` | the engine: `filtered_loot()`, the read-once `ItemSnapshot`, the four surfaces, transitional state, `push_marks()`, `draw_beacons()`, `reload_rules()`/`broadcast_reload()` |
| `.../loot/config_ui.py` | the System Settings editor (List / Materials / Filters / Marking / Status) + `draw_quick_access()` with both view modes |
| `json/Defaults/Widgets/System/LootGrouping.json` | the grouping table (seeded; 11 categories, 395 items) |
| `json/Defaults/Widgets/System/LootSalvage.json` | the salvage table (seeded; 2,021 items, 34 materials) |

### Wired into
- `Lootconfig_src.py` — rewritten as the **facade**; `LootConfig` keeps every legacy member, including
  the raw sets callers mutate in place (`item_id_whitelist`, `item_id_blacklist`, `dye_whitelist`) and
  `LootGroups` (returned as **`ModelID` members**, because `AutoInventoryHandler` reads `member.value`).
- `AgentRecolor.py` — the **item** surface added (`EnableItems`, `SetItem{Rarity,Type,Model,Name,Id,Agent}Color`,
  `ClearItemRules`); native already had it.
- `system_settings/model.py` + `config_ui.py` — a **`loot` category** with the lazy-import/error-surfaced branch.
- `Multiboxing_enums.py` + `Widgets/System/Messaging.py` — `SharedCommandType.LootConfigUpdated` and its
  route (Messaging only routes; the loot module re-reads its own file).
- `Widgets/System/System Settings.py` — boots the marking, and draws the quick window + beacons each
  frame so they survive the settings window being closed.
- `Widgets/Guild Wars/Items & Loot/LootManager.py` → **moved to `Legacy code and tests/`**.

### Deviations from the plan (deliberate)
1. **`multibox_loot` / `allow_unasigned_loot` are accepted-and-ignored, not deleted.** ~15 callers pass
   them by keyword; removing the parameters would break every one for no behavioural gain (they were
   already dead). They are documented as deprecated no-ops.
2. **Custom checks kept** (`AddCustomItemCheck`) as an additive-only contributor that runs last and can
   never beat an exclusion — frenkey's LootEx registers one. Session-only, never saved.
3. **The dye API now works.** The legacy dye lists were inert; they are wired to a transitional dye set
   the engine actually consults.

### Data notes for the review pass
The grouping table is the **merge of BOTH legacy catalogs**, not one of them. The old Loot Manager
widget used `modelid_drop_data.json` (403 rows, with `drop_info`); the core library used the separate
`LootGroups` dict (395). Taking either alone loses items — the merge is the point of killing the
duplication. As shipped:

- **11 categories, 52 subgroups, 377 items** — the widget catalog's order/structure, plus anything only
  `LootGroups` had.
- **5 misspellings fixed** (they were dead toggles in the old UI, matching nothing):
  `Curved_Mintaur_Horn`→`Curved_Minotaur_Horn`, `Dregde_Charm`→`Dredge_Charm`,
  `Dregde_Manifesto`→`Dredge_Manifesto`, `Oni_Taloon`→`Oni_Talon`, `Plauge_Idol`→`Plague_Idol`.
- **`drop_info` preserved for 376 items** in `LootDropInfo.json` and shown in the hover tooltip
  ("Dropped from: …"), as the old widget did.
- **27 entries dropped** because their `ModelID` is a placeholder, not a real id (the enum marks them
  *"Dummy modelid's to insure no LootManager Crash — will be changed to correct value"*): Animal_Hide,
  Bleached_Shell, Dark_Claw, Plague_Idol, Vampiric_Fang, … They could never match a real drop. They
  need real ids before they can come back.
- One duplicate remains by nature: model `817` is in Trophies/K and /O because `Oni_Claw` is an enum
  **alias** of `Keen_Oni_Claw`.
- Trophies' 23 subgroups are alphabet buckets (A, B, C…) — preserved as-is, but worth regrouping
  semantically during your review.
- Salvage: armor is intentionally absent (grabbed by rarity, per `01`).

### UI invariant (a regression to not repeat)
The catalog is rendered **two levels deep everywhere** — category → subgroup → items, with all/none at
both levels. An early build flattened each category into a single grid (one wall of 218 trophies);
that is a functional regression versus the old widget and is explicitly not allowed.
