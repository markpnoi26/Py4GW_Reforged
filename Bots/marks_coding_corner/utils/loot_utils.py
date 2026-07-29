from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import AgentArray
from Py4GWCoreLib import Bags
from Py4GWCoreLib import Item
from Py4GWCoreLib import ItemArray
from Py4GWCoreLib import ModelID
from Py4GWCoreLib import Player
from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings


INI_PATH = "Inventory/InventoryPlus"
INI_FILENAME = "InventoryPlus.ini"

SALVAGE_BLACKLIST_MODEL_IDS = {31202, 31203, 31204}  # glacial stones
SALVAGE_ALLOWED_RARITIES = {"White", "Blue", "Purple", "Gold"}

VIABLE_LOOT = {
    ModelID.Gold_Coins,
    ModelID.Bone,
    ModelID.Plant_Fiber,
    ModelID.Pile_Of_Glittering_Dust,
    ModelID.Feather,
    ModelID.Abnormal_Seed,
    ModelID.Feathered_Crest,
    ModelID.Shadowy_Remnants,
    ModelID.Bottle_Of_Rice_Wine,
    ModelID.Bottle_Of_Vabbian_Wine,
    ModelID.Dwarven_Ale,
    ModelID.Eggnog,
    ModelID.Hunters_Ale,
    ModelID.Shamrock_Ale,
    ModelID.Witchs_Brew,
    ModelID.Zehtukas_Jug,
    ModelID.Aged_Dwarven_Ale,
    ModelID.Bottle_Of_Grog,
    ModelID.Krytan_Brandy,
    ModelID.Spiked_Eggnog,
    ModelID.Vial_Of_Dye,
    ModelID.Monstrous_Claw,
    ModelID.Monstrous_Eye,
    ModelID.Lockpick,
    ModelID.Candy_Apple,
    ModelID.Pumpkin_Cookie,
    ModelID.Candy_Corn,
    ModelID.Squash_Serum,
    ModelID.Trick_Or_Treat_Bag,
    ModelID.Vial_Of_Absinthe,
    ModelID.Slice_Of_Pumpkin_Pie,
    ModelID.Candy_Cane_Shard,
    ModelID.Fruitcake,
    ModelID.Snowman_Summoner,
    ModelID.Frosty_Tonic,
}


def inventory_bag_items() -> list[int]:
    bag_list = ItemArray.CreateBagList(Bags.Backpack, Bags.BeltPouch, Bags.Bag1, Bags.Bag2)
    return ItemArray.GetItemArray(bag_list)


def collect_unidentified_item_ids() -> list[int]:
    return [
        item_id for item_id in inventory_bag_items()
        if not Item.Usage.IsIdentified(item_id)
    ]


def collect_salvageable_item_ids(
    allowed_rarities: set[str] = SALVAGE_ALLOWED_RARITIES,
    salvage_golds: bool = True,
) -> list[int]:
    result: list[int] = []
    for item_id in inventory_bag_items():
        if not Item.Usage.IsSalvageable(item_id):
            continue
        if Item.Usage.IsSalvageKit(item_id) or Item.Usage.IsIDKit(item_id):
            continue
        if Item.GetModelID(item_id) in SALVAGE_BLACKLIST_MODEL_IDS:
            continue
        _, rarity = Item.Rarity.GetRarity(item_id)
        if rarity not in allowed_rarities:
            continue
        if rarity == "Gold" and not salvage_golds:
            continue
        result.append(item_id)
    return result


def is_valid_item(item_id):
    if not Agent.IsValid(item_id):
        return False
    owner_id = Agent.GetItemAgentOwnerID(item_id)
    return owner_id == Player.GetAgentID() or owner_id == 0


