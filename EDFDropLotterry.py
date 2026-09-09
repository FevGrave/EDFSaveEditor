"""
Unified EDF drop-lottery RNG findings across EDF6, EDF4.1, and (partially) EDF5, all reverse-engineered via Ghidra RE against their live binaries. All 3 games share the same "sgs" engine DropItemManager architecture (a Weapon/Armor/HealSmall/HealBig kind table) and, where checked, byte-identical 64-bit LCG constants - confirmed independently in EDF6.dll AND EDF4.1's ORGEDF41.exe.

Coverage differs per game and is flagged inline:
  EDF6   - fully verified end to end: the kind pick (STAGE 2) and the real per-weapon pick (STAGE 0, live WEAPONTABLE.json P3 weights).
  EDF4.1 - kind-pick roll shape confirmed (SpawnDrops, FUN_1401ae160); the 4 kind weights are runtime/CPK-loaded, not static binary constants, so EDF41_KIND_WEIGHTS stays a placeholder; the per-weapon pick within the Weapon kind is not yet located.
  EDF5   - RTTI class layout (DropItemManager / Unit / Singleton<DropItemManager>) confirmed identical to EDF6/EDF4.1; no addresses vtable-walked yet.
"""

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

MASK64 = 0xFFFFFFFFFFFFFFFF

# Shared 64-bit LCG - byte-identical multiplier/increment confirmed in both EDF6.dll and EDF4.1's ORGEDF41.exe.
LCG_MULT = 0x5D588B656C078965
LCG_INC = 0x269EC3


def lcg_next(state: int) -> int:
    """One step of the shared engine LCG (state = state * LCG_MULT + LCG_INC). Only the high bits are ever consumed by the game; callers slice off the top 16 or 32 bits, never the raw low word."""
    return (state * LCG_MULT + LCG_INC) & MASK64


def weighted_pick(state: int, weights: Sequence[int]) -> Tuple[int, int]:
    """Shared "roll = high32(next_state) * total_weight >> 32, walk-and-subtract" kernel - EDF6's kind selector (FUN_1802ca610) and EDF4.1's SpawnDrops kind roll (FUN_1401ae160) both do exactly this. Returns (new_state, selected_index); falls through to the last index if nothing goes negative, matching both binaries."""
    total_weight = sum(weights)
    state = lcg_next(state)
    if total_weight <= 0:
        return state, 0

    high32 = (state >> 32) & 0xFFFFFFFF
    scaled = (high32 * total_weight) >> 32

    selected = len(weights) - 1
    remaining = scaled
    for i, w in enumerate(weights):
        remaining -= w
        if remaining < 0:
            selected = i
            break

    return state, selected


DROP_KIND_NAMES = ["Weapon", "Armor", "HealingSmall", "HealingBig"]  # same names/order/count confirmed in all 3 games


# ============================== EDF6 ==============================
# EDF6.dll, image base 0x180000000. Fully verified end to end.

EDF6_DROP_KIND_WEIGHTS = [6, 15, 14, 3]  # DropItemManager ctor, FUN_1802c68d0

# The EDF6 "kind" Mersenne Twister (FUN_1802c92e0/FUN_1802c7190/FUN_1802cae10). Standard MT19937 core, non-standard tempering constants.
MT_N = 624
MT_MAGIC = 0x9908B0DF
MT_SEED_MULT = 0x6C078965  # = 1812433253, verified seeding multiplier
MT_TEMPER_B_MASK = 0xFFFFFFFF  # verified as a full (no-op) mask in this build
MT_TEMPER_C_MASK = 0xFF3A58AD  # VERIFIED non-standard (vanilla: 0x9D2C5680)
MT_TEMPER_D_MASK = 0xFFFFDF8C  # VERIFIED non-standard (vanilla: 0xEFC60000)


