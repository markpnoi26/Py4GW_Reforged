# How looting works today (audit)

Derived from the code, not from memory. Three separate parts that barely know each other. Plain words.

## 1. The list-maker — `LootConfig` (`Py4GWCoreLib/py4gwcorelib_src/Lootconfig_src.py`)
- One shared instance everyone uses (a singleton, `:534`).
- You ask it "what nearby items are worth grabbing?" via `GetfilteredLootArray(...)` (`:714`) and it
  returns a distance-sorted list of item-agent-ids. **That is all it does.** It never watches on its
  own (no loop/timer anywhere) and never walks or picks anything up.
- How it decides, in order (first match wins): item-id blacklist → model blacklist → item-id whitelist
  → model whitelist → the five rarity on/off switches → custom checks. Eligibility gate first: the item
  must be **ours or unassigned**, and not locked by another account.
- Reference catalog `LootGroups` (`:9-531`) is **never used by the filter** — it's just a model list the
  menu reads.

**Broken / dead today:** dye options are fully ignored by the filter; `loot_gold_coins` is set but never
read; the item-id blacklist is keyed on the ground-agent id while the whitelist uses the item id (a
bug); the multibox owner-sharing options (`multibox_loot` / `allow_unasigned_loot`) and the
leader/follower path are commented out — inert.

## 2. The "is it a good time?" check — written three times
The loop that decides *when* to loot (not fighting, bag has room, enough time passed, then ask the
list-maker if anything's there) is **duplicated** in three places, each re-doing the same checks:
- `Widgets/Automation/Multiboxing/HeroAI.py` `LootingNode`,
- `HeroAI/headless_tree.py` `_handle_looting`,
- `Py4GWCoreLib/botting_src/helpers_src/Upkeepers.py` `upkeep_auto_loot`.
Manual buttons (`HeroAI/ui_base.py`, `commands.py`) skip the checks and fan out to all accounts.

## 3. The grabber — walks and picks up (two versions)
- **Message version:** the checks above send a `PickUpLoot` message; `Widgets/System/Messaging.py`
  `PickUpLoot` (`:1633`) does the walking — walk to it, claim it with the shared loot lock, interact,
  wait up to 3s for it to disappear (= picked up). On failure (unreachable / timeout / bag full) it
  remembers the item so it stops trying (`AddItemIDToBlacklist`).
- **Direct version:** the botting `Items.loot` step, the `LootItems` behaviour-tree node, and the
  standalone bots hand the list straight to a `LootItems` walker and walk it themselves — no message.

Cross-account "don't both grab the same drop" is handled in the shared-lock layer
(`GlobalCache/WhiteboardLocks.py`), already through shared memory — **not** in the list-maker.

## 4. The two menus
- **Loot Manager window** — configures the shared list-maker and **saves** its settings
  (`JsonFactory` docs).
- **Inventory+ panel** — changes the **same** shared list-maker but **saves nothing** (its save/export
  buttons are stubs); its edits only persist because the Loot Manager window autosaves the shared state.

## 5. Marking (recolour / beacon) — not wired at all
The game engine can recolour an item's label and draw a beacon, but **no loot code uses it**. The
Python wrapper `AgentRecolor.py` only exposes agents/gadgets (not items); the beacon files are orphan
test widgets nothing imports. So marking is built from zero.

**How the native item recolour actually works** (important — items are NOT like agents): the native
side keeps its own item rule table and matches inside a detour on the game's own item-label function
(`Detour_ItemGetTextData` → `AgentRecolor::OnItemGetTextData`,
`Py4GW_Reforged_Native/src/GW/agent_recolor/agent_recolor.cpp:99,641`). You **set rules** (by rarity /
type / model / name, or a specific item id/agent) and the game colours each label at draw time —
**no per-frame Python pass**. Precedence is native and fixed: `agent_id > item_id > model_id > name >
type > rarity`, first match wins. Alpha is the fade/hide channel (`0x00` blanks the label).
(For agents, by contrast, Python *does* scan and push per-agent colours every frame.)