def get_valid_loot_array(viable_loot=VIABLE_LOOT, loot_salvagables=False):
    loot_array = AgentArray.GetItemArray()
    loot_array = AgentArray.Filter.ByDistance(loot_array, Player.GetXY(), Range.Spellcast.value * 3.00)

    agent_array = AgentArray.GetItemArray()

    item_array_salv = []
    if loot_salvagables:
        item_array_salv = AgentArray.Filter.ByCondition(
            agent_array, lambda agent_id: Item.Usage.IsSalvageable(Agent.GetItemAgentItemID(agent_id))
        )

    filtered_agent_ids = []
    for agent_id in loot_array[:]:
        item_id = Agent.GetItemAgentItemID(agent_id)
        model_id = Item.GetModelID(item_id)
        if model_id in viable_loot and is_valid_item(agent_id):
            # Only keep black (10) and white (12) dyes; skip other colors.
            if (
                model_id == ModelID.Vial_Of_Dye
                and (GLOBAL_CACHE.Item.GetDyeColor(item_id) == 10 or GLOBAL_CACHE.Item.GetDyeColor(item_id) == 12)
                or model_id != ModelID.Vial_Of_Dye
            ):
                filtered_agent_ids.append(agent_id)
    return list(set(filtered_agent_ids + item_array_salv))


def identify_and_salvage_items(salvage_golds: bool = True):
    """Bypasses AutoInventoryHandler and drives the low-level queue routines
    directly with a caller-collected item list."""
    yield from Routines.Yield.wait(1500)

    unidentified = collect_unidentified_item_ids()
    if unidentified:
        yield from Routines.Yield.Items.IdentifyItems(unidentified)
        yield from Routines.Yield.wait(500)

    salvageable = collect_salvageable_item_ids(salvage_golds=salvage_golds)
    if salvageable:
        yield from Routines.Yield.Items.SalvageItems(salvageable)


def move_all_crafting_materials_to_storage():
    farmable_mats = {
        ModelID.Wood_Plank,
        ModelID.Scale,
        ModelID.Tanned_Hide_Square,
        ModelID.Bolt_Of_Cloth,
        ModelID.Granite_Slab,
        ModelID.Bone,
        ModelID.Iron_Ingot,
        ModelID.Pile_Of_Glittering_Dust,
        ModelID.Feather,
    }
    for item_id in inventory_bag_items():
        if GLOBAL_CACHE.Item.GetModelID(item_id) in farmable_mats:
            GLOBAL_CACHE.Inventory.DepositItemToStorage(item_id)
            yield from Routines.Yield.wait(250)


def set_autoloot_options_for_custom_bots(salvage_golds=False, module_active=False):
    """Persist loot options to the InventoryPlus INI. Only relevant when the
    InventoryPlus widget is enabled (module_active=True) — our own
    identify_and_salvage_items bypasses the widget entirely."""
    cfg = Settings(f"{INI_PATH}/{INI_FILENAME}", "account")

    cfg.set("AutoManager", "module_active", module_active)

    cfg.set("AutoSalvage", "salvage_whites", True)
    cfg.set("AutoSalvage", "salvage_rare_materials", False)
    cfg.set("AutoSalvage", "salvage_blues", True)
    cfg.set("AutoSalvage", "salvage_purples", True)
    cfg.set("AutoSalvage", "salvage_golds", salvage_golds)

    cfg.set("AutoIdentify", "id_whites", True)
    cfg.set("AutoIdentify", "id_blues", True)
    cfg.set("AutoIdentify", "id_purples", True)
    cfg.set("AutoIdentify", "id_golds", True)
    cfg.set("AutoIdentify", "id_greens", False)

    cfg.set("AutoDeposit", "deposit_trophies", False)
    cfg.set("AutoDeposit", "deposit_materials", False)
    cfg.set("AutoDeposit", "deposit_event_items", False)
    cfg.set("AutoDeposit", "deposit_dyes", False)
    cfg.set("AutoDeposit", "deposit_golds", not salvage_golds)
    cfg.set("AutoDeposit", "deposit_greens", True)
    cfg.set("AutoDeposit", "keep_gold", 10000)

    cfg.set("AutoSalvage", "salvage_blacklist", ",".join(str(m) for m in SALVAGE_BLACKLIST_MODEL_IDS))
