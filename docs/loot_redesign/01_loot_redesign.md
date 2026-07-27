# Loot Config — Redesign

Replaces the current Loot Manager class with one that is easy to handle. Written from how looting
actually works (audit in `02_how_it_works_today.md`). Plain language on purpose.

## What this class does — and only this

- **Watches the ground items** and produces the **loot array** — the list of items worth grabbing.
- **Decides the marking** — which items/categories get a recoloured label and/or a light beacon, and
  applies it.

**It does NOT** pick items up, decide *when* it is safe to loot, or handle salvage/vendor/inventory —
those are involved and already handled by other code. It keeps the one method everything already calls
to get the array, so nothing downstream changes.

---

## Two separate systems for "what to grab" — they stay separate

There are two independent ways to say "I want this," and they are kept distinct in **both the code and
the menu**. A hand-picked specific item and a property filter are different things: they need to be
told apart, and they need to be shown differently (especially for quick access). They are never merged.

### System 1 — The List (hand-picked specific items)
The curated items you want **by identity**, that no property describes:
- Trophies, consumables, tonics, event items.
- Organised in **two levels — category → subgroup → items** (Keys → Core/Prophecies/Factions/
  Nightfall, Materials → Common/Rare, Tomes → Normal/Elite, Trophies → A–W). **The subgroups are
  never flattened away**, anywhere they are shown (editor and quick window): a category rendered as
  one long list is exactly what the catalog exists to prevent. You tick an item, a subgroup, or a
  whole category.
- Built **from the `ModelID` list itself** — icon and name come from the model + texture folder (assume
  every item resolves a texture); the only thing kept by hand is which group an item is in. So adding
  an item is one step and nothing is duplicated (today two separate catalogs duplicate the enum, which
  is why items get half-added). The grouping (which item is in which category) is the one hand-maintained piece. **Decided:** reuse the
  existing categorization from the old `LootGroups` dict (`Lootconfig_src.py:9-531`) as the *starting
  point*, but **extracted into a clean, editable grouping table that the user reviews and cleans**
  (dropping dead/misspelled/misplaced entries) — not carried over blindly. The cleaned table becomes the
  single source; from then on the catalog is derived from `ModelID` + that grouping.
- Every item icon shows a **hover tooltip with its data**.
- **Nick's rotating items** feed into this list. Reuse the **existing Nicholas data already in the repo**
  (the one the Calendar widget uses — do not duplicate it). In the full editor the user controls **any
  cycle and any date**; in the quick-access window they just toggle **the current week's** items.
- This is the "I want THESE exact things" surface. It is a big, searchable grid of icons.

### System 2 — The Filters (property rules)
The rules that describe items **by quality**, so you never enumerate. This is the "I want anything that
IS like this" surface: a small editor of rules.

**It is the item-mod system, reused.** `Item.Mods` already solves exactly this problem, so a Filter is
shaped like a mod query — same structure, same value rules:

| item mods (`Item.py`) | loot filters |
|---|---|
| `HasMod(item_id, mod, *values)` — one condition | **one condition** = `(key, *values)` |
| `HasAllMods(item_id, modlist)` — **every entry must match** | **a Filter = a list of conditions, all must match** |
| entry = `mod` \| `(mod, *values)` | condition = `key` \| `(key, *values)` |

- **A Filter** = a name + an on/off + **a list of conditions, all of which must match** (the AND is
  `HasAllMods`). Different Filters are independent (any one matching is enough — §Putting them
  together).
