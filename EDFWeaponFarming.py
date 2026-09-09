"""
EDFWeaponFarming.py -- weapon "farming helper" logic for EDF6/EDF5/EDF4.1: given a mission + difficulty (or a target weapon), compute which weapon levels are eligible to drop there. Pure logic, no UI/GUI dependency.

Formula verified via Ghidra RE: WeaponDropLevelBand_Compute (0x1800d7c40) and WeaponDropLevelBand_ReadDifficultyCurve (0x1800e26c0) supply the level_min/level_max that FUN_1800d95c0/FUN_1800d81e0 (EDF6DropLotterry.py's "STAGE 0") check against. This is a separate curve from the x25-scaled WeaponLevelLimitInterpolator shown in the online Room Setting UI (display-only) -- this one is what the drop lottery actually checks.

The formula is verified; per-mode/per-difficulty curve endpoints (min_endpoint/max_endpoint/band_width) are wiki-sourced + empirically cross-checked rather than byte-verified against a live config.sgo dump. A still-null curve cell degrades gracefully to None so the UI shows an honest "curve data not available" state instead of a fabricated range.

All per-weapon and per-curve data lives in WeaponNamesLang.json, under each game's top-level key: "weapon_meta" ({"<id>": {name, sgo, category, drop_weight, availability, tag_count, item_class, pack, level_req}}, P0-P8-equivalent fields from WEAPONTABLE.json), per-mode curve sub-blocks ({<difficulty>: {min_endpoint, max_endpoint, band_width}}), and "weapon_meta_placeholder_fields" (which fields, if any, are placeholder-staged rather than really extracted). EDF5/EDF4.1's weapon_meta is built from each game's own raw WEAPONTABLE.json; item_class (both) and tag_count/pack (EDF4.1 only) are placeholder 0 since no corresponding field exists in those games' raw tables.

Field meanings, verified against the community wiki's WEAPON TABLE section: P2 category matches category_names 1:1; P3 drop_weight is "Drop Weighting as %" (a per-weapon multiplier on its odds within its own level band - most weapons are 1=100%, a handful of top-tier/starter variants run higher or lower, e.g. 1.29=129%, 0.6=60%, 0.5=50%); P4 level_req is "Weapon Level *25" (matches FARMING_DISPLAY_SCALE); P5 availability is 0=COLLECT/1=STARTER ITEM/3=SINGLE DLC; P7 item_class is the plain raw 0/1 field (a prior pass incorrectly forced a 3rd value here, since reverted -- SINGLE DLC classification lives entirely in P5==3).

2026-09-08 cross-check (EDF4.1, both Ghidra RE of a real decoded _WeaponTable.sgo and independent
verification against invadersfromplanet.space's own drop tables): availability==3 (SINGLE DLC)
weapons are NEVER in the natural drop pool at any difficulty/mode - the reference site shows a
literal "DLC" tag instead of a weight% for every one of them, in every drop-view mode (ON/DLC1/
DLC2 alike), matching weapon_matches_band()'s existing availability_ok gate below exactly. Their
drop_weight (P3) is unremarkable (always 1=100% in the sample checked) - it's availability, not
drop_weight, that marks them DLC-only; drop_weight only matters for weapons that already passed
the availability gate. Also confirmed: EDF4.1's 2 mission-pack DLCs add zero exclusive weapons
(their own PACKAGE.sgo points at the same base _WeaponTable.sgo, and pack stays 0 for every EDF4.1
weapon here) - the "mission packs drop good guns" folklore is real in effect but not in mechanism:
MP1/MP2 unlock access to higher item-level missions, which is where the naturally rarest (lowest
drop_weight, highest level_req) top-tier weapons already live in the shared table, DLC or not.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

DIFFICULTY_ORDER = ["Easy", "Normal", "Hard", "Hardest", "Inferno"]

# Verified constant (DAT_181765a04 in EDF.dll's .rdata = 0.05f). Used by FUN_1800d95c0 as both the flat tolerance floor and the multiplier against the curve's raw span: tolerance = max(0.05, (max_endpoint - min_endpoint) * 0.05).
DROP_TOLERANCE_FRACTION = 0.05
DROP_TOLERANCE_FLOOR = 0.05


def _default_path(filename: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, filename)


@dataclass
class DropWeaponEntry:
    id: int
    name: str                # P0 -- real display name (e.g. "Broken PA-11"), not the raw internal codename; codename still recoverable via "sgo"'s basename.
    sgo: str                  # P1
    category: int             # P2 -- numeric category id; see load_category_names() for the internal enum name, not a player-facing string.
    drop_weight: float        # P3 -- "Drop Weighting as %", 1 = 100% (default for nearly every weapon, DLC entries included); a small set of top-tier/starter variants run higher (e.g. 1.29) or lower (e.g. 0.5, 0.6) - NOT a DLC indicator, see availability (P5) for that.
    level_req: float          # P4 -- this weapon's position on the raw progress curve, exact precision. Wiki-confirmed "Weapon Level *25" (player-facing level = this * FARMING_DISPLAY_SCALE).
    availability: int         # P5 -- enum: 0 = COLLECT, 1 = STARTER ITEM, 3 = SINGLE DLC (no documented value 2)
    tag_count: int            # P6 count (0..8), not a 0/1 flag. Gates whether an availability==1 starter item is droppable (tag_count != 0), and whether the +-5% tolerance band applies.
    item_class: int            # P7 -- raw value only, 0 or 1. SINGLE DLC classification lives in availability==3, not here.
    pack: int                  # P8 -- 0 base game, 1 DLC pack 1, 2 DLC pack 2


def load_names_lang_doc(path: Optional[str] = None) -> dict:
    """Loads the full WeaponNamesLang.json document: per-language display names, per-weapon P0-P8-equivalent metadata ("weapon_meta"), category id -> internal enum name ("category_names"), and the drop-level-band curves, all nested under each game's top-level key."""
    path = path or _default_path('WeaponNamesLang.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_names_lang_doc(doc: dict, path: Optional[str] = None) -> None:
    path = path or _default_path('WeaponNamesLang.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def load_category_names(path: Optional[str] = None, game_key: str = 'EDF6') -> Dict[str, str]:
    """Loads WeaponNamesLang.json's "<game_key>"->"category_names": category id (P2, as a string key) -> internal enum name (e.g. "0" -> "Weapon_AssaultRifle"). Not player-facing display strings -- strip "Weapon_" and split on "_" for a nicer label. `game_key` defaults to 'EDF6'; 'EDF5' has its own independently-populated block."""
    doc = load_names_lang_doc(path)
    return (doc.get(game_key) or {}).get('category_names') or {}


def load_weapon_drop_data(path: Optional[str] = None, game_key: str = 'EDF6') -> List[DropWeaponEntry]:
    """Loads per-weapon drop data from WeaponNamesLang.json's "<game_key>" block's "weapon_meta" (id-keyed, level_req/P4 nested directly). Falls back to a legacy top-level "level float" dict for backward compat. id here == catalog_index == the same weapon ID space used elsewhere in EDFSaveEditor. `game_key` picks 'EDF6' (default), 'EDF5', or 'EDF4.1' - EDF4.1's own 827-entry weapon_meta table is real (Ghidra-confirmed, 2026-09-08: EDF41.exe's raw _WeaponTable.sgo decodes to the exact same [name,sgo,category,drop_weight,level_req,availability] shape as EDF6/EDF5's, just fewer trailing fields) and EDFSaveEditorMain.py already loads it this way; an earlier version of this docstring incorrectly called EDF4.1 unsupported."""
    doc = load_names_lang_doc(path)
    edf6 = doc.get(game_key) or {}
    meta = edf6.get('weapon_meta') or {}
    legacy_level_floats = edf6.get('level float') or {}
    raw = [dict(m, id=int(wid_str),
                level_req=m.get('level_req', legacy_level_floats.get(wid_str, 0.0)))
           for wid_str, m in meta.items()]
    raw.sort(key=lambda r: r['id'])
    return [
        DropWeaponEntry(
            id=row['id'], name=row.get('name', ''), sgo=row.get('sgo', ''),
            category=row.get('category', 0), drop_weight=row.get('drop_weight', 1.0),
            level_req=row.get('level_req', 0.0),
            availability=row.get('availability', 0),
            tag_count=row.get('tag_count', 0), item_class=row.get('item_class', 0),
            pack=row.get('pack', 0),
        )
        for row in raw
    ]


# Every farming panel mode this app currently supports, kept here so load_drop_curves can pull all sub-blocks out of WeaponNamesLang.json without the caller enumerating them.
FARMING_MODES = ["EDF6", "EDF6 DLC1", "EDF6 DLC2"]

# EDF5's own curve sub-block keys inside doc['EDF5'] - different naming than FARMING_MODES. Wiki-sourced, cross-checked against EDF6's curves. EDF5ONDLC2's "Normal" cell has a known min>max anomaly, left as-is since curve_data_available()/compute_level_band() degrade gracefully on bad data.
EDF5_FARMING_SUBMODES = ["EDF5", "EDF5ON", "EDF5DLC1", "EDF5ONDLC1", "EDF5DLC2", "EDF5ONDLC2"]

# EDF4.1's own curve sub-block keys - 5 submodes, no plain "EDF4.1ON" key since EDF4.1's online mission tables are separate files per DLC pack rather than a shared mode.
EDF41_FARMING_SUBMODES = ["EDF4.1", "EDF4.1DLC1", "EDF4.1ONDLC1", "EDF4.1DLC2", "EDF4.1ONDLC2"]

# EDF4.1 weapon_meta: `pack` staying 0 across all entries isn't a data gap - EDF4.1's real DLC weapons are already flagged via availability==3, and EDF4.1 has no mission-pack-exclusive weapons like EDF6 does.


def load_drop_curves(path: Optional[str] = None, game_key: str = 'EDF6', modes: Optional[List[str]] = None) -> dict:
    """Loads the drop-level-band curves from WeaponNamesLang.json's "<game_key>" block, one sub-block per mode. `modes` defaults to FARMING_MODES; pass game_key='EDF5' and modes=EDF5_FARMING_SUBMODES to read EDF5's curve data instead."""
    doc = load_names_lang_doc(path)
    block = doc.get(game_key) or {}
    return {mode: (block.get(mode) or {}) for mode in (modes or FARMING_MODES)}


def save_drop_curve_cell(mode: str, difficulty: str, values: dict, path: Optional[str] = None,
                          load_path: Optional[str] = None, game_key: str = 'EDF6') -> None:
    """Persists one mode/difficulty curve cell into WeaponNamesLang.json's "<game_key>"-><mode>-><difficulty> slot via a read-modify-write of the whole document, preserving every other key. `load_path` lets the read side differ from the write side, needed in a packaged build's first curve edit (no exe-adjacent file yet) so reading the bundled copy doesn't overwrite the exe-adjacent file with just this one cell. `game_key` picks which top-level game block the edit lands in."""
    doc = load_names_lang_doc(load_path if load_path is not None else path)
    edf6 = doc.setdefault(game_key, {})
    edf6.setdefault(mode, {})[difficulty] = values
    save_names_lang_doc(doc, path)


def mission_progress_fraction(mission_index: int, mission_count: int) -> float:
    """VERIFIED, MissionProgressFraction @ 0x1800d7b60: 0.0 if the mission list has fewer
    than 2 entries, else mission_index / (mission_count - 1)."""
    if mission_count < 2:
        return 0.0
    return mission_index / float(mission_count - 1)


def compute_level_band(curve: dict, progress: float) -> Optional[Tuple[float, float, float]]:
    """VERIFIED formula shape (WeaponDropLevelBand_Compute @ 0x1800d7c40). Returns
    (level_min, level_max, tolerance), or None if this curve's endpoints haven't been filled
    in yet (still null in WeaponNamesLang.json's "EDF6"-><mode>-><difficulty> cell)."""
    lo = curve.get('min_endpoint')
    hi = curve.get('max_endpoint')
    band = curve.get('band_width')
    if lo is None or hi is None or band is None:
        return None
    t = max(0.0, min(1.0, progress))
    level_max = lo + (hi - lo) * t
    level_min = max(0.0, level_max - band)
    tolerance = (hi - lo) * DROP_TOLERANCE_FRACTION
    if tolerance < DROP_TOLERANCE_FLOOR:
        tolerance = DROP_TOLERANCE_FLOOR
    return level_min, level_max, tolerance


def weapon_matches_band(weapon: DropWeaponEntry, active_pack_id: int,
                         level_min: float, level_max: float, tolerance: float) -> bool:
    """FUN_1800d81e0's per-weapon eligibility gate: availability + DLC-pack-owned + level-band, in that order. Mirrors EDF6DropLotterry.py's edf6_weapon_matches_drop_filter; the binary's anti-duplicate spatial hash check isn't modeled here since it doesn't affect odds/eligibility."""
    availability_ok = (weapon.availability == 0) or (
        weapon.availability == 1 and weapon.tag_count != 0
    )
    if not availability_ok:
        return False
    pack_ok = (weapon.pack == 0) or (weapon.pack == active_pack_id)
    if not pack_ok:
        return False
    tol = tolerance if weapon.tag_count != 0 else 0.0
    return level_min <= weapon.level_req <= level_max + tol


def weapons_droppable_at_mission(weapons: List[DropWeaponEntry], curve: dict,
                                  mission_index: int, mission_count: int,
                                  active_pack_id: int) -> Optional[List[DropWeaponEntry]]:
    """Direction 1: mission -> matching weapons. None if the curve's endpoints aren't filled
    in yet (see WeaponNamesLang.json's per-mode curve blocks)."""
    progress = mission_progress_fraction(mission_index, mission_count)
    band = compute_level_band(curve, progress)
    if band is None:
        return None
    level_min, level_max, tolerance = band
    return [
        w for w in weapons
        if weapon_matches_band(w, active_pack_id, level_min, level_max, tolerance)
    ]


def earliest_mission_for_weapon(weapon: DropWeaponEntry, curve: dict, mission_count: int,
                                 active_pack_id: int) -> Optional[int]:
    """Direction 2: target weapon -> earliest 0-based mission index at which it becomes droppable. Returns None if the curve isn't filled in yet, or if the weapon is never eligible across the whole mission list."""
    if curve.get('min_endpoint') is None:
        return None
    for mission_index in range(mission_count):
        progress = mission_progress_fraction(mission_index, mission_count)
        band = compute_level_band(curve, progress)
        if band is None:
            return None
        level_min, level_max, tolerance = band
        if weapon_matches_band(weapon, active_pack_id, level_min, level_max, tolerance):
            return mission_index
    return None


def curve_data_available(curve: dict) -> bool:
    """True once a curve's endpoints have real (non-null) values -- gate the UI on this
    before claiming to show a level range."""
    return curve is not None and curve.get('min_endpoint') is not None \
        and curve.get('max_endpoint') is not None and curve.get('band_width') is not None
