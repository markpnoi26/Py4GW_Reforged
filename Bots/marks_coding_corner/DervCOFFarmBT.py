"""COF Farmer, BottingTree edition.

Ports the old FSM-based `DervCOFFarm.py` to the new BT stack:

- `BottingTree.Create(...)` with named planner steps (Init → Prepare Outpost → Farm Loop)
- Custom BT skill rotation registered as a service tree; HeroAI stays disabled
- Existing yield-based utils (`loot_utils`, `merch_utils`, `town_utils`) wrapped
  as BT ActionNodes via a small `RunGenerator` shim
- Farm phase (Setup/Prepare/Kill/Loot/Wait) written to the shared blackboard;
  the rotation reads it every tick
- Party-wipe recovery routes back to Prepare Outpost when inventory is low,
  otherwise straight to Farm Loop
"""
from __future__ import annotations

import os
from typing import Callable
from typing import Iterator

import PySystem

from Bots.marks_coding_corner.cof_rotation import ENEMY_BLACKLIST
from Bots.marks_coding_corner.cof_rotation import PHASE_KILL
from Bots.marks_coding_corner.cof_rotation import PHASE_LOOT
from Bots.marks_coding_corner.cof_rotation import PHASE_PREPARE
from Bots.marks_coding_corner.cof_rotation import PHASE_SETUP
from Bots.marks_coding_corner.cof_rotation import PHASE_WAIT
from Bots.marks_coding_corner.cof_rotation import get_derv_build
from Bots.marks_coding_corner.utils.loot_utils import VIABLE_LOOT
from Bots.marks_coding_corner.utils.loot_utils import get_valid_loot_array
from Bots.marks_coding_corner.utils.loot_utils import identify_and_salvage_items
from Bots.marks_coding_corner.utils.loot_utils import move_all_crafting_materials_to_storage
from Bots.marks_coding_corner.utils.loot_utils import set_autoloot_options_for_custom_bots
from Bots.marks_coding_corner.utils.merch_utils import buy_id_kits
from Bots.marks_coding_corner.utils.merch_utils import buy_salvage_kits
from Bots.marks_coding_corner.utils.merch_utils import sell_non_essential_mats
from Bots.marks_coding_corner.utils.merch_utils import withdraw_gold
from Bots.marks_coding_corner.utils.town_utils import return_to_outpost
from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import ModelID
from Py4GWCoreLib import Player
from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib.BottingTree import BottingTree
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings
from Py4GWCoreLib.routines_src.BehaviourTrees import BT

# ---- Constants -----------------------------------------------------------

MODULE_NAME = "COF Farmer BT"
INI_PATH = "Widgets/Automation/Bots/COF Farmer BT"
INI_FILENAME = "COF_Farmer_BT.ini"

DOOMLORE_SHRINE_ID = 648
COF_LEVEL_1_ID = 560

MERCHANT_XY = (-19166.00, 17980.00)
MERCHANT_MOVE_XY = (-18815.00, 17923.00)
COF_ENTRANCE_MOVE_XY = (-18295.50, -8614.49)
COF_ENTRANCE_GADGET_XY = (-18250.00, -8595.00)
COF_PREP_SPOT = (-16623.00, -8989.00)
COF_ATTACK_SPOT_1 = (-15525.00, -8923.00)
COF_ATTACK_SPOT_2 = (-15737.00, -9093.00)
SETUP_RESIGN_SPOT = (-19665.00, -8045.00)

MERCHANT_DIALOG = 0x7F
COF_QUEST_DIALOG = 0x832101
COF_ENTER_DIALOG = 0x88
COF_ENTRANCE_GADGET_DIALOG = 0x84

# Loot list for COF (extends the shared VIABLE_LOOT).
VIABLE_LOOT |= {ModelID.Golden_Rin_Relic, ModelID.Diessa_Chalice}

# ---- Module-level bot handle --------------------------------------------

_botting_tree: BottingTree | None = None
_initialized = False
_ini_key = ""


# ---- Utility: wrap yield-based generators as BT ActionNodes --------------


