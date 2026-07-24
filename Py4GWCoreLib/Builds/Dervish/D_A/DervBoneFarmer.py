"""DervBoneFarmer — Dervish/Assassin bone farming build for COF.

Ported to `BTBuildMgr`: rotation is a BehaviorTree instead of a
generator, so it composes with a `BottingTree` planner without the
shared `ActionQueueManager` collisions the generator-based rotation
had. Metadata (template, required skills, weapon rules) is unchanged.

Phase communication is via `self.status` — the planner writes one of
the `DervBuildFarmStatus` values, the rotation's condition nodes read
it every tick.
"""
from __future__ import annotations

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import AgentModelID
from Py4GWCoreLib import BTBuildMgr
from Py4GWCoreLib import Key
from Py4GWCoreLib import Keystroke
from Py4GWCoreLib import Player
from Py4GWCoreLib import Profession
from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib import Skill
from Py4GWCoreLib import SpiritModelID
from Py4GWCoreLib import Weapon
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Py4GWCoreLib.routines_src.BehaviourTrees import BT

ENEMY_BLACKLIST = {SpiritModelID.BLOODSONG, SpiritModelID.DESTRUCTION, AgentModelID.CHARR_AXEMASTER}


class DervBuildFarmStatus:
    Setup = 'setup'
    Prepare = 'prepare'
    Kill = 'kill'
    Loot = 'loot'
    Wait = 'wait'


_NON_COMBAT_PHASES = {
    DervBuildFarmStatus.Setup,
    DervBuildFarmStatus.Loot,
    DervBuildFarmStatus.Wait,
}


# ---- Small BT construction helpers (module-local, used only here) --------


def sequence(name: str, *children) -> BehaviorTree:
    return BehaviorTree(BehaviorTree.SequenceNode(name=name, children=list(children)))


def selector(name: str, *children) -> BehaviorTree:
    return BehaviorTree(BehaviorTree.SelectorNode(name=name, children=list(children)))


def condition(name: str, fn) -> BehaviorTree.ConditionNode:
    return BehaviorTree.ConditionNode(name=name, condition_fn=fn)


def action(name: str, fn, aftercast_ms: int = 0) -> BehaviorTree.ActionNode:
    return BehaviorTree.ActionNode(name=name, action_fn=fn, aftercast_ms=aftercast_ms)


def succeeder(name: str) -> BehaviorTree.SucceederNode:
    return BehaviorTree.SucceederNode(name=name)


def optional(cast_tree: BehaviorTree, name: str = "Optional") -> BehaviorTree:
    """Wrap so a cast failure (on cooldown, no energy) doesn't fail the parent."""
    return selector(name, cast_tree, succeeder(f"{name}:Skip"))


