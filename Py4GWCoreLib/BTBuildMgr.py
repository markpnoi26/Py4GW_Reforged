"""BTBuildMgr — a BuildMgr whose combat rotation is a BehaviorTree.

Standard `BuildMgr` subclasses implement `ProcessSkillCasting` as a yield-
based generator that queues casts through the process-wide
`ActionQueueManager`. That model assumes the build owns the queue and
regularly calls `ResetAllQueues()` to clear stale state — fine under
HeroAI, hostile to any `BottingTree` planner that shares the same queue
for movement, dialogs, and interacts.

`BTBuildMgr` swaps the contract. Subclasses override `BuildRotationTree()`
to return a `BehaviorTree`. That tree is ticked as a service on the
parent `BottingTree` (see `BottingTree.AddBuild(build)`), composes with
planner branches without colliding, and uses `BT.Skills.CastSkillID` /
`CastSkillSlot` for casts — those call `GLOBAL_CACHE.SkillBar.UseSkill`
directly rather than queueing through `ActionQueueManager`.

Everything BuildMgr already gives you (name, template code, required
skills, `LoadSkillBar`, fallback registration, BuildRegistry
discovery) keeps working because we are still a BuildMgr subclass.

A shim `ProcessSkillCasting` is kept so `HeroAIHeadlessTree` can still
tick a `BTBuildMgr` via its existing `next(build.ProcessSkillCasting(),
None)` pattern — each `next()` call advances the rotation tree by one
frame.
"""
from __future__ import annotations

from typing import Any

from .BuildMgr import BuildCoroutine
from .BuildMgr import BuildMgr
from .py4gwcorelib_src.BehaviorTree import BehaviorTree


class BTBuildMgr(BuildMgr):
    """BuildMgr variant whose rotation is a BehaviorTree.

    Subclasses must override `BuildRotationTree()` and return the tree
    that will drive the rotation. The tree is built lazily (on first
    tick) and cached; `ResetRotationTree()` drops the cache if you need
    to rebuild it after mutating build parameters.

    Gating (explorable check, phase filter, energy guards, etc.) should
    live inside the rotation tree itself as `ConditionNode`s at the
    branches that need them — that keeps the rotation self-describing
    and lets it work whether it's ticked by a `BottingTree` service or
    by `HeroAIHeadlessTree`.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bt_rotation_cache: BehaviorTree | None = None

    # ---- Subclass hook -------------------------------------------------

    def build_rotation_tree(self) -> BehaviorTree:
        """Return the BehaviorTree that drives this build's rotation.

        Called once per BuildMgr instance; the result is then cached and
        ticked every frame. Must be overridden by subclasses.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must override BuildRotationTree()"
        )

    # ---- Cached tree accessor -----------------------------------------

    def get_rotation_tree(self) -> BehaviorTree:
        """Return the cached rotation tree, building it on first access."""
        if self._bt_rotation_cache is None:
            self._bt_rotation_cache = self.build_rotation_tree()
        return self._bt_rotation_cache

    def reset_rotation_tree(self) -> None:
        """Reset the cached tree so the next tick rebuilds it from scratch.

        Useful after a hot-swap of build parameters or a full bot stop/start.
        """
        if self._bt_rotation_cache is not None:
            self._bt_rotation_cache.reset()
        self._bt_rotation_cache = None

    # ---- HeroAIHeadlessTree compatibility shim -------------------------

    def process_skill_casting(self) -> BuildCoroutine:
        """Tick the rotation tree once and yield.

        Lets `HeroAIHeadlessTree` drive a `BTBuildMgr` via its existing
        `next(build.ProcessSkillCasting(), None)` per-frame pattern. Each
        `next()` call runs one BT tick and returns; the tree preserves
        its state across calls, so an ActionNode with `aftercast_ms`
        continues to hold across frames as expected.
        """
        self.get_rotation_tree().tick()
        yield