def RunGenerator(gen_factory: Callable[[], Iterator], name: str = "RunGenerator") -> BehaviorTree:
    """Drive a yield-based generator (from the old `utils/` modules) as a BT node.

    One `next()` per BT tick; StopIteration returns SUCCESS. The generator is
    rebuilt from the factory on each entry so retries after failure work.
    """
    state = {"gen": None}

    def _tick(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        if state["gen"] is None:
            state["gen"] = gen_factory() # type: ignore
        try:
            next(state["gen"])
            return BehaviorTree.NodeState.RUNNING
        except StopIteration:
            state["gen"] = None
            return BehaviorTree.NodeState.SUCCESS

    return BehaviorTree(BehaviorTree.ActionNode(name=name, action_fn=_tick, aftercast_ms=0))


# ---- Utility: blackboard phase setters -----------------------------------


def SetPhase(phase: str) -> BehaviorTree:
    """Write the current farm phase onto the DervBoneFarmer BuildMgr, which
    is what its ProcessSkillCasting reads to decide what to do this tick."""
    def _set(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        get_derv_build().status = phase
        return BehaviorTree.NodeState.SUCCESS
    return BehaviorTree(
        BehaviorTree.ActionNode(name=f"SetPhase({phase})", action_fn=_set, aftercast_ms=0)
    )


# ---- Farm-loop custom nodes ---------------------------------------------


def WaitForAreaClearOrDeath() -> BehaviorTree:
    """Stay RUNNING while non-blacklisted enemies remain in spellcast range.

    Returns SUCCESS when the area is clear, FAILURE if the player dies mid-fight
    (which lets the outer sequence unwind and the party-wipe service take over).
    """
    def _tick(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
        if Agent.IsDead(Player.GetAgentID()):
            return BehaviorTree.NodeState.FAILURE
        px, py = Player.GetXY()
        enemies = Routines.Agents.GetFilteredEnemyArray(px, py, Range.Spellcast.value)
        for enemy_id in enemies:
            if Agent.GetModelID(enemy_id) not in ENEMY_BLACKLIST:
                return BehaviorTree.NodeState.RUNNING
        return BehaviorTree.NodeState.SUCCESS

    return BehaviorTree(
        BehaviorTree.ActionNode(name="WaitForAreaClearOrDeath", action_fn=_tick, aftercast_ms=0)
    )


def LootFilteredItems() -> BehaviorTree:
    """Loot COF-viable items using the existing `loot_utils` filter."""
    def _gen():
        yield from Routines.Yield.wait(500)
        filtered = get_valid_loot_array(viable_loot=VIABLE_LOOT, loot_salvagables=True)
        yield from Routines.Yield.Items.LootItemsWithMaxAttempts(filtered, log=False)

    return RunGenerator(_gen, name="LootFilteredItems")


# ---- Inventory-aware party-wipe recovery target --------------------------


def _inventory_is_ready() -> bool:
    salv = GLOBAL_CACHE.Inventory.GetModelCount(ModelID.Salvage_Kit)
    id_kits = GLOBAL_CACHE.Inventory.GetModelCount(ModelID.Identification_Kit)
    sup_id = GLOBAL_CACHE.Inventory.GetModelCount(ModelID.Superior_Identification_Kit)
    free = GLOBAL_CACHE.Inventory.GetFreeSlotCount()
    return (id_kits + sup_id) > 0 and salv >= 3 and free >= 4


def _choose_recovery_step_name() -> str:
    return "Farm Loop" if _inventory_is_ready() else "Prepare Outpost"


# ---- Planner steps ------------------------------------------------------


def InitializeBot() -> BehaviorTree:
    bot = _ensure_botting_tree()
    # Prime autoloot config, then run through Pacifist config (HeroAI off,
    # isolation on, no auto-loot — our custom rotation owns combat).
    set_autoloot_options_for_custom_bots(salvage_golds=True, module_active=False)
    return BehaviorTree(
        BehaviorTree.SequenceNode(
            name="Initialize Bot",
            children=[
                bot.Config.Pacifist(
                    auto_loot=False,
                    pause_on_danger=False,
                    resurrection_scroll=False,
                    multi_account=False,
                ),
                SetPhase(PHASE_WAIT),
            ],
        )
    )


def PrepareOutpost() -> BehaviorTree:
    return BehaviorTree(
        BehaviorTree.SequenceNode(
            name="Prepare Outpost",
            children=[
                BT.Map.TravelToOutpost(outpost_id=DOOMLORE_SHRINE_ID, log=True, timeout=30_000),
                BT.Skills.LoadSkillbar("OgCjkqqLrSYiihdftXjhOXhX0kA", log=True),
                # LoadSkillbar returns fast; give the client a moment to actually
                # populate the 8 skill slots before the rotation reads them.
                BT.Player.Wait(1_500),
                SetPhase(PHASE_SETUP),
                BT.Player.Move(x=MERCHANT_MOVE_XY[0], y=MERCHANT_MOVE_XY[1], log=True),
                _dialog_at(MERCHANT_XY, MERCHANT_DIALOG, "Open Merchant"),
                RunGenerator(withdraw_gold, name="WithdrawGold"),
                RunGenerator(sell_non_essential_mats, name="SellNonEssentialMats"),
                RunGenerator(buy_id_kits, name="BuyIDKits"),
                RunGenerator(lambda: buy_salvage_kits(custom_amount=5), name="BuySalvageKits"),
                RunGenerator(identify_and_salvage_items, name="IDAndSalvage"),
                RunGenerator(move_all_crafting_materials_to_storage, name="StoreCraftingMats"),
                _dialog_at(MERCHANT_XY, COF_QUEST_DIALOG, "Take COF quest"),
                _dialog_at(MERCHANT_XY, COF_ENTER_DIALOG, "Enter COF Level 1"),
                BT.Player.Wait(2_000),
                BT.Map.WaitforMapLoad(map_id=COF_LEVEL_1_ID, log=True, timeout=60_000),
                BT.Player.Move(x=SETUP_RESIGN_SPOT[0], y=SETUP_RESIGN_SPOT[1], log=True),
                BT.Party.Resign(log=True),
                BT.Map.WaitforMapLoad(map_id=DOOMLORE_SHRINE_ID, log=True, timeout=60_000),
            ],
        )
    )


def FarmLoop() -> BehaviorTree:
    """One full farm cycle. `repeat=True` on BottingTree.Create loops this."""
    return BehaviorTree(
        BehaviorTree.SequenceNode(
            name="Farm Loop",
            children=[
                # In case we died last cycle and need to get back to town.
                RunGenerator(return_to_outpost, name="EnsureAtOutpost"),
                BT.Map.WaitforMapLoad(map_id=DOOMLORE_SHRINE_ID, log=True, timeout=60_000),
                _dialog_at(MERCHANT_XY, COF_QUEST_DIALOG, "Take COF quest"),
                _dialog_at(MERCHANT_XY, COF_ENTER_DIALOG, "Enter COF Level 1"),
                BT.Map.WaitforMapLoad(map_id=COF_LEVEL_1_ID, log=True, timeout=60_000),
                BT.Player.Wait(2_000),
                BT.Player.Move(x=COF_ENTRANCE_MOVE_XY[0], y=COF_ENTRANCE_MOVE_XY[1], log=True),
                _dialog_at(COF_ENTRANCE_GADGET_XY, COF_ENTRANCE_GADGET_DIALOG, "Open COF gadget"),
                BT.Player.Move(x=COF_PREP_SPOT[0], y=COF_PREP_SPOT[1], log=True),
                SetPhase(PHASE_PREPARE),
                BT.Player.Wait(3_000),
                BT.Player.Move(x=COF_ATTACK_SPOT_1[0], y=COF_ATTACK_SPOT_1[1], log=True),
                BT.Player.Move(x=COF_ATTACK_SPOT_2[0], y=COF_ATTACK_SPOT_2[1], log=True),
                SetPhase(PHASE_KILL),
                WaitForAreaClearOrDeath(),
                SetPhase(PHASE_LOOT),
                BT.Player.Wait(500),
                LootFilteredItems(),
                BT.Player.Wait(500),
                RunGenerator(identify_and_salvage_items, name="IDAndSalvage"),
                SetPhase(PHASE_WAIT),
                BT.Party.Resign(log=True),
                BT.Map.WaitforMapLoad(map_id=DOOMLORE_SHRINE_ID, log=True, timeout=60_000),
            ],
        )
    )


def _dialog_at(xy: tuple[float, float], dialog_id: int, label: str) -> BehaviorTree:
    """Move to `xy`, target the nearest NPC, interact, and send `dialog_id`.

    Mirrors the old `bot.Dialogs.AtXY(x, y, dialog_id)` which internally paired
    an NPC interact with a dialog send.
    """
    return BehaviorTree(
        BehaviorTree.SequenceNode(
            name=f"DialogAt:{label}",
            children=[
                BT.Movement.MoveTargetInteractAndDialog(
                    x=xy[0],
                    y=xy[1],
                    dialog_id=dialog_id,
                    pause_on_combat=False,
                    log=True,
                ),
                BT.Player.Wait(500),
            ],
        )
    )


# ---- Planner assembly ---------------------------------------------------


def get_execution_steps() -> list[tuple[str, Callable[[], BehaviorTree]]]:
    return [
        ("Initialize Bot", InitializeBot),
        ("Prepare Outpost", PrepareOutpost),
        ("Farm Loop", FarmLoop),
    ]


def _ensure_botting_tree() -> BottingTree:
    global _botting_tree
    if _botting_tree is None:
        _botting_tree = BottingTree.Create(
            MODULE_NAME,
            main_routine=get_execution_steps(),
            routine_name="COFFarmSequence",
            repeat=True,
            reset=False,
            auto_start=False,
            multi_account=False,
            isolation_enabled=True,
        )
        # DervBoneFarmer's rotation runs as a BT service alongside the planner.
        # HeroAI stays off (Config.Pacifist); the build reads self.status set
        # by planner SetPhase(...) nodes and gates its own explorable /
        # non-combat checks inside the rotation tree.
        _botting_tree.AddBuild(get_derv_build())
        # Route wipe recovery based on inventory state.
        _botting_tree.EnsurePartyWipeRecoveryService(
            default_step_name=_choose_recovery_step_name,
        )
    return _botting_tree


# ---- Widget entry point -------------------------------------------------


def main() -> None:
    global _initialized, _ini_key

    if not _initialized:
        if not _ini_key:
            _ini_key = Settings(f"{INI_PATH}/{INI_FILENAME}", "account").name
            if not _ini_key:
                return
        _ensure_botting_tree()
        _initialized = True

    tree = _ensure_botting_tree()
    tree.tick()
    texture = os.path.join(
        PySystem.Console.get_projects_path(),
        "Bots",
        "marks_coding_corner",
        "textures",
        "cof_art.png",
    )
    tree.UI.draw_window(icon_path=texture)


if __name__ == "__main__":
    main()
