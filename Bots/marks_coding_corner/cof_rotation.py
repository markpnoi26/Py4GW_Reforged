"""COF farm phase constants + shared DervBoneFarmer instance.

Now that `DervBoneFarmer` is a `BTBuildMgr` and the botting tree exposes
`bot.AddBuild(build)`, the rotation ticker that used to live here is gone.
This module just holds the shared build singleton and re-exports the phase
constants + enemy blacklist so `DervCOFFarmBT.py`'s imports don't churn.
"""
from __future__ import annotations

from Py4GWCoreLib.Builds.Dervish.D_A.DervBoneFarmer import (
    DervBoneFarmer,
    DervBuildFarmStatus,
    ENEMY_BLACKLIST,
)

# ---- Public phase constants (proxied from DervBuildFarmStatus) -----------

PHASE_SETUP = DervBuildFarmStatus.Setup
PHASE_PREPARE = DervBuildFarmStatus.Prepare
PHASE_KILL = DervBuildFarmStatus.Kill
PHASE_LOOT = DervBuildFarmStatus.Loot
PHASE_WAIT = DervBuildFarmStatus.Wait

__all__ = [
    "PHASE_SETUP",
    "PHASE_PREPARE",
    "PHASE_KILL",
    "PHASE_LOOT",
    "PHASE_WAIT",
    "ENEMY_BLACKLIST",
    "get_derv_build",
]

# ---- BuildMgr singleton --------------------------------------------------

_derv_build: DervBoneFarmer | None = None


def get_derv_build() -> DervBoneFarmer:
    """Lazy-instantiate the DervBoneFarmer so skill-ID lookups happen only
    once the game client is up (called from within the widget's `main`)."""
    global _derv_build
    if _derv_build is None:
        _derv_build = DervBoneFarmer()
    return _derv_build
