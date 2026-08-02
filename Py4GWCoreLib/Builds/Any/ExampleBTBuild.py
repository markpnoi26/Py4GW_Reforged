"""Minimal `BTBuildMgr` example — targets the nearest enemy in Spellcast range
and does nothing else. Useful as a copy-paste starting point when authoring a
new BT-native rotation."""
from __future__ import annotations

from Py4GWCoreLib import Agent
from Py4GWCoreLib import BTBuildMgr
from Py4GWCoreLib import Player
from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree


class ExampleBTBuild(BTBuildMgr):
    def __init__(self, match_only: bool = False):
        super().__init__(
            name="Example BT Build",
            required_primary=None,
            required_secondary=None,
            template_code="",
            is_combat_automator_compatible=False,
            required_skills=[],
        )
        if match_only:
            return

    def build_rotation_tree(self) -> BehaviorTree:
        def nearest_enemy_present() -> bool:
            px, py = Player.GetXY()
            return len(Routines.Agents.GetFilteredEnemyArray(px, py, Range.Spellcast.value)) > 0

        def target_nearest(node) -> BehaviorTree.NodeState:
            px, py = Player.GetXY()
            enemies = Routines.Agents.GetFilteredEnemyArray(px, py, Range.Spellcast.value)
            if not enemies:
                return BehaviorTree.NodeState.FAILURE
            nearest = min(enemies, key=lambda aid: (
                (Agent.GetXY(aid)[0] - px) ** 2 + (Agent.GetXY(aid)[1] - py) ** 2
            ))
            Player.Interact(nearest, False)
            return BehaviorTree.NodeState.SUCCESS

        rotation = BehaviorTree.SelectorNode(name="ExampleBTRotation", children=[
            BehaviorTree.SequenceNode(name="Engage", children=[
                BehaviorTree.ConditionNode(name="EnemyPresent", condition_fn=nearest_enemy_present),
                BehaviorTree.ActionNode(name="TargetNearest", action_fn=target_nearest, aftercast_ms=100),
            ]),
            BehaviorTree.SucceederNode(name="Idle"),
        ])
        return BehaviorTree(rotation)
