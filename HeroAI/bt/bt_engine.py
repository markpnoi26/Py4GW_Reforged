"""BT-native HeroAI engine. Satisfies the same driver protocol as HeroAI_Build
(set_cached_data / ProcessOOC / ProcessCombat / DidTickSucceed / contract
methods) so headless_tree.py and the widget need no structural changes."""

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.BldMgrBT import BldMgrBT
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.Routines import Routines
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree

from .frame_seed import seed_frame


class HeroAIBTEngine(BldMgrBT):
    def __init__(self, cached_data=None, standalone_fallback: bool = False):
        super().__init__(
            name="HeroAI BT",
            template_code="HEROAI_BT",
            IsFixedBuild=True,
        )
        self.cached_data = cached_data
        self.standalone_fallback = standalone_fallback

    def set_cached_data(self, cached_data) -> None:
        self.cached_data = cached_data

    def get_cached_data(self):
        if self.cached_data is None:
            from HeroAI.cache_data import CacheData
            self.cached_data = CacheData()
        return self.cached_data

    def current_rotation_signature(self):
        primary, secondary = Agent.GetProfessions(Player.GetAgentID())
        current_skills = tuple(int(skill_id) for skill_id in self._get_current_skills())
        return (
            int(Map.GetMapID()),
            int(Map.GetRegion()[0]),
            int(Map.GetDistrict()),
            int(Map.GetLanguage()[0]),
            int(primary),
            int(secondary),
            *current_skills,
        )

    def build_rotation_tree(self) -> BehaviorTree:
        from .rotation import build_rotation_tree
        return build_rotation_tree()

    def seed_blackboard(self, blackboard: dict) -> None:
        seed_frame(blackboard, self.get_cached_data())

    def prepare_tick(self):
        cached_data = self.get_cached_data()
        if not Routines.Checks.Map.MapValid():
            return None
        if not Map.IsExplorable() or Map.IsInCinematic():
            return None
        player_id = Player.GetAgentID()
        if not Agent.IsAlive(player_id) or Agent.IsKnockedDown(player_id):
            return None
        cached_data.Update()
        cached_data.UpdateCombat()
        return cached_data

    def run_engine_phase(self, ooc: bool):
        state = self.tick_rotation(self.current_tree().blackboard, ooc=ooc)
        if state in (BehaviorTree.NodeState.SUCCESS, BehaviorTree.NodeState.RUNNING):
            self.SetTickSuccess()
        else:
            self.SetTickFailure()

    def ProcessOOC(self):
        self.ResetTickState()
        cached_data = self.prepare_tick()
        if cached_data is None or cached_data.data.in_aggro:
            self.SetTickFailure()
            yield
            return
        self.run_engine_phase(ooc=True)
        yield

    def ProcessCombat(self):
        self.ResetTickState()
        cached_data = self.prepare_tick()
        if cached_data is None or not cached_data.data.in_aggro:
            self.SetTickFailure()
            yield
            return
        self.run_engine_phase(ooc=False)
        yield

    def ProcessSkillCasting(self):
        self.ResetTickState()
        cached_data = self.prepare_tick()
        if cached_data is None:
            self.SetTickFailure()
            yield
            return
        if cached_data.data.in_aggro:
            yield from self.ProcessCombat()
        else:
            yield from self.ProcessOOC()

    def EnsureBuildContract(self, cached_data=None):
        if cached_data is not None:
            self.set_cached_data(cached_data)
        return self

    def GetBuildContract(self):
        return self

    def ClearBuildContract(self) -> None:
        self.reset_rotation_tree()

    def ApplyBlockedSkillIDs(self, blocked_skill_ids: list[int] | None = None) -> None:
        combat_handler = getattr(self.get_cached_data(), "combat_handler", None)
        if combat_handler is not None and hasattr(combat_handler, "ApplyBlockedSkillIDs"):
            combat_handler.ApplyBlockedSkillIDs(blocked_skill_ids)
