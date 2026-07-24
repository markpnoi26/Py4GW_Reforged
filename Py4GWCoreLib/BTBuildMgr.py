from __future__ import annotations

from typing import Any

from .BuildMgr import BuildCoroutine
from .BuildMgr import BuildMgr
from .py4gwcorelib_src.BehaviorTree import BehaviorTree


class BTBuildMgr(BuildMgr):
    """BuildMgr whose combat rotation is a BehaviorTree instead of a generator.

    Subclasses override `build_rotation_tree()`. Rotation is registered as a
    service on the parent BottingTree via `bot.AddBuild(build)` and uses
    `BT.Skills.CastSkillID` / `CastSkillSlot` for casts, bypassing the
    process-wide ActionQueueManager that generator-style BuildMgr rotations
    collide with when composed under a planner.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.bt_rotation_cache: BehaviorTree | None = None

    def build_rotation_tree(self) -> BehaviorTree:
        raise NotImplementedError(
            f"{type(self).__name__} must override build_rotation_tree()"
        )

    def get_rotation_tree(self) -> BehaviorTree:
        if self.bt_rotation_cache is None:
            self.bt_rotation_cache = self.build_rotation_tree()
        return self.bt_rotation_cache

    def reset_rotation_tree(self) -> None:
        if self.bt_rotation_cache is not None:
            self.bt_rotation_cache.reset()
        self.bt_rotation_cache = None

    def process_skill_casting(self) -> BuildCoroutine:
        """Tick the rotation once per HeroAIHeadlessTree frame."""
        self.get_rotation_tree().tick()
        yield