class DervBoneFarmer(BTBuildMgr):
    def __init__(self, match_only: bool = False):
        super().__init__(
            name="Derv Bone Farmer",
            required_primary=Profession.Dervish,
            required_secondary=Profession.Assassin,
            template_code='OgCjkqqLrSYiihdftXjhOXhX0kA',
            is_combat_automator_compatible=False,
            required_skills=[
                GLOBAL_CACHE.Skill.GetID("Signet_of_Mystic_Speed"),
                GLOBAL_CACHE.Skill.GetID("Pious_Fury"),
                GLOBAL_CACHE.Skill.GetID("Grenths_Aura"),
                GLOBAL_CACHE.Skill.GetID("Vow_of_Silence"),
                GLOBAL_CACHE.Skill.GetID("Crippling_Victory"),
                GLOBAL_CACHE.Skill.GetID("Reap_Impurities"),
                GLOBAL_CACHE.Skill.GetID("Vow_of_Piety"),
                GLOBAL_CACHE.Skill.GetID("I_Am_Unstoppable"),
            ],
        )
        if match_only:
            return

        self.SetFallback("HeroAI", HeroAI_Build(standalone_fallback=True))

        # Skill IDs pulled out as attributes for readable rotation code.
        self.signet_of_mystic_speed = self.skills[0]
        self.pious_fury = self.skills[1]
        self.grenths_aura = self.skills[2]
        self.vow_of_silence = self.skills[3]
        self.crippling_victory = self.skills[4]
        self.reap_impurities = self.skills[5]
        self.vow_of_piety = self.skills[6]
        self.i_am_unstoppable = self.skills[7]

        # Planner writes here; rotation reads it every tick.
        self.status: str = DervBuildFarmStatus.Wait

    # ---- Per-tick predicates ---------------------------------------------

    def has_buff(self, skill_id: int) -> bool:
        return bool(Routines.Checks.Effects.HasBuff(Player.GetAgentID(), skill_id))

    def has_enough_adrenaline(self, skill_id: int) -> bool:
        slot = GLOBAL_CACHE.SkillBar.GetSlotBySkillID(skill_id)
        if not (1 <= slot <= 8):
            return False
        data = GLOBAL_CACHE.SkillBar.GetSkillData(slot)
        return data.adrenaline_a >= Skill.Data.GetAdrenaline(skill_id)

    def filtered_enemies_in_range(self):
        px, py = Player.GetXY()
        arr = Routines.Agents.GetFilteredEnemyArray(px, py, Range.Spellcast.value)
        return [aid for aid in arr if Agent.GetModelID(aid) not in ENEMY_BLACKLIST], px, py

    # ---- Small BT builders ------------------------------------------------

    def cast_gated(self, name: str, skill_id: int, gate_fn, aftercast_ms: int) -> BehaviorTree:
        """Cast `skill_id` if `gate_fn()` and CastSkillID's own preconditions
        all pass. The gate re-evaluates every tick."""
        return sequence(
            f"Cast:{name}",
            condition(f"Gate:{name}", gate_fn),
            BT.Skills.CastSkillID(skill_id, aftercast_delay=aftercast_ms, log=False),
        )

    def cast_plain(self, name: str, skill_id: int, aftercast_ms: int) -> BehaviorTree:
        """Cast `skill_id` if CastSkillID's own preconditions pass (energy,
        readiness, slot resolution). No extra gate."""
        return BT.Skills.CastSkillID(skill_id, aftercast_delay=aftercast_ms, log=False)

    def swap_to_scythe(self) -> BehaviorTree:
        def needs() -> bool:
            return Agent.GetWeaponType(Player.GetAgentID())[0] != Weapon.Scythe

        def press(node) -> BehaviorTree.NodeState:
            Keystroke.PressAndRelease(Key.F1.value)
            return BehaviorTree.NodeState.SUCCESS

        return sequence(
            "SwapToScythe",
            condition("NeedsScythe", needs),
            action("PressF1", press, aftercast_ms=100),
        )

    def swap_to_shield_set(self) -> BehaviorTree:
        def needs() -> bool:
            return Agent.GetWeaponType(Player.GetAgentID())[0] == Weapon.Scythe

        def press(node) -> BehaviorTree.NodeState:
            Keystroke.PressAndRelease(Key.F2.value)
            return BehaviorTree.NodeState.SUCCESS

        return sequence(
            "SwapToShieldSet",
            condition("NeedsShield", needs),
            action("PressF2", press, aftercast_ms=750),
        )

    # ---- Branches ---------------------------------------------------------

    def outpost_guard(self) -> BehaviorTree:
        """Skip the whole rotation when we're not in an explorable map.
        Returns SUCCESS in outposts so the outer selector terminates
        without touching any of the combat branches or the shared queue.
        """
        return sequence(
            "OutpostGuard",
            condition("NotExplorable", lambda: not Routines.Checks.Map.IsExplorable()),
            succeeder("SkipInOutpost"),
        )

    def non_combat_guard(self) -> BehaviorTree:
        """Setup / Loot / Wait phases: keep shield set equipped, do nothing else."""
        return sequence(
            "NonCombatGuard",
            condition("InNonCombatPhase", lambda: self.status in _NON_COMBAT_PHASES),
            optional(self.swap_to_shield_set(), name="OptionalShieldSwap"),
        )

    def prepare_branch(self) -> BehaviorTree:
        """Prepare: VoP → GA → VoS (in that order, one per tick).

        Nothing that would strip an enchant (Pious Fury lives only in the
        Kill refresh chain).
        """
        return sequence(
            "PrepareBranch",
            condition("InPrepare", lambda: self.status == DervBuildFarmStatus.Prepare),
            selector(
                "PreparePriority",
                self.cast_gated(
                    "VowOfPiety",
                    self.vow_of_piety,
                    lambda: not self.has_buff(self.vow_of_piety),
                    aftercast_ms=750,
                ),
                self.cast_gated(
                    "GrenthsAura",
                    self.grenths_aura,
                    lambda: not self.has_buff(self.grenths_aura),
                    aftercast_ms=100,
                ),
                self.cast_gated(
                    "VowOfSilence",
                    self.vow_of_silence,
                    lambda: (
                        self.has_buff(self.grenths_aura)
                        and self.has_buff(self.vow_of_piety)
                    ),
                    aftercast_ms=100,
                ),
            ),
        )

    def refresh_chain(self) -> BehaviorTree:
        """PF → GA → VoS refresh. Commits only when both GA and VoS are off
        cooldown (checked at tick time via `IsSkillIDReady`) — otherwise
        PF would strip our current VoS and the chain would stall mid-refresh.
        PF itself is optional; GA and VoS are required.
        """
        def both_ready() -> bool:
            return (
                Routines.Checks.Skills.IsSkillIDReady(self.grenths_aura)
                and Routines.Checks.Skills.IsSkillIDReady(self.vow_of_silence)
            )

        return sequence(
            "RefreshChain",
            condition("GAandVoSReady", both_ready),
            self.cast_plain("PiousFury", self.pious_fury, aftercast_ms=100),
            self.cast_plain("GrenthsAura", self.grenths_aura, aftercast_ms=100),
            self.cast_plain("VowOfSilence", self.vow_of_silence, aftercast_ms=100),
        )

    def engagement(self) -> BehaviorTree:
        """Swap to scythe, target nearest filtered enemy, hit adrenaline
        attacks. Auto-attack fills the gap between adrenaline windows."""
        def enemy_present() -> bool:
            enemies, _, _ = self.filtered_enemies_in_range()
            return bool(enemies)

        def interact_nearest(node) -> BehaviorTree.NodeState:
            enemies, px, py = self.filtered_enemies_in_range()
            if not enemies:
                return BehaviorTree.NodeState.FAILURE
            nearest = min(
                enemies,
                key=lambda aid: (
                    (Agent.GetXY(aid)[0] - px) ** 2
                    + (Agent.GetXY(aid)[1] - py) ** 2
                ),
            )
            Player.Interact(nearest, False)
            return BehaviorTree.NodeState.SUCCESS

        return sequence(
            "Engagement",
            condition("EnemyPresent", enemy_present),
            # If we're already on scythe the swap sub-sequence would FAIL
            # (its NeedsScythe condition is False), which would abort the
            # engagement before we ever reach the interact/attack nodes.
            # Wrap it so "no swap needed" reads as SUCCESS and we continue.
            optional(self.swap_to_scythe(), name="OptionalScytheSwap"),
            action("InteractNearest", interact_nearest, aftercast_ms=100),
            selector(
                "AdrenalineAttackChoice",
                self.cast_gated(
                    "CripplingVictory",
                    self.crippling_victory,
                    lambda: self.has_enough_adrenaline(self.crippling_victory),
                    aftercast_ms=200,
                ),
                self.cast_gated(
                    "ReapImpurities",
                    self.reap_impurities,
                    lambda: self.has_enough_adrenaline(self.reap_impurities),
                    aftercast_ms=200,
                ),
                # Fall-through: swap + target counted as useful work; auto-attack
                # fills the adrenaline gap between named attacks.
                succeeder("AutoAttackFallthrough"),
            ),
        )

    def kill_branch(self) -> BehaviorTree:
        """Kill priority order:

          1. SoMS when VoS is up and SoMS isn't already stanced — primes
             the next VoS cast to land instantly.
          2. IAU whenever it's off cooldown — knockdown-immunity stance.
          3. Refresh chain (PF → GA → VoS) when both GA and VoS are ready.
          4. Engagement — swap, target, adrenaline attacks, auto-attack.
        """
        return sequence(
            "KillBranch",
            condition("InKill", lambda: self.status == DervBuildFarmStatus.Kill),
            selector(
                "KillPriority",
                self.cast_gated(
                    "SignetOfMysticSpeed",
                    self.signet_of_mystic_speed,
                    lambda: (
                        self.has_buff(self.vow_of_silence)
                        and not self.has_buff(self.signet_of_mystic_speed)
                    ),
                    aftercast_ms=250,
                ),
                self.cast_plain("IAmUnstoppable", self.i_am_unstoppable, aftercast_ms=100),
                self.refresh_chain(),
                self.engagement(),
            ),
        )

    # ---- Root rotation tree ----------------------------------------------

    def build_rotation_tree(self) -> BehaviorTree:
        return selector(
            "DervBoneRotation",
            self.outpost_guard(),
            self.non_combat_guard(),
            self.prepare_branch(),
            self.kill_branch(),
            succeeder("Idle"),
        )