- **A condition's values are type-routed exactly as `HasMod` does it** (`Item.py:127-165`):
  - an **enum** narrows the subtype — `Attribute.Marksmanship`, `DamageType.Fire`, `ItemType.Bow`,
    `DyeColor.Black`;
  - a **number** means **"that value or better"**, and the direction comes from the key's own metadata
    (`better_low` in `mods_core._Def`) — requirement is lower-is-better, damage/armor/worth are
    higher-is-better. No min/max pairs, no "or better" checkbox;
  - **multi-value keys match positionally** (e.g. Damage's `[min, max]`), same as `_values_match`;
  - **no value** = presence only ("has this mod at all").
- **Keys are of two kinds, written identically:**
  - a **mod** (`ModId`) → evaluated by `Item.Mods.HasMod`;
  - an **item fact** (`rarity`, `type`, `model`, `worth`, `quantity`, `dye`, `salvages_into`) →
    evaluated by its own reader (§`02`). The fact keys get the **same small metadata table** the mods
    have (value type, direction, subtype enum), so "or better" and subtypes work the same for both.
- **No callables.** `HasMod` accepts a predicate as an escape hatch; **Filters do not** — a filter must
  save as plain data and must never be able to override a decision from code.

**On disk** a Filter is just that list, e.g.
`{"name":"Gold Star Bows","on":true,"when":[["rarity","Gold"],["type","Bow"],["model","Star_Bow"],["requirement","Marksmanship",9]]}`

### Rarity — the broad quick switches
White / blue / purple / gold / green (+ gold coins) as simple on/off toggles — the everyday
quick-access. The broadest stroke: turn "white" on and every white is in, no list or filter needed.

### Materials — a tick-list, like the List, but matched by salvage output
The crafting materials (Bone, Iron Ingot, …) shown **the same way the trophies are** — a textured grid
or a checkbox table — where you tick the materials you want. An item is grabbed if it **salvages into
any ticked material**. It looks like the List (a tick-list of things) but behaves like a filter (it
matches on a property), which is why it is its own surface. Needs the salvage table (below).

### Putting them together
An eligible item (ours or unassigned, not locked by another account) is grabbed if **any** of these
says yes: a **rarity** switch it matches is on, **or** it is ticked in the **List**, **or** it salvages
into a ticked **Material**, **or** it matches a **Filter**. Four surfaces, added together, never merged.
Not being on the List does not mean unwanted — rarity, a material, or a filter can still bring it in.

## Marking — its own separate layer, driven by a callback

Recolour and beacon are driven **by criteria too** (a rarity, an item type, one specific item, or a
name match), but **independent of pickup**: you can mark without grabbing, and grab without marking.

*Marking a whole **group** (e.g. "all Trophies") is supported in the editor, but the native table has no
concept of our groups — so a group rule is **expanded into one model rule per item in that group** when
it is pushed. Purely an implementation detail; the user just picks the group.*

### Recolour — we push RULES, the game applies them (no per-frame scan)

**Items work differently from agents, and this is the important part.** For agents, the Python
controller scans the agent array every frame and pushes explicit `{agent_id: colour}` pairs. **Items do
not work that way.** The native side keeps its own item rule table and does the matching itself, inside
a detour on the game's own item-label function (`Detour_ItemGetTextData` →
`AgentRecolor::OnItemGetTextData`, `src/GW/agent_recolor/agent_recolor.cpp:99,641`):

- We **set rules once, when the config changes** — `set_item_rarity_color(rarity, argb)`,
  `set_item_type_color`, `set_item_model_color`, `set_item_name_color` (plus `set_item_id_color` /
  `set_item_agent_color` to target one specific item instance).
- Whenever the game draws an item's label, the detour looks the item up against those rules and
  colours it. **No Python loop over ground items, no per-frame push, nothing to throttle.**
- **Precedence is native and fixed:** `agent_id > item_id > model_id > name > type > rarity`, first
  match wins (`:661-700`). It reads from an immutable snapshot, so it's lock-free at render time.
- **Alpha is the fade/hide channel:** `0xFF` solid, mid values dim, and **`0x00` blanks the label
  entirely** (`:704-708`).

**What this means for the design:** marking rules are **keyed by what the native table understands** —
a rarity, an item type, a model (one specific item), or a name match. That is exactly the vocabulary
you asked for ("recolour a special item, or a whole category"), which is why the native was built with
those keys. Marking rules are therefore **not** the same thing as the multi-condition Filters of
System 2, and priority is not ours to order — **the native precedence above decides the winner.**