class EDF6MT19937:
    """Generator matching FUN_1802cae10/FUN_1802c7190 exactly, including the non-standard tempering constants. Re-seeded fresh every time FUN_1802c92e0 runs, from the shared persistent LCG state."""

    def __init__(self, seed32: int):
        self.mt = [0] * MT_N
        self.mt[0] = seed32 & 0xFFFFFFFF
        for i in range(1, MT_N):
            prev = self.mt[i - 1]
            self.mt[i] = (MT_SEED_MULT * (prev ^ (prev >> 30)) + i) & 0xFFFFFFFF
        self.index = MT_N  # forces a regen on first draw, matches the binary

    def _generate(self):
        for i in range(MT_N):
            y = (self.mt[i] & 0x80000000) | (self.mt[(i + 1) % MT_N] & 0x7FFFFFFF)
            next_val = self.mt[(i + 397) % MT_N] ^ (y >> 1)
            if y & 1:
                next_val ^= MT_MAGIC
            self.mt[i] = next_val & 0xFFFFFFFF
        self.index = 0

    def next_u32(self) -> int:
        if self.index >= MT_N:
            self._generate()
        y = self.mt[self.index]
        self.index += 1
        y ^= (y >> 11) & MT_TEMPER_B_MASK
        y ^= (y & MT_TEMPER_C_MASK) << 7
        y ^= (y & MT_TEMPER_D_MASK) << 15
        y ^= y >> 18
        return y & 0xFFFFFFFF

    def below(self, n: int) -> int:
        """Unbiased int in [0, n) via rejection sampling, matching FUN_1802c7190's observable behavior (uniform, unbiased, in-range) even if the exact bit-path differs slightly for reduced-width draws."""
        if n <= 0:
            return 0
        limit = ((0xFFFFFFFF + 1) // n) * n
        while True:
            r = self.next_u32()
            if r < limit:
                return r % n


def edf6_seed_mt_from_lcg(lcg_state: int) -> Tuple[int, "EDF6MT19937"]:
    """Reseed step from FUN_1802c92e0: advance the shared LCG, then seed a fresh EDF6MT19937 from its high 32 bits. Returns (new_lcg_state, mt_instance)."""
    lcg_state = lcg_next(lcg_state)
    high32 = (lcg_state >> 32) & 0xFFFFFFFF
    seed32 = (high32 * 0xFFFFFFFF) >> 32
    return lcg_state, EDF6MT19937(seed32)


# Resolving a Weapon or Armor "kind" into a macro pool split (STAGE 2's flat-weight step, FUN_1802c92e0) - decides how much of the draw goes to weapon vs armor pool overall, NOT the per-weapon selection (see STAGE 0 below for that).
EDF6_WEAPON_POOL_FLAT_WEIGHT = 600  # literal from FUN_1802c92e0
EDF6_ARMOR_POOL_FLAT_WEIGHT = 250   # literal from FUN_1802c92e0

DEFAULT_ELIGIBLE_WEAPON_INDICES = [0, 1, 2, 3, 4]  # placeholder stand-in for a mission's macro-pool eligibility list, NOT real data


def edf6_resolve_drop_index(
    mt: EDF6MT19937,
    eligible_catalog_indices: Sequence[int],
    flat_weight: int,
) -> Optional[int]:
    """Kernel from FUN_1802c92e0: every eligible catalog index gets the same flat weight; draws uniform via MT19937, then cumulative-subtracts across the eligible list until it lands. Returns the selected catalog index, or None if the list is empty."""
    if not eligible_catalog_indices:
        return None

    total_weight = flat_weight * len(eligible_catalog_indices)
    draw = mt.below(total_weight)

    remaining = draw
    for idx in eligible_catalog_indices:
        if remaining < flat_weight:
            return idx
        remaining -= flat_weight

    return eligible_catalog_indices[-1]  # matches the binary's fallthrough


# STAGE 0, the real per-weapon filter + weighted pick (FUN_1800d81e0/FUN_1800d95c0). Field layout (P0-P8) cross-verified against the community wiki's field map and FUN_1800e1cf0's own column reads.

@dataclass
class WeaponTableEntry:
    """One row of EDF6's WeaponTable. catalog_index is this entry's position in the table (0-based), used as the "weapon-catalog index" elsewhere in this module."""
    catalog_index: int
    name: str               # P0
    sgo_path: str            # P1
    category: int            # P2 -- weapon category/class enum
    drop_weight: float       # P3 -- 1 for base game, 3 for DLC-pack entries
    level_req: float         # P4 -- level-band value checked by the filter
    availability: int        # P5 -- 0 collectible, 1 starter item, 3 (some base-game promo entries)
    tag_count: int           # P6 count -- 0..8; >0 unlocks the level tolerance band and starter-item exception
    locked: bool              # P7 -- true if locked/unreleased
    pack_id: int              # P8 -- 0 base game, 1 DLC pack 1, 2 DLC pack 2


def edf6_weapon_matches_drop_filter(
    entry: WeaponTableEntry,
    active_pack_id: int,
    level_min: float,
    level_max: float,
    level_tolerance: float,
) -> bool:
    """From FUN_1800d81e0, the real weapon_matches_drop_class_and_level: all three gates (availability, pack/DLC, level-band) must pass. NOT modeled: the binary's spatial/anti-duplicate hash check, which affects duplicate nearby pickups but not drop odds."""
    availability_ok = (entry.availability == 0) or (
        entry.availability == 1 and entry.tag_count != 0
    )
    if not availability_ok:
        return False

    pack_ok = (entry.pack_id == 0) or (entry.pack_id == active_pack_id)
    if not pack_ok:
        return False

    tolerance = level_tolerance if entry.tag_count != 0 else 0.0
    return level_min <= entry.level_req <= level_max + tolerance


def edf6_resolve_weapon_drop(
    mt: EDF6MT19937,
    candidates: Sequence[WeaponTableEntry],
) -> Optional[WeaponTableEntry]:
    """From FUN_1800d95c0's second half: sum real P3 weights over the filtered candidates -> totalDropWeight, draw uniform via MT19937, cumulative-subtract each candidate's P3 until it goes negative. Returns the selected entry, or None if candidates is empty or all weights are non-positive."""
    if not candidates:
        return None

    total_weight = sum(c.drop_weight for c in candidates)
    if total_weight <= 0:
        return None

    draw = mt.below(int(total_weight)) if total_weight == int(total_weight) else (
        mt.next_u32() / 0xFFFFFFFF * total_weight
    )

    remaining = draw
    for c in candidates:
        remaining -= c.drop_weight
        if remaining < 0:
            return c

    return candidates[-1]  # matches the binary's fallthrough-to-last


def edf6_roll_weapon_drop(
    mt: EDF6MT19937,
    table: Sequence[WeaponTableEntry],
    active_pack_id: int,
    level_min: float,
    level_max: float,
    level_tolerance: float,
) -> Optional[WeaponTableEntry]:
    """Convenience wrapper chaining the two STAGE 0 steps: filter the whole table down to eligible candidates, then weighted-pick one."""
    candidates = [
        e for e in table
        if edf6_weapon_matches_drop_filter(e, active_pack_id, level_min, level_max, level_tolerance)
    ]
    return edf6_resolve_weapon_drop(mt, candidates)


def edf6_level_scale_stat(base_value: float, p1: float, p2: float, level: float) -> float:
    """PROJECT-VERIFIED (not fully trustworthy) formula from WeaponLevelHandler @ 0x1804a1d60: stat = base_value * (p1 * (level/5)**p2 + 1), level 0.0-10.0. The source doc's own worked example doesn't match this formula, so treat with caution until re-derived against the live decompile."""
    return base_value * (p1 * (level / 5.0) ** p2 + 1.0)


# ============================== EDF4.1 ==============================
# ORGEDF41.exe, image base 0x140000000.

EDF41_DROP_KIND_STRIDE = 0x290  # bytes per kind-table entry
EDF41_KIND_WEIGHTS = None  # 4x int32 at kind_weight_table - runtime/CPK-loaded, not a static binary constant (same pattern as EDFWeaponFarming.py's per-weapon Weight column), so this stays a placeholder

# Addresses are specific to this EDF4.1 build; not portable to EDF5/EDF6 as-is.
EDF41_ADDRESSES = {
    "DropItemManager::vftable": 0x140A96098,
    "DropItemManager::ctor": 0x1401AD690,
    "DropItemManager::dtor": 0x1401ADB00,
    "DropItemManager::SpawnDrops": 0x1401AE160,  # weighted kind pick (roll vs kind_weight_table) + allocates/places the Unit for the picked kind. Called from a network-message dispatcher (FUN_1401AFA10) with the roll seed read off the wire, not the local persistent LCG state directly - drop results are server/host-authoritative and replayed identically on every client
    "DropItemManager::Unit::vftable": 0x140A96048,
    "DropItemManager::Unit::Init": 0x1401AFDF0,  # called from SpawnDrops right after the kind pick; stores kind index, copies kind-entry data into a new Havok hkpRigidBody (FUN_1406097F0) for physics/placement. NOT the per-weapon pick - that data already looks decided by this point, so the specific-weapon-within-Weapon-kind roll is still unlocated (possibly a separate loot/reward system outside DropItemManager entirely)
    "DropItemManager::Unit::PlaceDroppedItem": 0x1401AFFD0,  # vftable slot 0; places one dropped item given an already-chosen kind index (0-3); indexes the kind table via kind_index * EDF41_DROP_KIND_STRIDE. Only reached via virtual dispatch - Ghidra shows no direct incoming xrefs, confirmed instead via xrefs to the vftable itself
    "kind_weight_table": 0x140A96060,  # 4x int32 base weight, one per kind, immediately before kind_name_table
    "kind_name_table": 0x140A96070,  # Weapon.mdb, Armor.mdb, Healingsmall.mdb, Healingbig.mdb -- 8 bytes apart
}


def edf41_kind_pick(state: int, weights: Optional[Sequence[int]] = None) -> Tuple[int, int]:
    """SpawnDrops' kind roll (FUN_1401AE160), same shape as EDF6's weighted_pick. weights defaults to EDF41_KIND_WEIGHTS, which is None until sourced from CPK data - pass real weights explicitly to actually use this."""
    weights = weights if weights is not None else EDF41_KIND_WEIGHTS
    if weights is None:
        raise ValueError("EDF4.1 kind weights not yet sourced from CPK data - pass weights= explicitly")
    return weighted_pick(state, weights)


# ============================== EDF5 ==============================
# EDF5.exe. RTTI class layout (DropItemManager / DropItemManager::Unit / Singleton<DropItemManager>) confirmed
# identical to EDF6/EDF4.1 at addresses 0x1411ab100 / 0x1411ab130 / 0x1411ab170. No vtable walk done yet - nothing
# else to put here until that RE pass happens.

EDF5_ADDRESSES = {
    "DropItemManager (RTTI type descriptor)": 0x1411AB100,
    "DropItemManager::Unit (RTTI type descriptor)": 0x1411AB130,
    "Singleton<DropItemManager> (RTTI type descriptor)": 0x1411AB170,
}


if __name__ == "__main__":
    # --- EDF6 stage 1 demo: the "kind" lottery, fully verified end to end ---
    state = 0x1234_5678_9ABC_DEF0
    counts = [0, 0, 0, 0]
    for _ in range(100_000):
        state, idx = weighted_pick(state, EDF6_DROP_KIND_WEIGHTS)
        counts[idx] += 1

    total = sum(counts)
    print(f"EDF6 kind distribution over 100k draws (total weight = {sum(EDF6_DROP_KIND_WEIGHTS)}):")
    for i, c in enumerate(counts):
        expected = 100 * EDF6_DROP_KIND_WEIGHTS[i] / sum(EDF6_DROP_KIND_WEIGHTS)
        print(f"  {DROP_KIND_NAMES[i]:>13s} (w={EDF6_DROP_KIND_WEIGHTS[i]:2d}): {c:6d}  "
              f"({100 * c / total:5.2f}% observed, {expected:5.2f}% expected)")

    # --- EDF6 stage 2 demo: resolving a "Weapon" kind into a catalog index (DEFAULT_ELIGIBLE_WEAPON_INDICES is a placeholder, not real data) ---
    print(f"\nEDF6 stage-2 catalog-index distribution over 20k weapon draws "
          f"(placeholder eligible set {DEFAULT_ELIGIBLE_WEAPON_INDICES}, NOT real data):")
    idx_counts = {i: 0 for i in DEFAULT_ELIGIBLE_WEAPON_INDICES}
    for _ in range(20_000):
        state, mt = edf6_seed_mt_from_lcg(state)
        picked = edf6_resolve_drop_index(mt, DEFAULT_ELIGIBLE_WEAPON_INDICES, EDF6_WEAPON_POOL_FLAT_WEIGHT)
        idx_counts[picked] += 1
    for i, c in idx_counts.items():
        print(f"  catalog index {i}: {c:5d}  ({100 * c / 20_000:5.2f}%)")

    # --- EDF6 stage 0 demo: the real per-weapon filter + weighted pick, using a synthetic table with real P3 values (3 base weapons w=1, 1 DLC weapon w=3, all eligible - DLC should win ~3x as often as any single base weapon). ---
    synthetic_table = [
        WeaponTableEntry(0, "AssultRifle01", "app:/weapon/AssultRifle01.sgo", 0, 1.0, 0.0, 0, 0, False, 0),
        WeaponTableEntry(1, "aWeapon001", "app:/weapon/aWeapon001.sgo", 0, 1.0, 0.0, 0, 0, False, 0),
        WeaponTableEntry(2, "aWeapon002", "app:/weapon/aWeapon002.sgo", 0, 1.0, 0.0, 0, 0, False, 0),
        WeaponTableEntry(3, "MPACK_A_Weapon001", "app:/weapon/MPACK_A_Weapon001.sgo", 0, 3.0, 0.0, 0, 0, False, 1),
    ]
    win_counts = {e.name: 0 for e in synthetic_table}
    for _ in range(20_000):
        state, mt = edf6_seed_mt_from_lcg(state)
        winner = edf6_roll_weapon_drop(
            mt, synthetic_table, active_pack_id=1,
            level_min=0.0, level_max=0.0, level_tolerance=0.0,
        )
        win_counts[winner.name] += 1
    total_weight = sum(e.drop_weight for e in synthetic_table)
    print(f"\nEDF6 stage-0 real per-weapon draw over 20k rolls "
          f"(3 base weapons w=1, 1 DLC weapon w=3, total weight {total_weight:.0f}):")
    for name, c in win_counts.items():
        w = next(e.drop_weight for e in synthetic_table if e.name == name)
        expected = 100 * w / total_weight
        print(f"  {name:>20s} (w={w:.0f}): {c:6d}  "
              f"({100 * c / 20_000:5.2f}% observed, {expected:5.2f}% expected)")

    # --- EDF6 level-scaled stat demo (PROJECT-VERIFIED formula) ---
    print("\nEDF6 example level-scaled stat (base=6000, p1=0.5, p2=0.5), PROJECT-VERIFIED formula:")
    for lvl in (0.0, 5.0, 10.0):
        print(f"  level {lvl:4.1f}: {edf6_level_scale_stat(6000, 0.5, 0.5, lvl):.1f}")

    # --- EDF4.1 kind-pick demo, using placeholder weights (real weights not yet sourced from CPK data) ---
    placeholder_weights = [6, 15, 14, 3]  # NOT verified for EDF4.1 - reusing EDF6's ratio as a stand-in shape only
    print("\nEDF4.1 kind-pick demo using PLACEHOLDER weights (not real EDF4.1 data):")
    counts = [0, 0, 0, 0]
    for _ in range(20_000):
        state, idx = edf41_kind_pick(state, placeholder_weights)
        counts[idx] += 1
    for i, c in enumerate(counts):
        print(f"  {DROP_KIND_NAMES[i]:>13s}: {c:6d}  ({100 * c / 20_000:5.2f}%)")
