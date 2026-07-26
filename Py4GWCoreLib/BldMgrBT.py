from __future__ import annotations

from typing import Any

from .BuildMgr import BuildCoroutine
from .BuildMgr import BuildMgr
from .py4gwcorelib_src.BehaviorTree import BehaviorTree


class BldMgrBT(BuildMgr):
    """BuildMgr whose rotation is a BehaviorTree.

    Subclasses override `build_rotation_tree()`. Constant rotations compile once;
    rotations that depend on live state also override `current_rotation_signature()`
    so the tree recompiles when the signature changes. `get_rotation_tree()` returns
    a stable wrapper safe to register with `bot.AddBuild()` even though the inner
    tree may be swapped later.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.rotation_tree: BehaviorTree | None = None
        self.rotation_signature: Any = None
        self.service_tree: BehaviorTree | None = None

    def build_rotation_tree(self) -> BehaviorTree:
        raise NotImplementedError(f"{type(self).__name__} must override build_rotation_tree()")

    def current_rotation_signature(self) -> Any:
        return None

    def seed_blackboard(self, blackboard: dict) -> None:
        pass

    def current_tree(self) -> BehaviorTree:
        signature = self.current_rotation_signature()
        if self.rotation_tree is None or self.rotation_signature != signature:
            self.rotation_tree = self.build_rotation_tree()
            self.rotation_signature = signature
        return self.rotation_tree

    def reset_rotation_tree(self) -> None:
        if self.rotation_tree is not None:
            self.rotation_tree.reset()
        self.rotation_tree = None
        self.rotation_signature = None

    def get_rotation_tree(self) -> BehaviorTree:
        if self.service_tree is None:
            self.service_tree = BehaviorTree(
                BehaviorTree.ActionNode(
                    name=f"{self.build_name}:Rotation",
                    action_fn=lambda node: self.tick_rotation(node.blackboard, ooc=None),
                )
            )
        return self.service_tree

    def tick_rotation(self, blackboard: dict, ooc: bool | None) -> BehaviorTree.NodeState:
        tree = self.current_tree()
        if isinstance(blackboard, dict):
            tree.blackboard = blackboard
        if ooc is None:
            ooc = not bool(tree.blackboard.get("in_aggro", False))
        tree.blackboard["ooc"] = ooc
        self.seed_blackboard(tree.blackboard)
        return tree.tick()

    def run_phase(self, ooc: bool | None) -> BuildCoroutine:
        self.ResetTickState()
        state = self.tick_rotation(self.current_tree().blackboard, ooc)
        if state in (BehaviorTree.NodeState.SUCCESS, BehaviorTree.NodeState.RUNNING):
            self.SetTickSuccess()
            yield
            return
        fallback = self.ResolveFallback()
        if fallback is not None:
            if ooc is True:
                yield from fallback.ProcessOOC()
            elif ooc is False:
                yield from fallback.ProcessCombat()
            else:
                yield from fallback.ProcessSkillCasting()
            return
        self.SetTickFailure()
        yield

    def ProcessSkillCasting(self) -> BuildCoroutine:
        yield from self.run_phase(None)

    def ProcessCombat(self) -> BuildCoroutine:
        yield from self.run_phase(False)

    def ProcessOOC(self) -> BuildCoroutine:
        yield from self.run_phase(True)


BTBuildMgr = BldMgrBT