### Beacon — the one part we do draw
The beacon is our own 3D render, so it *is* a per-frame pass: each frame, take the ground items that
match a beacon rule, cap to the nearest few (a beacon is expensive), and draw. Reuse the existing
beacon renderer.

**Missing pieces on our side:** expose the **item** recolour functions on the Python wrapper
(`AgentRecolor.py` only wraps agents/gadgets today — the native functions all exist), and lift the
beacon renderer. Nothing drives either yet.

## Saves itself — global config, per-account toggles (same split as the other modules)
Exactly like `agent_recolor` / `name_obfuscation`:
- **Global** (shared across all accounts on the machine): the **common data and the rules** — the List,
  the Filters, the recolour/beacon rules.
- **Per-account**: the **local settings and toggles** — master on/off, which rarities are on, and each
  account's quick-access customisation.

Stored through the sanctioned jailed store (`JsonFactory` global + `Settings` account) and loaded by
the class itself — no caller-owned save/load like today.

**Transitional values are runtime-only and are NEVER saved.** Anything added at runtime — a bot adding
a model mid-run, the picker's skip-list of items it couldn't reach — lives in memory for that session
only and never touches the saved loot list. That is what makes it transitional. (Item ids are per
instance anyway.)

## Keeps working with everything else
The class keeps the existing "give me the loot array" method (`GetfilteredLootArray`, ~20 callers), so
HeroAI, the botting framework, and the bots keep working unchanged — they still ask for the array and
still own the *when* and the *walking*.

**Deprecated options removed:** the `multibox_loot` / `allow_unasigned_loot` params were no-ops (the
leader/follower loot-role logic is dead) — they are dropped. The working multibox contention (two
accounts never grabbing the same drop) is unaffected: it lives in the shared loot lock (shared memory),
untouched.

## Cross-account rule updates (messaging)
The config is global — one shared set — so the rules already travel via the shared file, but the other
accounts don't *know* it changed. So when one account edits the rules, it **sends a message to the other
accounts to reload**, and each account's loot module re-reads the shared rules live. This uses the
messaging system the same way `MerchantRules` does: a command routed by `Widgets/System/Messaging.py`
(which only routes — the loot module owns the reload). This is the only multibox concern that belongs to
this class.

## Materials data — two separate things (don't confuse them)
1. **The material list** (which materials exist, to pick from) — **we already have this:** `MaterialMap`
   in `Py4GWCoreLib/enums_src/Item_enums.py:267` (`ModelID → name`: Bone, Iron Ingot, Amber Chunk, …).
   No gap — the "materials" filter's picker uses it. (Frenkey's `LootEx/data/materials.json` is just a
   scraped copy of the same fixed ~30–40-material set; not needed.)
2. **The per-item salvage mapping** (which materials a *given item* yields) — **this we do not have.**
   The client never exposes it (`Item` only says *is it salvageable / is it a material*, never into
   what); the **common** material is whatever the item is *made of* (cloth robes → cloth, wooden branch
   → wood), a per-model fact, so it must come from data. The only source is frenkey's scraped
   `items.json` (keyed item-type → model-id, each with `common_salvage`/`rare_salvage` = the material
   ModelIDs; e.g. Abbot's Robes → common Bolt of Cloth, rare Bolt of Linen/Silk; amounts unscraped).
   **We extract only the clean minimal table** — `model_id → { common: [material ModelID], rare:
   [material ModelID] }`, dropping all the names/descriptions/wiki/amount noise — stored our own way.
   With `MaterialMap` (id→name) that answers both directions ("does item X give bone" and, inverted,
   "which items give bone"). **"Salvages into materials (any)" already works** with no table via
   `Item.Properties.IsMaterialSalvageable`.

**Decided: build the clean table** ("any material" is useless — nearly every drop salvages into
*something*). With it, materials become a **toggleable list, textured and tabled the same as the
trophies** (§ the List's two view modes): you tick the materials you want (Bone, Iron, …), and an item
is grabbed if it salvages into **any ticked material**. It's a fourth pickup surface, list-style in the
UI, salvage-filter in behaviour.

**Coverage is enough.** Frenkey's data covers ~2,000 items — the white salvage items, trophies, and
weapons, i.e. exactly the things you'd filter by material. **Armor is intentionally left uncovered:**
you grab armor by rarity, never by "salvages into cloth", so its missing salvage data doesn't matter.
If any gap ever needs filling, the source is the wiki's **"Contains \<material\>"** category pages
(e.g. `Contains_hide`) — the inverse index of the same facts, which frenkey already links per item
(`wiki_url`).

---

## The menu — full editor in System Settings + a compact pop-up

The class is reworked to live in **System Settings**, the same way `agent_recolor` / `name_obfuscation`
do: its own category, built from `model.py` / `store.py` / `controller.py` / `config_ui.py` and
attached via `add_sections(win, group)` + the lazy-import branch in `system_settings/config_ui.py`.

**Full editor (in System Settings) — the careful-setup surface, holds everything:**
- the **Filters** (property rules),
- the **List** in full — every group: trophies, event items, materials, consumables, tonics,
  **Nick's items**, and the rest,
- the **rarities**,
- the **recolour and beacon rules** (authored here; the callback above applies them).

**Quick-access window — a plain window (built like the other modules), opened from the settings
module, for in-play use:**
- shows a **subset the user chooses** — the settings editor has config options that let each account
  pick what appears in its quick-access window (e.g. the rarities, the trophies, the event items,
  materials, and whichever quick filters they want). Sensible defaults out of the box; Nick's items
  default to the current-week toggle. Everything else stays in the full editor.
- It must be **compact but functional** — the opposite of today's tree of hundreds of rows. The look
  to copy is **Inventory+**: textures, buttons packed in a grid so each takes little space.
- **Two view modes the user picks between**, trading graphics cost for density:
  1. **Texture grid** — Inventory+-style icon buttons (nicer, heavier to render);
  2. **Checkbox table** — plain rows of checkboxes (lighter, cheaper), for users who don't want the
     texture overhead.
- The balance to hit: **data-dense but a lean window, with good UX** — enough on screen to be useful
  mid-play, small enough to leave up, quick to read.

Search over the item grid is still the biggest single usability add wherever the grid appears.

---

## The two data tables (extracted, pending your review)

Both are **drafts extracted from existing data**; neither is final until you clean them, and the cleaned
versions become the single source (they then ship in the package's `data/` folder).

| table | what it is | source | status |
|---|---|---|---|
| **grouping** (item → category) | which item sits in which group (Trophies, Consumables, Tonics, …) — the one hand-maintained piece | the old `LootGroups` dict (`Lootconfig_src.py:9-531`, ~400 items) | not yet extracted |
| **salvage** (item → materials) | `model_id → { common: [material ModelID], rare: [material ModelID] }` | frenkey's scraped `items.json`, stripped of all name/description/wiki/amount noise | **extracted** → `salvage_mapping.json` (ids only, the real artefact) + `salvage_mapping_review.json` (same data with names, for reading). ~2,000 items, 34 materials. Armor deliberately absent (grabbed by rarity). |

The two `salvage_mapping*.json` files in this folder are **review drafts, not runtime data** — once you
approve, the id-only one moves into the package and the review copy is deleted.

## Still open (small, not blocking the first steps)

1. **Gold coins** — a specific model, not a rarity, and today's toggle is broken (set, never read). Keep
   it as its own switch beside the rarity toggles?
2. **The Inventory+ embedded loot panel** — the standalone Loot Manager window is replaced by the
   System Settings editor; does the InvPlus panel get repointed at the new class, or removed?
3. **The skip-list id bug** — today it is stored by one id and checked by another
   (`02` §1). Fix it in the new engine (recommended) or reproduce as-is?

## Status
Design settled. Steps 1–3 of the build order (`03`) are fully specified and safe to start; the three
items above only affect later steps.
