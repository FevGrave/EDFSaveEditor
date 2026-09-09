# EDFSaveEditorLogic.py
import struct
import os
import json
import glob
import re  # used by load_all_mission_tables' game-family scoping (see its docstring)
import sys  # added for frozen exe path handling
import zlib  # EDF4.1's TROPHY.DAT checksum uses standard CRC-32 (zlib.crc32), not crc32c - see save_save_data()'s trophy block
import shutil  # used by _backup_before_overwrite() for the pre-save safety-net copy
import datetime  # timestamps the pre-save backup filename
from tkinter import filedialog
from EDFSaveEditorSave_Handler import load_save, save_save, load_save_edf41, save_save_edf41, edf41_decrypt, edf41_encrypt, generate_dat_key_iv_variants, try_decrypt_variants, aes_ctr_decrypt, aes_ctr_encrypt, crc32c, generate_key_iv

# Helper functions for locating bundled resources when frozen (PyInstaller)
def _resource_base():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS  # type: ignore
    return os.path.abspath(os.path.dirname(__file__))

def resource_path(name: str) -> str:
    return os.path.join(_resource_base(), name)

def load_json_safe(path: str, fallback):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback

PLAYER_CLASS_MAP = {0: "Ranger", 1: "Wingdiver", 2: "Air Raider", 3: "Fencer"}

# TROPHY.DAT's lifetime "Total Armor Points Acquired" field (EDF6 only), kept in sync with the sum of per-class armor.
TOTAL_ARMOR_POINTS_OFFSET = 0x100  # TROPHY.DAT, EDF6 only

# EDF6's per-class armor growth-rate multipliers (named, so the "Modded Growth Rate" UI field
# added 2026-09-07 has a table to pull its vanilla pre-fill from, same pattern as EDF5/EDF4.1 below).
EDF6_ARMOR_GROWTH_RATES = {
    "Ranger Armor": 0.5600000023841858,
    "Wingdiver Armor": 0.3499999940395355,
    "Air Raider Armor": 0.5600000023841858,
    "Fencer Armor": 0.5950000286102295,
}

# FevGrave 2026-09-07: playing a modded game (EDF 6.9) whose starting armor AND per-class growth
# rate differ from vanilla makes "Modded Armor Gain" wrong for that game, since it was always using
# the vanilla constants regardless of `mg`. Every calc lambda below now takes optional
# `modded_start`/`modded_rate` arguments, used ONLY in "Modded Armor Gain" - "Base Game Gain" always
# stays tied to the real vanilla constants on purpose, since it's meant to answer "what would this
# be in unmodded EDF6". Passing None (the default, e.g. any existing caller that hasn't been
# updated) keeps the old behavior exactly, so this is backward compatible with EDF5/EDF4.1's calc
# reuse below.
ARMOR_STRUCTURE = [
    (0x134, 0x4, "<I", "Ranger Armor", lambda v, mg, modded_start=None, modded_rate=None: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * EDF6_ARMOR_GROWTH_RATES["Ranger Armor"] + 200, 2),
        "Modded Armor Gain": round(v * (mg * (EDF6_ARMOR_GROWTH_RATES["Ranger Armor"] if modded_rate is None else modded_rate)) + (200 if modded_start is None else modded_start), 2),
    }),
    (0x138, 0x4, "<I", "Wingdiver Armor", lambda v, mg, modded_start=None, modded_rate=None: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * EDF6_ARMOR_GROWTH_RATES["Wingdiver Armor"] + 150, 2),
        "Modded Armor Gain": round(v * (mg * (EDF6_ARMOR_GROWTH_RATES["Wingdiver Armor"] if modded_rate is None else modded_rate)) + (150 if modded_start is None else modded_start), 2),
    }),
    (0x13C, 0x4, "<I", "Air Raider Armor", lambda v, mg, modded_start=None, modded_rate=None: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * EDF6_ARMOR_GROWTH_RATES["Air Raider Armor"] + 200, 2),
        "Modded Armor Gain": round(v * (mg * (EDF6_ARMOR_GROWTH_RATES["Air Raider Armor"] if modded_rate is None else modded_rate)) + (200 if modded_start is None else modded_start), 2),
    }),
    (0x140, 0x4, "<I", "Fencer Armor", lambda v, mg, modded_start=None, modded_rate=None: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * EDF6_ARMOR_GROWTH_RATES["Fencer Armor"] + 250, 2),
        "Modded Armor Gain": round(v * (mg * (EDF6_ARMOR_GROWTH_RATES["Fencer Armor"] if modded_rate is None else modded_rate)) + (250 if modded_start is None else modded_start), 2),
    }),
]

# "Current" (in-mission) armor value per class, separate from the "max" ARMOR_STRUCTURE offsets.
ARMOR_CURRENT_OFFSETS = [0x14, 0x18, 0x1C, 0x20]

# EDF5's armor region, same layout as EDF6 shifted +0xC, with its own per-class growth rates.
EDF5_ARMOR_GROWTH_RATES = {
    "Ranger Armor": 0.6399999856948853,
    "Wingdiver Armor": 0.4000000059604645,
    "Air Raider Armor": 0.6399999856948853,
    "Fencer Armor": 0.800000011920929,
}

def _edf5_armor_calc(label, starting_total):
    rate = EDF5_ARMOR_GROWTH_RATES[label]
    return lambda v, mg, modded_start=None, modded_rate=None: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * rate + starting_total, 2),
        "Modded Armor Gain": round(v * (mg * (rate if modded_rate is None else modded_rate)) + (starting_total if modded_start is None else modded_start), 2),
    }

EDF5_ARMOR_STRUCTURE = [
    (offset + 0xC, size, fmt, label, _edf5_armor_calc(label, calc(0, 1)["Base Game Gain"]))
    for (offset, size, fmt, label, calc) in ARMOR_STRUCTURE
]
EDF5_ARMOR_CURRENT_OFFSETS = [offset + 0xC for offset in ARMOR_CURRENT_OFFSETS]

# EDF5's TROPHY.DAT armor total, stored per-class as a derived float rather than one summed int.
EDF5_TROPHY_ARMOR_GAIN_OFFSETS = {
    "Ranger Armor": 0x1B8,
    "Wingdiver Armor": 0x1E8,
    "Air Raider Armor": 0xE8,
    "Fencer Armor": 0x130,
}

# EDF4.1's per-class armor growth-rate multipliers.
EDF41_ARMOR_GROWTH_RATES = {
    "Ranger Armor": 4.2399999499320984,
    "Wingdiver Armor": 2.1199999749660492,
    "Air Raider Armor": 4.2399999499320984,
    "Fencer Armor": 5.299999713897705,
}

# EDF4.1 armor lives only in TROPHY.DAT (not MAIN.GST) - the single source of truth for its Armor tab.
EDF41_TROPHY_ARMOR_OFFSETS = {
    "Ranger Armor": 0x19C,
    "Wingdiver Armor": 0x1D4,
    "Air Raider Armor": 0xE4,
    "Fencer Armor": 0x128,
}

# Starting armor-point totals per class, used to invert a display value back to a pickup count.
EDF41_ARMOR_STARTING_TOTALS = {
    "Ranger Armor": 200,
    "Wingdiver Armor": 150,
    "Air Raider Armor": 200,
    "Fencer Armor": 250,
}

def _edf41_armor_calc(label):
    """Builds the EDF4.1 armor-preview calc for one class (Total/Base/Modded Gain)."""
    start = EDF41_ARMOR_STARTING_TOTALS[label]
    rate = EDF41_ARMOR_GROWTH_RATES[label]
    def calc(v, mg, modded_start=None, modded_rate=None):
        real_start = start if modded_start is None else modded_start
        real_rate = rate if modded_rate is None else modded_rate
        # pseudo_count divides by the true vanilla rate against real_start (unchanged from before
        # modded_rate existed) - it's recovering "how many pickups got you to v" from the save's
        # real accumulation. Only the final scale-up below applies real_rate.
        pseudo_count = (v - real_start) / rate if rate else 0.0
        return {
            "Total You Really Have": v,
            "Base Game Gain": round(v, 2),
            "Modded Armor Gain": round(pseudo_count * (mg * real_rate) + real_start, 2),
        }
    return calc

EDF41_ARMOR_CALC = {label: _edf41_armor_calc(label) for label in EDF41_ARMOR_STARTING_TOTALS}

def _game_is_edf5(game) -> bool:
    """True for any EDF5 game/DLC/Online-Offline variant."""
    return str(game or '').upper().startswith('EDF5')

def _game_is_edf6(game) -> bool:
    """True for any EDF6 game/DLC/Online-Offline variant."""
    return str(game or '').upper().startswith('EDF6')

def _game_is_edf41(game) -> bool:
    """True for any EDF4.1 game/DLC/Online-Offline variant."""
    return str(game or '').upper().startswith('EDF4')

def get_vanilla_armor_rate(game, label):
    """Per-game vanilla growth-rate lookup for `label` (e.g. 'Ranger Armor') - unlike starting AP
    (200/150/200/250, shared across all 3 games), growth rate differs drastically per game (EDF6
    ~0.56, EDF5 ~0.64-0.8, EDF4.1 ~2.1-5.3), so the "Modded Growth Rate" UI field must be re-filled
    with the right table's value whenever the selected game changes."""
    if _game_is_edf5(game):
        return EDF5_ARMOR_GROWTH_RATES.get(label, 1.0)
    if _game_is_edf41(game):
        return EDF41_ARMOR_GROWTH_RATES.get(label, 1.0)
    return EDF6_ARMOR_GROWTH_RATES.get(label, 1.0)

def get_armor_structure(game):
    """Return the right ARMOR_STRUCTURE table for app.current_game (empty for EDF4.1 - its armor lives in TROPHY.DAT, see EDF41_TROPHY_ARMOR_OFFSETS)."""
    return EDF5_ARMOR_STRUCTURE if _game_is_edf5(game) else ([] if _game_is_edf41(game) else ARMOR_STRUCTURE)

def get_armor_current_offsets(game):
    """Mirrors get_armor_structure() above for the "current" armor offsets."""
    return EDF5_ARMOR_CURRENT_OFFSETS if _game_is_edf5(game) else ([] if _game_is_edf41(game) else ARMOR_CURRENT_OFFSETS)

# Sentinel raw value for an empty loadout slot, shown in the UI as -1.
LOADOUT_UNUSED_SLOT_RAW = 0xFFFFFFFF
LOADOUT_STRUCTURE = [
    (0x44, 0x4, "<I", "Current Ranger Primary Weapon ID"),
    (0x48, 0x4, "<I", "Current Ranger Secondary Weapon ID"),
    (0x4C, 0x4, "<I", "Current Ranger Backpack Equipment ID"),
    (0x50, 0x4, "<I", "Current Ranger Support Equipment ID"),
    (0x54, 0x4, "<I", "Unused Ranger Slot"),
    (0x58, 0x4, "<I", "Unused Ranger Slot"),
    (0x5C, 0x4, "<I", "Current Wingdiver Primary Weapon ID"),
    (0x60, 0x4, "<I", "Current Wingdiver Secondary Weapon ID"),
    (0x64, 0x4, "<I", "Current Wingdiver Independently Operated Equipment ID"),
    (0x68, 0x4, "<I", "Current Wingdiver Plasma Core ID"),
    (0x6C, 0x4, "<I", "Unused Wingdiver Slot"),
    (0x70, 0x4, "<I", "Unused Wingdiver Slot"),
    (0x74, 0x4, "<I", "Current Air Raider Primary Weapon ID"),
    (0x78, 0x4, "<I", "Current Air Raider Secondary Weapon ID"),
    (0x7C, 0x4, "<I", "Current Air Raider Tertiary Weapon ID"),
    (0x80, 0x4, "<I", "Current Air Raider Backpack Equipment ID"),
    (0x84, 0x4, "<I", "Current Air Raider Vehicle Equipment ID"),
    (0x88, 0x4, "<I", "Unused Air Raider Slot"),
    (0x8C, 0x4, "<I", "Current Fencer L. Hand Primary Weapon ID"),
    (0x90, 0x4, "<I", "Current Fencer R. Hand Secondary Weapon ID"),
    (0x94, 0x4, "<I", "Current Fencer L. Hand Tertiary Weapon ID"),
    (0x98, 0x4, "<I", "Current Fencer R. Hand Quaternary Weapon ID"),
    (0x9C, 0x4, "<I", "Current Fencer Reinforced Parts Primary ID"),
    (0xA0, 0x4, "<I", "Current Fencer Reinforced Parts Secondary ID"),
]

LOADOUT_GROUPS = {
    "Ranger": LOADOUT_STRUCTURE[0:6],
    "Wingdiver": LOADOUT_STRUCTURE[6:12],
    "Air Raider": LOADOUT_STRUCTURE[12:18],
    "Fencer": LOADOUT_STRUCTURE[18:24],
}

# EDF5 loadout offsets: same +0xC shift as armor, but slot labels differ (EDF6 added extra equipment categories); confirmed via real screenshots + isolated diffs.
EDF5_LOADOUT_STRUCTURE = [
    (0x50, 0x4, "<I", "Current Ranger Primary Weapon ID"),
    (0x54, 0x4, "<I", "Current Ranger Secondary Weapon ID"),
    (0x58, 0x4, "<I", "Current Ranger Support Equipment ID"),
    (0x5C, 0x4, "<I", "Unused Ranger Slot"),
    (0x60, 0x4, "<I", "Unused Ranger Slot"),
    (0x64, 0x4, "<I", "Unused Ranger Slot"),
    (0x68, 0x4, "<I", "Current Wingdiver Primary Weapon ID"),
    (0x6C, 0x4, "<I", "Current Wingdiver Secondary Weapon ID"),
    (0x70, 0x4, "<I", "Current Wingdiver Plasma Core ID"),
    (0x74, 0x4, "<I", "Unused Wingdiver Slot"),
    (0x78, 0x4, "<I", "Unused Wingdiver Slot"),
    (0x7C, 0x4, "<I", "Unused Wingdiver Slot"),
    (0x80, 0x4, "<I", "Current Air Raider Primary Weapon ID"),
    (0x84, 0x4, "<I", "Current Air Raider Secondary Weapon ID"),
    (0x88, 0x4, "<I", "Current Air Raider Tertiary Weapon ID"),
    (0x8C, 0x4, "<I", "Current Air Raider Vehicle Equipment ID"),
    (0x90, 0x4, "<I", "Unused Air Raider Slot"),
    (0x94, 0x4, "<I", "Unused Air Raider Slot"),
    (0x98, 0x4, "<I", "Current Fencer L. Hand Primary Weapon ID"),
    (0x9C, 0x4, "<I", "Current Fencer R. Hand Secondary Weapon ID"),
    (0xA0, 0x4, "<I", "Current Fencer L. Hand Tertiary Weapon ID"),
    (0xA4, 0x4, "<I", "Current Fencer R. Hand Quaternary Weapon ID"),
    (0xA8, 0x4, "<I", "Current Fencer Reinforced Parts Primary ID"),
    (0xAC, 0x4, "<I", "Current Fencer Reinforced Parts Secondary ID"),
]

EDF5_LOADOUT_GROUPS = {
    "Ranger": EDF5_LOADOUT_STRUCTURE[0:6],
    "Wingdiver": EDF5_LOADOUT_STRUCTURE[6:12],
    "Air Raider": EDF5_LOADOUT_STRUCTURE[12:18],
    "Fencer": EDF5_LOADOUT_STRUCTURE[18:24],
}

# EDF4.1 loadout offsets - only 4 slots per class (not 6 like EDF5/6), own labels.
EDF41_LOADOUT_STRUCTURE = [
    (0x44, 0x4, "<I", "Current Ranger Weapon 1 ID"),
    (0x48, 0x4, "<I", "Current Ranger Weapon 2 ID"),
    (0x4C, 0x4, "<I", "Unused Ranger Slot"),
    (0x50, 0x4, "<I", "Unused Ranger Slot"),
    (0x54, 0x4, "<I", "Current Wingdiver Weapon 1 ID"),
    (0x58, 0x4, "<I", "Current Wingdiver Weapon 2 ID"),
    (0x5C, 0x4, "<I", "Unused Wingdiver Slot"),
    (0x60, 0x4, "<I", "Unused Wingdiver Slot"),
    (0x64, 0x4, "<I", "Current Air Raider Weapon 1 ID"),
    (0x68, 0x4, "<I", "Current Air Raider Weapon 2 ID"),
    (0x6C, 0x4, "<I", "Current Air Raider Vehicle ID"),
    (0x70, 0x4, "<I", "Unused Air Raider Slot"),
    (0x74, 0x4, "<I", "Current Fencer Weapon 1 - L. Hand ID"),
    (0x78, 0x4, "<I", "Current Fencer Weapon 1 - R. Hand ID"),
    (0x7C, 0x4, "<I", "Current Fencer Weapon 2 - L. Hand ID"),
    (0x80, 0x4, "<I", "Current Fencer Weapon 2 - R. Hand ID"),
]

EDF41_LOADOUT_GROUPS = {
    "Ranger": EDF41_LOADOUT_STRUCTURE[0:4],
    "Wingdiver": EDF41_LOADOUT_STRUCTURE[4:8],
    "Air Raider": EDF41_LOADOUT_STRUCTURE[8:12],
    "Fencer": EDF41_LOADOUT_STRUCTURE[12:16],
}

def get_loadout_structure(game):
    """Return the right LOADOUT_STRUCTURE table for app.current_game."""
    if _game_is_edf5(game):
        return EDF5_LOADOUT_STRUCTURE
    if _game_is_edf41(game):
        return EDF41_LOADOUT_STRUCTURE
    return LOADOUT_STRUCTURE

def get_loadout_groups(game):
    """Return the right {class_name: slots} dict for `game`, mirroring get_loadout_structure()."""
    if _game_is_edf5(game):
        return EDF5_LOADOUT_GROUPS
    if _game_is_edf41(game):
        return EDF41_LOADOUT_GROUPS
    return LOADOUT_GROUPS

# Weapon table base offset in MAIN.GST (EDF6: 0x7CFC, EDF5: 0x7D08). EDF4.1 uses its own ownership/unlock flag array instead, below.
EDF41_WEAPON_TABLE_BASE = 0x2078
EDF41_WEAPON_TABLE_STRIDE = 4

# EDF4.1 DLC weapon indices and class/category ranges (Ranger 0-6, Wing Diver 10-17, Fencer 20-25, Air Raider 30-39).
EDF41_DLC_WEAPON_INDICES = {
    31: 'aShotgun_StingShot',        # Sting Shot (Ranger Weapons DLC)
    101: 'GenocideGun',               # Genocide Gun (level 100 - bonus/endgame, not from a Steam DLC pack by that name)
    136: 'aNapalmLauncher01',         # Volatile Napalm (Ranger Weapons DLC)
    160: 'aDecoyShooter01',           # Pure Decoy Launcher [Karia]  } Ranger Weapons: Pure Decoy
    161: 'aDecoyShooter02',           # Pure Decoy Launcher [Moegi]  } Launcher 5 Pack A
    162: 'aDecoyShooter03',           # Pure Decoy Launcher [Ouka]   }
    163: 'aDecoyShooter04',           # Pure Decoy Launcher [Rinrin] }
    164: 'aDecoyShooter05',           # Pure Decoy Launcher [Chiri]  }
    200: 'pSparkLancer',              # Spark Lancer (Wing Diver Weapons DLC)
    230: 'pReflectLaser01',           # Reflectron Laser (Wing Diver Weapons DLC)
    364: 'pClusterHoming01',          # Gleipnir (Wing Diver Weapons DLC)
    377: 'pGenocideCluster',          # Armageddon Cluster (level 100 - bonus/endgame, same caveat as Genocide Gun)
    506: 'hHellStorm01',              # Ifrit (Fencer Weapons DLC)
    520: 'hClusterMissile01',         # Blood Storm (Fencer Weapons DLC)
    699: 'eDecoyShooter01',           # Pure Decoy Launcher [Anju]   } Air Raider Weapons: Pure Decoy
    700: 'eDecoyShooter02',           # Pure Decoy Launcher [Miyabi] } Launcher 5 Pack B
    701: 'eDecoyShooter03',           # Pure Decoy Launcher [Noko]   }
    702: 'eDecoyShooter04',           # Pure Decoy Launcher [Mitsuki]}
    703: 'eDecoyShooter05',           # Pure Decoy Launcher [Seira]  }
    730: 'eVehicle_Begaruta01',       # BM03 Vegalta Gold (Air Raider vehicle skin DLC)
    733: 'GroundRobo01_Gold',         # Depth Crawler Gold Coat (Air Raider vehicle skin DLC)
    738: 'eVehicle_Tank_BulletGirls', # Gigantus Tank, Bullet Girls Marking
    739: 'eVehicle_Tank_DcZero',      # Gigantus DCC-Zero Marking
    740: 'eVehicle_Tank_Dc55',        # Gigantus DCC-Gogo. Marking
    741: 'eVehicle_Tank_EDF2pv2',     # Gigantus Tank, EDF IFPS Markings
    742: 'eVehicle_Tank_natsuiro',    # Gigantus Tank, Natsuiro HS Markings
}
def get_weapon_table_base(game) -> int:
    """Return the MAIN.GST byte offset where the 2048x12-byte weapon table starts, for app.current_game."""
    return 0x7D08 if _game_is_edf5(game) else 0x7CFC

# --- KILL FIELDS for Achievements Tab ---
# SUPERSEDED 2026-09-08: the table below (byte-scan/hexbm/sentinel-flavored guessed names, wired
# 2026-09-07) is replaced with the fuller, Achievement.sgo-derived table further down, using the
# exact same reconciliation method that worked for EDF4.1 (see SAVE_FORMAT_NOTES.md). Cross-checked
# 17 of this old table's entries against the real Achievement.sgo names by semantic match
# ('missions_as_air_raider'~'AirRaiderPlayCount', 'archeluses_kills'~'Monster504KillCount', etc.)
# and EVERY ONE agreed on an identical base offset of 0xDC with ZERO gaps needed - cleaner than
# EDF4.1's reconciliation (which needed a 6-slot fudge). All 53 of the old table's entries fall
# within the new 91-slot range with no contradictions; several guessed names get real corrections
# (e.g. the one entry hexbm's own bookmark had flagged uncertain, 'mobile_base_mothership_kills'
# at 0x15C, turns out to be 'FortressKillCount' - a different, more sensible identity entirely;
# 'android_kills'-family guesses map cleanly onto EDF6's real 'BerserkerA/B/C/D' enemy names).
# EDF6's Achievements panel (the 0x14/0x34 byte-flag Conquest/Master/Rescue system) is NOT touched
# by this - that system is already independently confirmed against a real save and stays as-is;
# only this Kill Statistics counter table is being replaced/expanded (52 named fields -> 91).
# Source: EDF6's own APP:/ETC/Achievement.sgo (decoded JSON supplied by FevGrave from their own
# game install), same OGS/SGO format already used for EDF4.1's Achievement.sgo/_WeaponTable.sgo.
KILL_FIELDS = [
    (0xDC, 4, 'AirRaiderArmor', 'float'),
    (0xE0, 4, 'AirRaiderEasyClearRatio', 'int'),
    (0xE4, 4, 'AirRaiderHardClearRatio', 'int'),
    (0xE8, 4, 'AirRaiderHardestClearRatio', 'int'),
    (0xEC, 4, 'AirRaiderInfernoClearRatio', 'int'),
    (0xF0, 4, 'AirRaiderNormalClearRatio', 'int'),
    (0xF4, 4, 'AirRaiderPlayCount', 'int'),
    (0xF8, 4, 'AllClearRatio', 'int'),
    (0xFC, 4, 'AntHillKillCount', 'int'),
    (0x100, 4, 'ArmorCount', 'int'),
    (0x104, 4, 'BerserkerAKillCount', 'int'),
    (0x108, 4, 'BerserkerBKillCount', 'int'),
    (0x10C, 4, 'BerserkerCKillCount', 'int'),
    (0x110, 4, 'BerserkerDKillCount', 'int'),
    (0x114, 4, 'BerserkerLargeKillCount', 'int'),
    (0x118, 4, 'BerserkerMiddleBommerKillCount', 'int'),
    (0x11C, 4, 'BerserkerMiddleKillCount', 'int'),
    (0x120, 4, 'BigGiantSpiderKillCount', 'int'),
    (0x124, 4, 'BigGreyBossKillCount', 'int'),
    (0x128, 4, 'Carrier1KillCount', 'int'),
    (0x12C, 4, 'DangoKillCount', 'int'),
    (0x130, 4, 'DeiroiKillCount', 'int'),
    (0x134, 4, 'DragonAceKillCount', 'int'),
    (0x138, 4, 'DragonKillCount', 'int'),
    (0x13C, 4, 'EasyClearRatio', 'int'),
    (0x140, 4, 'FencerArmor', 'float'),
    (0x144, 4, 'FencerEasyClearRatio', 'int'),
    (0x148, 4, 'FencerHardClearRatio', 'int'),
    (0x14C, 4, 'FencerHardestClearRatio', 'int'),
    (0x150, 4, 'FencerInfernoClearRatio', 'int'),
    (0x154, 4, 'FencerNormalClearRatio', 'int'),
    (0x158, 4, 'FencerPlayCount', 'int'),
    (0x15C, 4, 'FortressKillCount', 'int'),
    (0x160, 4, 'FrameCount', 'int'),
    (0x164, 4, 'FrogKillCount', 'int'),
    (0x168, 4, 'GiantAntKillCount', 'int'),
    (0x16C, 4, 'GiantAntQueenKillCount', 'int'),
    (0x170, 4, 'GiantBeeKillCount', 'int'),
    (0x174, 4, 'GiantBeeQueenKillCount', 'int'),
    (0x178, 4, 'GiantSpiderKillCount', 'int'),
    (0x17C, 4, 'GoldUfoAceKillCount', 'int'),
    (0x180, 4, 'GoldUfoKillCount', 'int'),
    (0x184, 4, 'GreyKillCount', 'int'),
    (0x188, 4, 'GuardDamage', 'float'),
    (0x18C, 4, 'HardClearRatio', 'int'),
    (0x190, 4, 'HardestClearRatio', 'int'),
    (0x194, 4, 'HealDamage', 'float'),
    (0x198, 4, 'HornetNestKillCount', 'int'),
    (0x19C, 4, 'HornetNestSnallKillCount', 'int'),
    (0x1A0, 4, 'ImperialUfoAceKillCount', 'int'),
    (0x1A4, 4, 'ImperialUfoKillCount', 'int'),
    (0x1A8, 4, 'InfernoClearRatio', 'int'),
    (0x1AC, 4, 'JormungandKillCount', 'int'),
    (0x1B0, 4, 'MartianKillCount', 'int'),
    (0x1B4, 4, 'MermanKillCount', 'int'),
    (0x1B8, 4, 'Monster501KillCount', 'int'),
    (0x1BC, 4, 'Monster504KillCount', 'int'),
    (0x1C0, 4, 'MotherShipKillCount', 'int'),
    (0x1C4, 4, 'NephilaKillCount', 'int'),
    (0x1C8, 4, 'NormalClearRatio', 'int'),
    (0x1CC, 4, 'OfflinePlayCount', 'int'),
    (0x1D0, 4, 'OnlinePlayCount', 'int'),
    (0x1D4, 4, 'PlayCount', 'int'),
    (0x1D8, 4, 'RadonKillCount', 'int'),
    (0x1DC, 4, 'RangerArmor', 'float'),
    (0x1E0, 4, 'RangerEasyClearRatio', 'int'),
    (0x1E4, 4, 'RangerHardClearRatio', 'int'),
    (0x1E8, 4, 'RangerHardestClearRatio', 'int'),
    (0x1EC, 4, 'RangerInfernoClearRatio', 'int'),
    (0x1F0, 4, 'RangerNormalClearRatio', 'int'),
    (0x1F4, 4, 'RangerPlayCount', 'int'),
    (0x1F8, 4, 'RescueCount', 'int'),
    (0x1FC, 4, 'RingMotherKillCount', 'int'),
    (0x200, 4, 'ShellFishAceKillCount', 'int'),
    (0x204, 4, 'ShellFishKillCount', 'int'),
    (0x208, 4, 'ShieldBearerKillCount', 'int'),
    (0x20C, 4, 'SpinnerUfoAceKillCount', 'int'),
    (0x210, 4, 'SpinnerUfoKillCount', 'int'),
    (0x214, 4, 'SquidSmallKillCount', 'int'),
    (0x218, 4, 'TeleportionAnchorKillCount', 'int'),
    (0x21C, 4, 'TimeShipAnchorKillCount', 'int'),
    (0x220, 4, 'VenusKillCount', 'int'),
    (0x224, 4, 'WeaponCount', 'int'),
    (0x228, 4, 'WeaponGetRatio', 'float'),
    (0x22C, 4, 'WingDiverArmor', 'float'),
    (0x230, 4, 'WingDiverEasyClearRatio', 'int'),
    (0x234, 4, 'WingDiverHardClearRatio', 'int'),
    (0x238, 4, 'WingDiverHardestClearRatio', 'int'),
    (0x23C, 4, 'WingDiverInfernoClearRatio', 'int'),
    (0x240, 4, 'WingDiverNormalClearRatio', 'int'),
    (0x244, 4, 'WingDiverPlayCount', 'int'),
]

# EDF6_ACHIEVEMENT_EVENTS: the 39 Steam achievement unlock formulas from EDF6's Achievement.sgo -
# not currently wired into the UI (EDF6's existing 0x14/0x34 byte-flag achievement system already
# covers these same 39 achievements and is independently confirmed working), kept here for
# reference/future cross-validation and because it's the same shape as EDF41_ACHIEVEMENT_EVENTS.
EDF6_ACHIEVEMENT_EVENTS = [
    (1, 'Conquest5', 'AllClearRatio', '>=', 500, 'int'),
    (2, 'Conquest10', 'AllClearRatio', '>=', 1000, 'int'),
    (3, 'Conquest15', 'AllClearRatio', '>=', 1500, 'int'),
    (4, 'Conquest20', 'AllClearRatio', '>=', 2000, 'int'),
    (5, 'Conquest25', 'AllClearRatio', '>=', 2500, 'int'),
    (6, 'Conquest30', 'AllClearRatio', '>=', 3000, 'int'),
    (7, 'Conquest35', 'AllClearRatio', '>=', 3500, 'int'),
    (8, 'Conquest40', 'AllClearRatio', '>=', 4000, 'int'),
    (9, 'Conquest45', 'AllClearRatio', '>=', 4500, 'int'),
    (10, 'Conquest50', 'AllClearRatio', '>=', 5000, 'int'),
    (11, 'Conquest55', 'AllClearRatio', '>=', 5500, 'int'),
    (12, 'Conquest60', 'AllClearRatio', '>=', 6000, 'int'),
    (13, 'Conquest62', 'AllClearRatio', '>=', 6200, 'int'),
    (14, 'Conquest64', 'AllClearRatio', '>=', 6400, 'int'),
    (15, 'Conquest66', 'AllClearRatio', '>=', 6600, 'int'),
    (16, 'Conquest68', 'AllClearRatio', '>=', 6800, 'int'),
    (17, 'Conquest70', 'AllClearRatio', '>=', 7000, 'int'),
    (18, 'Conquest72', 'AllClearRatio', '>=', 7200, 'int'),
    (19, 'Conquest74', 'AllClearRatio', '>=', 7400, 'int'),
    (20, 'Conquest76', 'AllClearRatio', '>=', 7600, 'int'),
    (21, 'Conquest78', 'AllClearRatio', '>=', 7800, 'int'),
    (22, 'Conquest80', 'AllClearRatio', '>=', 8000, 'int'),
    (23, 'Conquest82', 'AllClearRatio', '>=', 8200, 'int'),
    (24, 'Conquest84', 'AllClearRatio', '>=', 8400, 'int'),
    (25, 'Conquest86', 'AllClearRatio', '>=', 8600, 'int'),
    (26, 'Conquest88', 'AllClearRatio', '>=', 8800, 'int'),
    (27, 'Conquest90', 'AllClearRatio', '>=', 9000, 'int'),
    (28, 'Conquest92', 'AllClearRatio', '>=', 9200, 'int'),
    (29, 'Conquest94', 'AllClearRatio', '>=', 9400, 'int'),
    (30, 'Conquest96', 'AllClearRatio', '>=', 9600, 'int'),
    (31, 'Conquest98', 'AllClearRatio', '>=', 9800, 'int'),
    (32, 'Conquest100', 'AllClearRatio', '>=', 10000, 'int'),
    (33, 'MasterRanger', 'RangerArmor', '>=', 1000, 'float'),
    (34, 'MasterWingDiver', 'WingDiverArmor', '>=', 550, 'float'),
    (35, 'MasterAirRaider', 'AirRaiderArmor', '>=', 1000, 'float'),
    (36, 'MasterFencer', 'FencerArmor', '>=', 1250, 'float'),
    (37, 'Rescue', 'RescueCount', '>=', 5, 'int'),
    (38, 'SuperRescue', 'RescueCount', '>=', 50, 'int'),
    (39, 'Medic', 'HealDamage', '>', 0, 'float'),
]

# EDF5 kill-stats table. Originally a 40-entry, name-keyed (not +0xC shift of KILL_FIELDS)
# live-diff-derived table (semantic names guessed from watching which byte changed after each
# in-game action - kept in the history comment block below for attribution).
#
# SUPERSEDED 2026-09-08: replaced with the full 71-entry, Achievement.sgo-derived table, using the
# same architecture Ghidra RE confirmed for EDF4.1/EDF6 (AchievementVariable names inserted into a
# wstring-keyed red-black tree, in-order walk = alphabetical = slot order, one 4-byte counter per
# slot starting at a fixed TROPHY.DAT file offset). Source: D:\EDF_GhidraRE_Documents\Real
# Files\Achievement.json (a decoded Achievement.sgo; provenance confirmed to be EDF5, not EDF4.1,
# purely from the reconciliation below - the file's own JSON has no game field, but its 71
# AchievementVariable names sort alphabetically into EXACTLY the old 40-entry table's offsets with
# zero gaps and zero type mismatches, which is only possible if this is EDF5's own Achievement.sgo).
#
# Base-offset derivation: matched 13 old semantic names to their obvious real-name equivalents
# (armor_value_<class> -> <Class>Armor, missions_as_<class> -> <Class>PlayCount,
# gameplay_time_frames -> FrameCount, weapons_acquired -> WeaponCount, weapon_acquisition_rate ->
# WeaponGetRatio, rescues -> RescueCount, shield_bearers_defeated -> ShieldBearerKillCount) and
# computed implied_base = real_offset - alphabetical_index*4 for each. All 13 unanimously gave
# base 0xE8 - the single outlier from a 14th naive guess (teleportation_anchors_defeated ->
# TeleportionAnchorKillCount, at then-known offset 0x17C) was the wrong pairing, not proof against
# the base: at 0xE8, TeleportionAnchorKillCount lands at 0x1DC, a gap the old 40-entry table never
# had a name for - it was just never among the ~40 live-diffed fields, not evidence of a shift.
# Re-validated ALL 40 old entries against base 0xE8 with zero offset conflicts and zero type
# mismatches (every float/int old-table type matches the real Achievement.sgo type exactly); ~30 of
# the 40 also have strong-to-exact semantic matches (motherships_defeated->MotherShipKillCount,
# araneas_defeated->NephilaKillCount, deroys_defeated->DeiroiKillCount, hives_defeated->
# HornetNestKillCount, teleportation_ships_defeated->Carrier1KillCount, outpost_bases_defeated->
# FortressKillCount, mother_monsters_defeated->GiantAntQueenKillCount, queens_defeated->
# GiantBeeQueenKillCount, online_missions_started->OnlinePlayCount, imperial_drones_defeated->
# ImperialUfoAceKillCount, armor_item_acquisition->ArmorCount, etc.) - the remaining ~10 (e.g.
# teleportation_devices_defeated->AntHillKillCount, kings_defeated->BigGiantSpiderKillCount,
# silver_man_defeated->BigGreyBossKillCount, the two tadpole fields->DragonAceKillCount/
# DragonKillCount, colonists_defeated->FrogKillCount, cosmonauts_defeated->GreyKillCount,
# missions_started->OfflinePlayCount, teleportation_anchors_defeated->HardClearRatio) are simply
# where the original live-diff session's semantic guess was wrong - expected, since diffing bytes
# after an action doesn't reveal true meaning the way a real Achievement.sgo name does. The old
# table's last entry (missions_as_wingdiver @ 0x200) lands on the new table's last slot too - a
# clean, gapless, exact-boundary match end to end (0xE8-0x200, 71 slots), same shape as EDF6's own
# zero-gap reconciliation. See SAVE_FORMAT_NOTES.md for the full derivation.
EDF5_KILL_FIELDS = [
    (0x0E8, 4, 'AirRaiderArmor', 'float'),
    (0x0EC, 4, 'AirRaiderEasyClearRatio', 'int'),
    (0x0F0, 4, 'AirRaiderHardClearRatio', 'int'),
    (0x0F4, 4, 'AirRaiderHardestClearRatio', 'int'),
    (0x0F8, 4, 'AirRaiderInfernoClearRatio', 'int'),
    (0x0FC, 4, 'AirRaiderNormalClearRatio', 'int'),
    (0x100, 4, 'AirRaiderPlayCount', 'int'),
    (0x104, 4, 'AllClearRatio', 'int'),
    (0x108, 4, 'AntHillKillCount', 'int'),
    (0x10C, 4, 'ArmorCount', 'int'),
    (0x110, 4, 'BigGiantSpiderKillCount', 'int'),
    (0x114, 4, 'BigGreyBossKillCount', 'int'),
    (0x118, 4, 'Carrier1KillCount', 'int'),
    (0x11C, 4, 'DangoKillCount', 'int'),
    (0x120, 4, 'DeiroiKillCount', 'int'),
    (0x124, 4, 'DragonAceKillCount', 'int'),
    (0x128, 4, 'DragonKillCount', 'int'),
    (0x12C, 4, 'EasyClearRatio', 'int'),
    (0x130, 4, 'FencerArmor', 'float'),
    (0x134, 4, 'FencerEasyClearRatio', 'int'),
    (0x138, 4, 'FencerHardClearRatio', 'int'),
    (0x13C, 4, 'FencerHardestClearRatio', 'int'),
    (0x140, 4, 'FencerInfernoClearRatio', 'int'),
    (0x144, 4, 'FencerNormalClearRatio', 'int'),
    (0x148, 4, 'FencerPlayCount', 'int'),
    (0x14C, 4, 'FortressKillCount', 'int'),
    (0x150, 4, 'FrameCount', 'int'),
    (0x154, 4, 'FrogKillCount', 'int'),
    (0x158, 4, 'GiantAntKillCount', 'int'),
    (0x15C, 4, 'GiantAntQueenKillCount', 'int'),
    (0x160, 4, 'GiantBeeKillCount', 'int'),
    (0x164, 4, 'GiantBeeQueenKillCount', 'int'),
    (0x168, 4, 'GiantSpiderKillCount', 'int'),
    (0x16C, 4, 'GoldUfoAceKillCount', 'int'),
    (0x170, 4, 'GoldUfoKillCount', 'int'),
    (0x174, 4, 'GreyKillCount', 'int'),
    (0x178, 4, 'GuardDamage', 'float'),
    (0x17C, 4, 'HardClearRatio', 'int'),
    (0x180, 4, 'HardestClearRatio', 'int'),
    (0x184, 4, 'HealDamage', 'float'),
    (0x188, 4, 'HornetNestKillCount', 'int'),
    (0x18C, 4, 'ImperialUfoAceKillCount', 'int'),
    (0x190, 4, 'ImperialUfoKillCount', 'int'),
    (0x194, 4, 'InfernoClearRatio', 'int'),
    (0x198, 4, 'Monster501KillCount', 'int'),
    (0x19C, 4, 'Monster504KillCount', 'int'),
    (0x1A0, 4, 'MotherShipKillCount', 'int'),
    (0x1A4, 4, 'NephilaKillCount', 'int'),
    (0x1A8, 4, 'NormalClearRatio', 'int'),
    (0x1AC, 4, 'OfflinePlayCount', 'int'),
    (0x1B0, 4, 'OnlinePlayCount', 'int'),
    (0x1B4, 4, 'PlayCount', 'int'),
    (0x1B8, 4, 'RangerArmor', 'float'),
    (0x1BC, 4, 'RangerEasyClearRatio', 'int'),
    (0x1C0, 4, 'RangerHardClearRatio', 'int'),
    (0x1C4, 4, 'RangerHardestClearRatio', 'int'),
    (0x1C8, 4, 'RangerInfernoClearRatio', 'int'),
    (0x1CC, 4, 'RangerNormalClearRatio', 'int'),
    (0x1D0, 4, 'RangerPlayCount', 'int'),
    (0x1D4, 4, 'RescueCount', 'int'),
    (0x1D8, 4, 'ShieldBearerKillCount', 'int'),
    (0x1DC, 4, 'TeleportionAnchorKillCount', 'int'),
    (0x1E0, 4, 'WeaponCount', 'int'),
    (0x1E4, 4, 'WeaponGetRatio', 'float'),
    (0x1E8, 4, 'WingDiverArmor', 'float'),
    (0x1EC, 4, 'WingDiverEasyClearRatio', 'int'),
    (0x1F0, 4, 'WingDiverHardClearRatio', 'int'),
    (0x1F4, 4, 'WingDiverHardestClearRatio', 'int'),
    (0x1F8, 4, 'WingDiverInfernoClearRatio', 'int'),
    (0x1FC, 4, 'WingDiverNormalClearRatio', 'int'),
    (0x200, 4, 'WingDiverPlayCount', 'int'),
]
EDF5_ACHIEVEMENT_VARIABLES = EDF5_KILL_FIELDS  # same table, alias for clarity at achievement call sites

# EDF5_ACHIEVEMENT_EVENTS: the 39 Steam achievement unlock formulas from EDF5's Achievement.sgo -
# same 32x Conquest%/Master*/Rescue/SuperRescue/Medic shape as EDF6's (confirms the hardcoded
# `percentages` list and `other_achievements_names` order already used by EDF5's existing 0x14+0xC/
# 0x34+0xC byte-flag Achievements panel logic above - 32 Conquest steps + 7 "other" entries in the
# exact same order). Not wired into the UI: EDF5 already has a working (if unverified-shift) stored
# byte-flag system for these same 39 achievements, unlike EDF4.1 which has none. Kept for reference
# and as a future cross-check if a real EDF5 TROPHY.DAT ever turns up to test the +0xC shift against.
EDF5_ACHIEVEMENT_EVENTS = [
    (1, 'Conquest5', 'AllClearRatio', '>=', 500, 'int'),
    (2, 'Conquest10', 'AllClearRatio', '>=', 1000, 'int'),
    (3, 'Conquest15', 'AllClearRatio', '>=', 1500, 'int'),
    (4, 'Conquest20', 'AllClearRatio', '>=', 2000, 'int'),
    (5, 'Conquest25', 'AllClearRatio', '>=', 2500, 'int'),
    (6, 'Conquest30', 'AllClearRatio', '>=', 3000, 'int'),
    (7, 'Conquest35', 'AllClearRatio', '>=', 3500, 'int'),
    (8, 'Conquest40', 'AllClearRatio', '>=', 4000, 'int'),
    (9, 'Conquest45', 'AllClearRatio', '>=', 4500, 'int'),
    (10, 'Conquest50', 'AllClearRatio', '>=', 5000, 'int'),
    (11, 'Conquest55', 'AllClearRatio', '>=', 5500, 'int'),
    (12, 'Conquest60', 'AllClearRatio', '>=', 6000, 'int'),
    (13, 'Conquest62', 'AllClearRatio', '>=', 6200, 'int'),
    (14, 'Conquest64', 'AllClearRatio', '>=', 6400, 'int'),
    (15, 'Conquest66', 'AllClearRatio', '>=', 6600, 'int'),
    (16, 'Conquest68', 'AllClearRatio', '>=', 6800, 'int'),
    (17, 'Conquest70', 'AllClearRatio', '>=', 7000, 'int'),
    (18, 'Conquest72', 'AllClearRatio', '>=', 7200, 'int'),
    (19, 'Conquest74', 'AllClearRatio', '>=', 7400, 'int'),
    (20, 'Conquest76', 'AllClearRatio', '>=', 7600, 'int'),
    (21, 'Conquest78', 'AllClearRatio', '>=', 7800, 'int'),
    (22, 'Conquest80', 'AllClearRatio', '>=', 8000, 'int'),
    (23, 'Conquest82', 'AllClearRatio', '>=', 8200, 'int'),
    (24, 'Conquest84', 'AllClearRatio', '>=', 8400, 'int'),
    (25, 'Conquest86', 'AllClearRatio', '>=', 8600, 'int'),
    (26, 'Conquest88', 'AllClearRatio', '>=', 8800, 'int'),
    (27, 'Conquest90', 'AllClearRatio', '>=', 9000, 'int'),
    (28, 'Conquest92', 'AllClearRatio', '>=', 9200, 'int'),
    (29, 'Conquest94', 'AllClearRatio', '>=', 9400, 'int'),
    (30, 'Conquest96', 'AllClearRatio', '>=', 9600, 'int'),
    (31, 'Conquest98', 'AllClearRatio', '>=', 9800, 'int'),
    (32, 'Conquest100', 'AllClearRatio', '>=', 10000, 'int'),
    (33, 'MasterRanger', 'RangerArmor', '>=', 1000, 'float'),
    (34, 'MasterWingDiver', 'WingDiverArmor', '>=', 550, 'float'),
    (35, 'MasterAirRaider', 'AirRaiderArmor', '>=', 1000, 'float'),
    (36, 'MasterFencer', 'FencerArmor', '>=', 1250, 'float'),
    (37, 'Rescue', 'RescueCount', '>=', 5, 'int'),
    (38, 'SuperRescue', 'RescueCount', '>=', 50, 'int'),
    (39, 'Medic', 'HealDamage', '>', 0, 'float'),
]

# EDF4.1 kill-stats table. Extended 2026-09-06 via byte-scan of a real, non-template TROPHY.DAT
# (FevGrave's saveslot03) against every value on that save's in-game Battle History screen - each
# new field below was an EXACT, UNAMBIGUOUS int32 match (only one offset in the whole 1024-byte
# file held that value), so confidence is high. Still not-yet-placed, found during the same pass:
#   - The 6 fields that were ambiguous (four tied at value 2, two tied at value 1) are RESOLVED,
#     2026-09-06: wrote distinct sentinel values (1001-1006) directly into each of the 6 offsets in
#     saveslot03's TROPHY.DAT (checksum recomputed, re-encrypted), had FevGrave load the save and
#     read which Battle History row showed which sentinel, then restored the original bytes from
#     backup. Two of six landed opposite the proximity-based guess that shipped earlier today -
#     confirms that guess was the right call to flag rather than commit: byte order really doesn't
#     track the UI's display order here.
#     CAVEAT learned the hard way: EDF4.1 was still running while this was done, so it had the
#     save's real motherships_defeated/brains_defeated (0x17C/0x180) loaded in memory. Restoring
#     the file's on-disk bytes afterward didn't stick - the game's next autosave overwrote the
#     restore with its own in-memory copy, which still held the 1005/1006 sentinels. Those two
#     fields are stuck at 1005/1006 on saveslot03 permanently now (FevGrave's call: leave it, it's
#     a cosmetic-only stat). Lesson for next time: sentinel-value byte ID tricks like this one
#     need the game fully closed first, or expect a real (not just file-level) fix afterward.
#   - "Games Started: 47" from the same screen was NOT found anywhere in the file as a raw int32 -
#     likely computed (e.g. offline+online games started summed) rather than stored directly.
#   - CONFIRMED 2026-09-06 (FevGrave): the difficulty-completion-rate percentages on the Battle
#     History screen (Easy/Normal/Hard/VeryHard/Inferno x Overall/Ranger/WingDiver/AirRaider/
#     Fencer, plus the all-difficulty/all-class rate - ~26 fields total) are CALCULATED, not
#     stored - the game derives them live from the mission-table completion bits (DEFP_M00.MST
#     etc.), matching what the byte-scan already pointed at: only 3 small nonzero floats exist
#     anywhere in the whole 1024-byte file (0x104, 0x124, 0x1D8), nowhere near enough for 26
#     distinct stored rates. Renamed the three fields that used to claim otherwise
#     ('easy_completion_rate_overall'/'_fencer'/'_ranger' at 0x124/0x12C/0x1A0) to honest
#     'unknown_float_0x...' placeholders rather than keep a name now known to be wrong - they are
#     still real, present fields (0x124 held ~0.0109 on saveslot03, oddly close to that save's
#     actual Very Hard Overall rate of 1%, but that's most likely coincidence now that "these
#     percentages aren't stored" is confirmed, not evidence of what 0x124 really is), just not yet
#     identified. Whatever they actually are needs its own byte-scan/sentinel pass the same way
#     the contested int fields above were resolved.
#   - 'missions_as_air_raider' (0x0FC) is BY ELIMINATION, not sentinel-confirmed: FevGrave played
#     exactly 1 Air Raider mission on saveslot03 and asked to check for a "1" near
#     missions_as_wingdiver (0x1EC) - nothing turned up there (that whole neighborhood is the
#     Wing Diver armor-float block/padding), so the search was widened to the whole file. Only 3
#     offsets held `1` at all: 0x004 (the MDB0 header's own format-version field, confirmed
#     unrelated), 0x028 (inside the early achievement-boolean-flag region - reads as 1 only
#     because one flag byte in that 4-byte group is set, not a real int32 counter), and 0x0FC
#     (isolated, no other explanation, and in the same rough neighborhood as EDF6's own "Missions
#     Played as Air Raider" at 0xF4). Reasonably confident but not sentinel-verified like the
#     others - worth double-checking with a second Air Raider mission (should read 2, not stay at
#     1) before fully trusting it.
# SUPERSEDED 2026-09-08: the table above (byte-scan + partial sentinel-test derived) is kept in
# this comment block for history/attribution, but EDF41_KILL_FIELDS itself now points at the
# fuller, Achievement.sgo-derived table below. Every field this old table covered was cross-
# checked against the new one and matched with ZERO type mismatches once a uniform +6 slot
# (+0x18 byte) shift was applied (the exact shift needed because the ACHIEVEMENT.json snapshot
# used is missing 6 unknown, alphabetically-first entries) - see SAVE_FORMAT_NOTES.md's
# "2026-09-08 (same day, cont'd 3)" section for the full reconciliation. The old table's semantic
# guesses (e.g. 'quadrupeds_defeated', 'shield_bearers_defeated') are superseded by the real,
# game-data names ('4LegTankKillCount', 'AlienTrailerKillCount', etc.) below - same offsets, same
# values, better names, plus ~30 previously-unlisted fields (class clear-ratios, PlayCounts,
# HealDamage/GuardDamage, WeaponCount, ArmorCount, elevation/max_elevation).
#
# EDF41_ACHIEVEMENT_VARIABLES: the 76 real counter slots in EDF4.1's TROPHY.DAT, 0xC8-0x1F4,
# reconstructed from D:\EDF_GhidraRE_Documents\Real Files\dlc\ACHIEVEMENT.json (a decoded
# APP:/ETC/Achievement.sgo) sorted alphabetically per the same logic Ghidra RE confirmed EDF6 uses
# (AchievementSystemInit @ EDF6 0x1800cdd30 - inserts every AchievementVariable into a
# wstring-keyed red-black tree, in-order walk = alphabetical = slot order; EDF4.1's own
# deserializer FUN_1400cfcf0 does the identical walk, writing raw[0xC8:] into the counter tree).
# Slots 0-5 (0xC8-0xDC) are still unnamed - missing from this particular Achievement.sgo snapshot,
# needs a newer/more complete dump to resolve; everything from 0xE0 on is the real game data.
EDF41_KILL_FIELDS = [
    (0xC8, 4, 'unknown_0xC8', 'int'),  # not in this Achievement.sgo snapshot - real name unresolved
    (0xCC, 4, 'unknown_0xCC', 'int'),  # not in this Achievement.sgo snapshot - real name unresolved
    (0xD0, 4, 'unknown_0xD0', 'int'),  # not in this Achievement.sgo snapshot - real name unresolved
    (0xD4, 4, 'unknown_0xD4', 'int'),  # not in this Achievement.sgo snapshot - real name unresolved
    (0xD8, 4, 'unknown_0xD8', 'int'),  # not in this Achievement.sgo snapshot - real name unresolved
    (0xDC, 4, 'unknown_0xDC', 'int'),  # not in this Achievement.sgo snapshot - real name unresolved
    (0xE0, 4, '4LegTankKillCount', 'int'),
    (0xE4, 4, 'AirRaiderArmor', 'float'),
    (0xE8, 4, 'AirRaiderEasyClearRatio', 'float'),
    (0xEC, 4, 'AirRaiderHardClearRatio', 'float'),
    (0xF0, 4, 'AirRaiderHardestClearRatio', 'float'),
    (0xF4, 4, 'AirRaiderInfernoClearRatio', 'float'),
    (0xF8, 4, 'AirRaiderNormalClearRatio', 'float'),
    (0xFC, 4, 'AirRaiderPlayCount', 'int'),
    (0x100, 4, 'AlienTrailerKillCount', 'int'),
    (0x104, 4, 'AllClearRatio', 'float'),
    (0x108, 4, 'ArmorCount', 'int'),
    (0x10C, 4, 'BigDragonKillCount', 'int'),
    (0x110, 4, 'BigGiantSpiderKillCount', 'int'),
    (0x114, 4, 'Carrier1KillCount', 'int'),
    (0x118, 4, 'Carrier2KillCount', 'int'),
    (0x11C, 4, 'DeiroiKillCount', 'int'),
    (0x120, 4, 'DragonKillCount', 'int'),
    (0x124, 4, 'EasyClearRatio', 'float'),
    (0x128, 4, 'FencerArmor', 'float'),
    (0x12C, 4, 'FencerEasyClearRatio', 'float'),
    (0x130, 4, 'FencerHardClearRatio', 'float'),
    (0x134, 4, 'FencerHardestClearRatio', 'float'),
    (0x138, 4, 'FencerInfernoClearRatio', 'float'),
    (0x13C, 4, 'FencerNormalClearRatio', 'float'),
    (0x140, 4, 'FencerPlayCount', 'int'),
    (0x144, 4, 'FrameCount', 'int'),
    (0x148, 4, 'GiantAntKillCount', 'int'),
    (0x14C, 4, 'GiantAntQueenKillCount', 'int'),
    (0x150, 4, 'GiantBeeKillCount', 'int'),
    (0x154, 4, 'GiantBeeQueenKillCount', 'int'),
    (0x158, 4, 'GiantSpiderKillCount', 'int'),
    (0x15C, 4, 'GuardDamage', 'float'),
    (0x160, 4, 'HardClearRatio', 'float'),
    (0x164, 4, 'HardestClearRatio', 'float'),
    (0x168, 4, 'HealDamage', 'float'),
    (0x16C, 4, 'HectorKillCount', 'int'),
    (0x170, 4, 'HornetNestKillCount', 'int'),
    (0x174, 4, 'InfernoClearRatio', 'float'),
    (0x178, 4, 'Monster501KillCount', 'int'),
    (0x17C, 4, 'MotherShip301KillCount', 'int'),
    (0x180, 4, 'MotherShip401KillCount', 'int'),
    (0x184, 4, 'NephilaKillCount', 'int'),
    (0x188, 4, 'NestKillCount', 'int'),
    (0x18C, 4, 'NormalClearRatio', 'float'),
    (0x190, 4, 'OfflinePlayCount', 'int'),
    (0x194, 4, 'OnlinePlayCount', 'int'),
    (0x198, 4, 'PlayCount', 'int'),
    (0x19C, 4, 'RangerArmor', 'float'),
    (0x1A0, 4, 'RangerEasyClearRatio', 'float'),
    (0x1A4, 4, 'RangerHardClearRatio', 'float'),
    (0x1A8, 4, 'RangerHardestClearRatio', 'float'),
    (0x1AC, 4, 'RangerInfernoClearRatio', 'float'),
    (0x1B0, 4, 'RangerNormalClearRatio', 'float'),
    (0x1B4, 4, 'RangerPlayCount', 'int'),
    (0x1B8, 4, 'RescueCount', 'int'),
    (0x1BC, 4, 'UfoRoboKillCount', 'int'),
    (0x1C0, 4, 'UfoSmall301AceKillCount', 'int'),
    (0x1C4, 4, 'UfoSmall301KillCount', 'int'),
    (0x1C8, 4, 'UfoSmall401KillCount', 'int'),
    (0x1CC, 4, 'WeaponCount', 'int'),
    (0x1D0, 4, 'WeaponGetRatio', 'float'),
    (0x1D4, 4, 'WingDiverArmor', 'float'),
    (0x1D8, 4, 'WingDiverEasyClearRatio', 'float'),
    (0x1DC, 4, 'WingDiverHardClearRatio', 'float'),
    (0x1E0, 4, 'WingDiverHardestClearRatio', 'float'),
    (0x1E4, 4, 'WingDiverInfernoClearRatio', 'float'),
    (0x1E8, 4, 'WingDiverNormalClearRatio', 'float'),
    (0x1EC, 4, 'WingDiverPlayCount', 'int'),
    (0x1F0, 4, 'elevation', 'float'),
    (0x1F4, 4, 'max_elevation', 'float'),
]
EDF41_ACHIEVEMENT_VARIABLES = EDF41_KILL_FIELDS  # same table, alias for clarity at achievement call sites

# EDF41_ACHIEVEMENT_EVENTS: the 51 named-achievement unlock formulas from Achievement.sgo's
# AchievementEvent section - (id, event_name, target_variable_key, comparison_op, threshold,
# value_type). event_name is the game's own internal name, typos included ("RangerNromalClear" is
# real, not a transcription error here). target_variable_key indexes into the dict returned by
# extract_kill_fields(td, EDF41_KILL_FIELDS) / app.kill_fields.
EDF41_ACHIEVEMENT_EVENTS = [
    (1, 'RangerNromalClear', 'RangerNormalClearRatio', '>=', 1, 'float'),
    (2, 'RangerHardClear', 'RangerHardClearRatio', '>=', 1, 'float'),
    (3, 'RangerHardestClear', 'RangerHardestClearRatio', '>=', 1, 'float'),
    (4, 'RangerInfernoClear', 'RangerInfernoClearRatio', '>=', 1, 'float'),
    (5, 'WingDiverNormalClear', 'WingDiverNormalClearRatio', '>=', 1, 'float'),
    (6, 'WingDiverHardClear', 'WingDiverHardClearRatio', '>=', 1, 'float'),
    (7, 'WingDiverHardestClear', 'WingDiverHardestClearRatio', '>=', 1, 'float'),
    (8, 'WingDiverInfernoClear', 'WingDiverInfernoClearRatio', '>=', 1, 'float'),
    (9, 'AirRaiderNormalClear', 'AirRaiderNormalClearRatio', '>=', 1, 'float'),
    (10, 'AirRaiderHardClear', 'AirRaiderHardClearRatio', '>=', 1, 'float'),
    (11, 'AirRaiderHardestClear', 'AirRaiderHardestClearRatio', '>=', 1, 'float'),
    (12, 'AirRaiderInfernoClear', 'AirRaiderInfernoClearRatio', '>=', 1, 'float'),
    (13, 'FencerNormalClear', 'FencerNormalClearRatio', '>=', 1, 'float'),
    (14, 'FencerHardClear', 'FencerHardClearRatio', '>=', 1, 'float'),
    (15, 'FencerHardestClear', 'FencerHardestClearRatio', '>=', 1, 'float'),
    (16, 'FencerInfernoClear', 'FencerInfernoClearRatio', '>=', 1, 'float'),
    (17, 'GetWeapon10', 'WeaponGetRatio', '>=', 0.10000000149011612, 'float'),
    (18, 'GetWeapon50', 'WeaponGetRatio', '>=', 0.5, 'float'),
    (19, 'GetWeapon100', 'WeaponGetRatio', '>=', 1, 'float'),
    (20, 'AntHunter', 'GiantAntKillCount', '>=', 20000, 'int'),
    (21, 'SpiderHunter', 'GiantSpiderKillCount', '>=', 12000, 'int'),
    (22, 'FlyingDroneHunter', 'UfoSmall301KillCount', '>=', 5000, 'int'),
    (23, 'CarrierHunter', 'Carrier1KillCount', '>=', 500, 'int'),
    (24, 'HectorHunter', 'HectorKillCount', '>=', 900, 'int'),
    (25, 'FortressHunter', '4LegTankKillCount', '>=', 12, 'int'),
    (26, 'QueenHunter', 'GiantAntQueenKillCount', '>=', 24, 'int'),
    (27, 'KingHunter', 'BigGiantSpiderKillCount', '>=', 40, 'int'),
    (28, 'RedColorHunter', 'UfoSmall301AceKillCount', '>=', 150, 'int'),
    (29, 'MotherShipHunnter', 'MotherShip301KillCount', '>=', 6, 'int'),
    (30, 'NephilaHunter', 'NephilaKillCount', '>=', 360, 'int'),
    (31, 'TunnelHunter', 'NestKillCount', '>=', 200, 'int'),
    (32, 'SheldHunter', 'AlienTrailerKillCount', '>=', 120, 'int'),
    (33, 'BeeHunter', 'GiantBeeKillCount', '>=', 4000, 'int'),
    (34, 'DeathHunter', 'GiantBeeQueenKillCount', '>=', 24, 'int'),
    (35, 'NestHunter', 'HornetNestKillCount', '>=', 6, 'int'),
    (36, 'VehicleHunter', 'UfoSmall401KillCount', '>=', 2000, 'int'),
    (37, 'JumpShipHunter', 'Carrier2KillCount', '>=', 200, 'int'),
    (38, 'DeiroiHunter', 'DeiroiKillCount', '>=', 200, 'int'),
    (39, 'DragonHunter', 'DragonKillCount', '>=', 2400, 'int'),
    (40, 'GreatHunter', 'BigDragonKillCount', '>=', 20, 'int'),
    (41, 'AlgoHunter', 'UfoRoboKillCount', '>=', 20, 'int'),
    (42, 'ErginusHunter', 'Monster501KillCount', '>=', 30, 'int'),
    (43, 'BrainHunter', 'MotherShip401KillCount', '>=', 6, 'int'),
    (44, 'MasterRanger', 'RangerArmor', '>=', 1000, 'float'),
    (45, 'MasterWingDiver', 'WingDiverArmor', '>=', 550, 'float'),
    (46, 'MasterAirRaider', 'AirRaiderArmor', '>=', 1000, 'float'),
    (47, 'MasterFencer', 'FencerArmor', '>=', 1250, 'float'),
    (48, 'Rescue', 'RescueCount', '>=', 5, 'int'),
    (49, 'SuperRescue', 'RescueCount', '>=', 50, 'int'),
    (50, 'Medic', 'HealDamage', '>', 0, 'float'),
    (51, 'Elevation200', 'elevation', '>', 200, 'float'),
]

def prettify_edf41_achievement_name(name: str) -> str:
    """'RangerNromalClear' -> 'Ranger Nromal Clear', 'GetWeapon100' -> 'Get Weapon 100'. Typos in
    the game's own data (e.g. 'Nromal') are kept as-is - not ours to silently correct."""
    spaced = re.sub(r'(?<!^)(?=[A-Z])', ' ', name)          # split before each capital
    spaced = re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', spaced)    # split letter->digit boundary
    return spaced

def humanize_field_key(key: str) -> str:
    """General fallback display-name formatter for kill/counter field keys, used when no
    translation string exists. Handles both naming styles this codebase uses: EDF6/EDF5's
    snake_case ('missions_as_air_raider' -> 'Missions As Air Raider') and EDF4.1's CamelCase
    Achievement.sgo names ('GiantAntKillCount' -> 'Giant Ant Kill Count') - plain
    key.replace('_',' ').title() mangles CamelCase into one run-on lowercase word since there are
    no underscores for it to split on."""
    s = key.replace('_', ' ')
    s = re.sub(r'(?<!^)(?<![ ])(?=[A-Z])', ' ', s)   # split before a capital, unless already at a space/start
    s = re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', s)       # split letter->digit boundary
    s = re.sub(r'\s+', ' ', s).strip()
    return s.title()

# EDF6_STATUS_INFO_NAMES: the REAL in-game English display names for every Kill Statistics /
# Achievement.sgo counter field, extracted 2026-09-08 from EDF6's own shipped localization asset -
# F:\...\EARTH DEFENSE FORCE 6\Root\ETC\TEXTTABLE_STEAM.EN.TXT_SGO (decoded to
# TEXTTABLE_STEAM.EN.TXT.json), whose `StatusInfo_<FieldName>` keys are exactly what the game's own
# Battle History screen looks up to label each stat (colon suffix stripped here - the game appends
# its own ": value" formatting). This is a MUCH stronger source than humanize_field_key()'s
# CamelCase-splitting guess (e.g. 'AntHillKillCount' humanizes to "Ant Hill Kill Count", but the
# real label is "Teleportation Devices Defeated" - the internal variable name and the shipped UI
# text don't always match at all) or the old live-diff-guessed semantic names this session already
# superseded. Cross-checked against KILL_FIELDS: 90/91 entries match exactly (the sole miss,
# GuardDamage, simply has no Battle History row - it's Achievement.sgo-only, not a display bug).
# EDF5/EDF4.1 don't have an equivalent table yet - their game installs weren't available this
# session to pull TEXTTABLE_STEAM.EN.TXT_SGO from; real_field_display_name() falls back to
# humanize_field_key() for both until that data can be added the same way.
EDF6_STATUS_INFO_NAMES = {
    'AirRaiderArmor': 'Armor Value (Air Raider)',
    'AirRaiderEasyClearRatio': 'Easy Difficulty Completion Rate (Air Raider)',
    'AirRaiderHardClearRatio': 'Hard Difficulty Completion Rate (Air Raider)',
    'AirRaiderHardestClearRatio': 'Hardest Difficulty Completion Rate (Air Raider)',
    'AirRaiderInfernoClearRatio': 'Inferno Difficulty Completion Rate (Air Raider)',
    'AirRaiderNormalClearRatio': 'Normal Difficulty Completion Rate (Air Raider)',
    'AirRaiderPlayCount': 'Missions as Air Raider',
    'AllClearRatio': 'Completion Rate for All Difficulty Levels',
    'AntHillKillCount': 'Teleportation Devices Defeated',
    'ArmorCount': 'Armor Item Acquisition',
    'BerserkerAKillCount': 'Androids Defeated',
    'BerserkerBKillCount': 'Super Androids Defeated',
    'BerserkerCKillCount': 'High Mobility Androids Defeated',
    'BerserkerDKillCount': 'Grenadiers Defeated',
    'BerserkerLargeKillCount': 'Cyclopes Defeated',
    'BerserkerMiddleBommerKillCount': 'Giant Grenadiers Defeated',
    'BerserkerMiddleKillCount': 'Giant Androids Defeated',
    'BigGiantSpiderKillCount': 'Kings Defeated',
    'BigGreyBossKillCount': 'Silver Man Defeated',
    'Carrier1KillCount': 'Teleportation Ships Defeated',
    'DangoKillCount': 'Aggressive Alien Species \u03b3s Defeated',
    'DeiroiKillCount': 'Deroys Defeated',
    'DragonAceKillCount': 'Giant Tadpoles Defeated',
    'DragonKillCount': 'Tadpoles Defeated',
    'EasyClearRatio': 'Easy Difficulty Completion Rate',
    'FencerArmor': 'Armor Value (Fencer)',
    'FencerEasyClearRatio': 'Easy Difficulty Completion Rate (Fencer)',
    'FencerHardClearRatio': 'Hard Difficulty Completion Rate (Fencer)',
    'FencerHardestClearRatio': 'Hardest Difficulty Completion Rate (Fencer)',
    'FencerInfernoClearRatio': 'Inferno Difficulty Completion Rate (Fencer)',
    'FencerNormalClearRatio': 'Normal Difficulty Completion Rate (Fencer)',
    'FencerPlayCount': 'Missions as Fencer',
    'FortressKillCount': 'Outpost Bases Defeated',
    'FrameCount': 'Gameplay Time',
    'FrogKillCount': 'Colonists Defeated',
    'GiantAntKillCount': 'Aggressive Alien Species \u03b1s Defeated',
    'GiantAntQueenKillCount': 'Mother Monsters Defeated',
    'GiantBeeKillCount': 'Flying Aggressors Defeated',
    'GiantBeeQueenKillCount': 'Queens Defeated',
    'GiantSpiderKillCount': 'Aggressive Alien Species \u03b2s Defeated',
    'GoldUfoAceKillCount': 'Red Drones Defeated',
    'GoldUfoKillCount': 'Drones Defeated',
    'GreyKillCount': 'Cosmonauts Defeated',
    'HardClearRatio': 'Hard Difficulty Completion Rate',
    'HardestClearRatio': 'Hardest Difficulty Completion Rate',
    'HealDamage': 'Recovery',
    'HornetNestKillCount': 'Hives Defeated',
    'HornetNestSnallKillCount': 'Small Hives Defeated',
    'ImperialUfoAceKillCount': 'Imperial Drones Defeated',
    'ImperialUfoKillCount': 'Type 2 Drones Defeated',
    'InfernoClearRatio': 'Inferno Difficulty Completion Rate',
    'JormungandKillCount': 'Primers Defeated',
    'MartianKillCount': 'Kruuls Defeated',
    'MermanKillCount': 'Scyllas Defeated',
    'Monster501KillCount': 'Erginuses Defeated',
    'Monster504KillCount': 'Archeluses Defeated',
    'MotherShipKillCount': 'Motherships Defeated',
    'NephilaKillCount': 'Araneas Defeated',
    'NormalClearRatio': 'Normal Difficulty Completion Rate',
    'OfflinePlayCount': 'Missions Started',
    'OnlinePlayCount': 'Online Missions Started',
    'PlayCount': 'Games Started',
    'RadonKillCount': 'Sirens/Glaucoses Defeated',
    'RangerArmor': 'Armor Value (Ranger)',
    'RangerEasyClearRatio': 'Easy Difficulty Completion Rate (Ranger)',
    'RangerHardClearRatio': 'Hard Difficulty Completion Rate (Ranger)',
    'RangerHardestClearRatio': 'Hardest Difficulty Completion Rate (Ranger)',
    'RangerInfernoClearRatio': 'Inferno Difficulty Completion Rate (Ranger)',
    'RangerNormalClearRatio': 'Normal Difficulty Completion Rate (Ranger)',
    'RangerPlayCount': 'Missions as Ranger',
    'RescueCount': 'Rescues',
    'RingMotherKillCount': 'Rings Defeated',
    'ShellFishAceKillCount': 'High Grade Excavators Defeated',
    'ShellFishKillCount': 'Excavators Defeated',
    'ShieldBearerKillCount': 'Shield Bearers Defeated',
    'SpinnerUfoAceKillCount': 'High Grade Type 3 Drones Defeated',
    'SpinnerUfoKillCount': 'Type 3 Drones Defeated',
    'SquidSmallKillCount': 'Hazes Defeated',
    'TeleportionAnchorKillCount': 'Teleportation Anchors Defeated',
    'TimeShipAnchorKillCount': 'Tail Anchors Defeated',
    'VenusKillCount': 'Krakens Defeated',
    'WeaponCount': 'Weapons Acquired',
    'WeaponGetRatio': 'Weapon Acquisition Rate',
    'WingDiverArmor': 'Armor Value (Wing Diver)',
    'WingDiverEasyClearRatio': 'Easy Difficulty Completion Rate (Wing Diver)',
    'WingDiverHardClearRatio': 'Hard Difficulty Completion Rate (Wing Diver)',
    'WingDiverHardestClearRatio': 'Hardest Difficulty Completion Rate (Wing Diver)',
    'WingDiverInfernoClearRatio': 'Inferno Difficulty Completion Rate (Wing Diver)',
    'WingDiverNormalClearRatio': 'Normal Difficulty Completion Rate (Wing Diver)',
    'WingDiverPlayCount': 'Missions as Wing Diver',
}

# EDF41_STATUS_INFO_NAMES: EDF4.1's own real, shipped Battle-History field labels (English),
# extracted 2026-09-08 from D:\EDF_GhidraRE_Documents\Real Files\TEXTTABLE_STEAM_EN.TXT_.json (a
# decoded StatusInfo_* table, same shape/source as EDF6's). 69/70 of EDF41_KILL_FIELDS' real names
# match exactly (the miss, 'elevation', has no Battle History row, same pattern as EDF6's
# GuardDamage). IMPORTANT, discovered while cross-checking against EDF6_STATUS_INFO_NAMES: 13 of
# the 55 field names shared between the two games' Achievement.sgo schemes have COMPLETELY
# DIFFERENT real meanings despite the identical internal variable name - e.g. 'DragonKillCount' is
# "Tadpoles Defeated" in EDF6 but "Dragons Defeated" in EDF4.1; 'BigGiantSpiderKillCount' is "Kings
# Defeated" in EDF6 but "King Spiders Defeated" in EDF4.1. This is why these names are kept in
# SEPARATE per-game dicts/languages.json key prefixes (EDF6_.../EDF41_...) rather than one shared
# flat namespace - a shared namespace would have silently shown EDF6's wrong label on EDF4.1 saves
# (and vice versa) for exactly these 13 fields. EDF4.1's own TEXTTABLE_STEAM_CN.TXT.json is NOT
# usable - it's byte-identical to TEXTTABLE_STEAM_JP.TXT.json (a decode artifact, not real Chinese
# text), so no Chinese/Korean data exists for EDF4.1 yet; only English is covered here as a Python
# fallback, though languages.json also carries EDF4.1's real Japanese names (EDF41_* keys) since
# that data was genuinely distinct.
EDF41_STATUS_INFO_NAMES = {
    '4LegTankKillCount': 'Quadrupeds Defeated',
    'AirRaiderArmor': 'Armor Value (Air Raider)',
    'AirRaiderEasyClearRatio': 'Easy Difficulty Completion Rate (Air Raider)',
    'AirRaiderHardClearRatio': 'Hard Difficulty Completion Rate (Air Raider)',
    'AirRaiderHardestClearRatio': 'Hardest Difficulty Completion Rate (Air Raider)',
    'AirRaiderInfernoClearRatio': 'Inferno Difficulty Completion Rate (Air Raider)',
    'AirRaiderNormalClearRatio': 'Normal Difficulty Completion Rate (Air Raider)',
    'AirRaiderPlayCount': 'Missions as Air Raider',
    'AlienTrailerKillCount': 'Shield Bearers Defeated',
    'AllClearRatio': 'Completion Rate for All Difficulty Levels',
    'ArmorCount': 'Armor Item Acquisition Rate',
    'BigDragonKillCount': 'Greater Wild Dragons Defeated',
    'BigGiantSpiderKillCount': 'King Spiders Defeated',
    'Carrier1KillCount': 'Transport Ships Destroyed',
    'Carrier2KillCount': 'Large Transport Ships Destroyed',
    'DeiroiKillCount': 'Deroys Defeated',
    'DragonKillCount': 'Dragons Defeated',
    'EasyClearRatio': 'Easy Difficulty Completion Rate',
    'FencerArmor': 'Armor Value (Fencer)',
    'FencerEasyClearRatio': 'Easy Difficulty Completion Rate (Fencer)',
    'FencerHardClearRatio': 'Hard Difficulty Completion Rate (Fencer)',
    'FencerHardestClearRatio': 'Hardest Difficulty Completion Rate (Fencer)',
    'FencerInfernoClearRatio': 'Inferno Difficulty Completion Rate (Fencer)',
    'FencerNormalClearRatio': 'Normal Difficulty Completion Rate (Fencer)',
    'FencerPlayCount': 'Missions as Fencer',
    'FrameCount': 'Gameplay Time',
    'GiantAntKillCount': 'Ant-Type Bugs Defeated',
    'GiantAntQueenKillCount': 'Queens Defeated',
    'GiantBeeKillCount': 'Flying-Type Bugs Defeated',
    'GiantBeeQueenKillCount': 'Death Queens Defeated',
    'GiantSpiderKillCount': 'Spider-Type Bugs Defeated',
    'GuardDamage': 'Guard Damage',
    'HardClearRatio': 'Hard Difficulty Completion Rate',
    'HardestClearRatio': 'Very Hard Difficulty Completion Rate',
    'HealDamage': 'Recovery',
    'HectorKillCount': 'Hectors Defeated',
    'HornetNestKillCount': 'Giant Flying-Type Bug Nests Destroyed',
    'InfernoClearRatio': 'Inferno Difficulty Completion Rate',
    'Monster501KillCount': 'Erginuses Defeated',
    'MotherShip301KillCount': 'Motherships Defeated',
    'MotherShip401KillCount': 'Brains Defeated',
    'NephilaKillCount': 'Retiarii Defeated',
    'NestKillCount': 'Underground Tunnel Exits Destroyed',
    'NormalClearRatio': 'Normal Difficulty Completion Rate',
    'OfflinePlayCount': 'Missions Started',
    'OnlinePlayCount': 'Online Missions Started',
    'PlayCount': 'Games Started',
    'RangerArmor': 'Armor Value (Ranger)',
    'RangerEasyClearRatio': 'Easy Difficulty Completion Rate (Ranger)',
    'RangerHardClearRatio': 'Hard Difficulty Completion Rate (Ranger)',
    'RangerHardestClearRatio': 'Hardest Difficulty Completion Rate (Ranger)',
    'RangerInfernoClearRatio': 'Inferno Difficulty Completion Rate (Ranger)',
    'RangerNormalClearRatio': 'Normal Difficulty Completion Rate (Ranger)',
    'RangerPlayCount': 'Missions as Ranger',
    'RescueCount': 'Rescues',
    'UfoRoboKillCount': 'Argos Defeated',
    'UfoSmall301AceKillCount': 'Red Drones Defeated',
    'UfoSmall301KillCount': 'Flying Drones Defeated',
    'UfoSmall401KillCount': 'Flying Vehicles Defeated',
    'WeaponCount': 'Acquired Weapons',
    'WeaponGetRatio': 'Weapon Acquisition Rate',
    'WingDiverArmor': 'Armor Value (Wing Diver)',
    'WingDiverEasyClearRatio': 'Easy Difficulty Completion Rate (Wing Diver)',
    'WingDiverHardClearRatio': 'Hard Difficulty Completion Rate (Wing Diver)',
    'WingDiverHardestClearRatio': 'Hardest Difficulty Completion Rate (Wing Diver)',
    'WingDiverInfernoClearRatio': 'Inferno Difficulty Completion Rate (Wing Diver)',
    'WingDiverNormalClearRatio': 'Normal Difficulty Completion Rate (Wing Diver)',
    'WingDiverPlayCount': 'Missions as Wing Diver',
    'max_elevation': 'Max Height',
}

def kill_stat_lang_prefix(game) -> str:
    """The languages.json key prefix real Kill Statistics field names are stored under for this
    game - 'EDF6_'/'EDF41_'/'EDF5_'. Games can share an internal Achievement.sgo field NAME while
    meaning something totally different in-game (see EDF41_STATUS_INFO_NAMES' module comment), so
    each game's real names live under their own prefix rather than a shared flat key."""
    if _game_is_edf41(game):
        return 'EDF41_'
    if _game_is_edf5(game):
        return 'EDF5_'
    return 'EDF6_'

def real_field_display_name(key: str, game) -> str:
    """Best available display name for a Kill Statistics field key, as a plain-Python fallback for
    when languages.json's game-prefixed key (see kill_stat_lang_prefix()) isn't present - EDF6's or
    EDF4.1's real, shipped Battle-History label when known (EDF6_STATUS_INFO_NAMES/
    EDF41_STATUS_INFO_NAMES), else humanize_field_key()'s CamelCase/snake_case-aware formatted
    guess. EDF5 has no real-name source yet (own TEXTTABLE not available), always falls through to
    the guess. Never mixes EDF6's and EDF4.1's dicts for the same key - see the DragonKillCount-style
    divergence documented on EDF41_STATUS_INFO_NAMES."""
    if _game_is_edf41(game):
        real = EDF41_STATUS_INFO_NAMES.get(key)
    elif _game_is_edf6(game):
        real = EDF6_STATUS_INFO_NAMES.get(key)
    else:
        real = None
    if real:
        return real
    return humanize_field_key(key)

def compute_edf41_achievement_status(kill_fields: dict) -> list:
    """Evaluate every EDF41_ACHIEVEMENT_EVENTS formula against already-extracted kill_fields
    (from extract_kill_fields(td, EDF41_KILL_FIELDS)). Returns [[id, display_name, unlocked(0/1),
    current_value, threshold, value_type], ...] - same [id, name, flag] prefix shape as
    app.achievement_data so calling code can treat the first 3 columns uniformly; the extra
    trailing fields let the UI show real progress instead of just Yes/No. Read-only by nature -
    EDF4.1 has no separate stored "unlocked" bit, unlock status is always derived from the
    counters themselves, matching how Steam's own SetAchievement calls in AchievementUtility work."""
    results = []
    for eid, name, target_key, op, threshold, vtype in EDF41_ACHIEVEMENT_EVENTS:
        current = kill_fields.get(target_key, 0)
        if op == '>=':
            unlocked = current >= threshold
        elif op == '>':
            unlocked = current > threshold
        else:
            unlocked = False
        results.append([eid, prettify_edf41_achievement_name(name), 1 if unlocked else 0, current, threshold, vtype])
    return results

def get_playtime_offset(game):
    """Return the TROPHY.DAT byte offset of the 60fps playtime frame-count field for `game`."""
    g = str(game or '').upper()
    if g.startswith('EDF5'):
        return 0x150
    if g.startswith('EDF4'):
        return 0x144
    return 0x160

def get_profile_name_offset(game):
    """Return the COMMON.CFG byte offset of the UTF-16LE profile-name field for `game`."""
    g = str(game or '').upper()
    if g.startswith('EDF5'):
        return 0x5000
    if g.startswith('EDF4'):
        return 0x8CC
    return 0x5014

def get_kill_fields_table(game):
    """Return the right kill-stats field table for `game`."""
    g = str(game or '').upper()
    if g.startswith('EDF5'):
        return EDF5_KILL_FIELDS
    if g.startswith('EDF4'):
        return EDF41_KILL_FIELDS
    return KILL_FIELDS

def extract_kill_fields(dat_data, fields_table=None):
    """Extract kill field values from DAT file data as a dict, reading each entry as signed 32-bit LE (or float32)."""
    if fields_table is None:
        fields_table = KILL_FIELDS
    kills = {}
    for entry in fields_table:
        offset, size, key = entry[0], entry[1], entry[2]
        ftype = entry[3] if len(entry) > 3 else 'int'
        if len(dat_data) >= offset + size:
            if ftype == 'float':
                val = struct.unpack_from("<f", dat_data, offset)[0]
            else:
                val = int.from_bytes(dat_data[offset:offset+size], 'little', signed=True)
        else:
            val = 0.0 if ftype == 'float' else 0  # Default if not enough data
        kills[key] = val
    return kills

def write_kill_fields(dat_data: bytearray, kill_fields: dict, fields_table=None) -> None:
    """Inverse of extract_kill_fields: writes each key in kill_fields back into dat_data in place."""
    if fields_table is None:
        fields_table = KILL_FIELDS
    for entry in fields_table:
        offset, size, key = entry[0], entry[1], entry[2]
        ftype = entry[3] if len(entry) > 3 else 'int'
        if key not in kill_fields:
            continue
        if len(dat_data) < offset + size:
            continue
        if ftype == 'float':
            struct.pack_into("<f", dat_data, offset, float(kill_fields[key]))
        else:
            val = int(kill_fields[key])
            val = max(-2147483648, min(2147483647, val))  # Clamp so a bad manual edit can't crash the save
            dat_data[offset:offset+size] = val.to_bytes(size, 'little', signed=True)

# --- *ClearRatio fields: always COMPUTED from Mission Table completion bits, never read as raw
# TROPHY.DAT bytes. ---
# EDF4.1's Battle History percentages were CONFIRMED (2026-09-06) to be calculated live from
# mission-table completion bits, not stored - only 3 stray floats existed anywhere in that whole
# 1024-byte file, nowhere near enough for the ~26 distinct rates needed. All 3 games' Achievement.sgo
# declare the same ~26 "*ClearRatio" AchievementVariable names (1 AllClearRatio + 5 difficulty-only
# + 4 classes x 5 difficulties), identically CamelCase-spelled across EDF4.1/EDF5/EDF6. Re-checking
# EDF6's reconciled byte offsets against a real, played save (2026-09-08 - see SAVE_FORMAT_NOTES.md's
# "clear ratios read 0" section) turned up implausible values at several of them too (e.g. a
# supposed PlayCount reading in the billions) - the whole 91-entry table needs a proper Ghidra RE
# pass to fully re-verify, not yet done. Rather than keep showing unreliable raw bytes for exactly
# the field family with a confirmed compute-don't-read precedent, these are always computed fresh
# from mission_arrays/total_missions - the same inputs update_completion()'s overall-% already uses -
# for all three games uniformly. The KILL_FIELDS-family tables still carry byte offsets for these
# keys (kept for reference/future verification), but extract_kill_fields()'s raw read is always
# overridden by compute_clear_ratios() before display or save - see update_kill_fields() and
# save_save_data().
CLEAR_RATIO_DIFFICULTIES = [('Easy', 0x01), ('Normal', 0x02), ('Hard', 0x04), ('Hardest', 0x08), ('Inferno', 0x10)]
CLEAR_RATIO_CLASSES = ['Ranger', 'WingDiver', 'AirRaider', 'Fencer']  # matches mission_arrays' index order (0-3)

def is_clear_ratio_key(key: str) -> bool:
    """True for any of the 26 computed *ClearRatio field names (AllClearRatio, <Difficulty>ClearRatio,
    <Class><Difficulty>ClearRatio) - see the module comment above compute_clear_ratios()."""
    if key == 'AllClearRatio':
        return True
    if any(key == f'{d}ClearRatio' for d, _ in CLEAR_RATIO_DIFFICULTIES):
        return True
    return any(key == f'{c}{d}ClearRatio' for c in CLEAR_RATIO_CLASSES for d, _ in CLEAR_RATIO_DIFFICULTIES)

def compute_clear_ratios(mission_arrays, total_missions, game) -> dict:
    """Compute all 26 *ClearRatio values live from mission-table completion bits, matching
    update_completion()'s overall-% math exactly (same total_possible = total_missions*20 model).
    EDF4.1 stores these as 0.0-1.0 floats (its AchievementEvent thresholds use '>= 1'); EDF5/EDF6
    store them as 0-10000 ints (their thresholds use e.g. Conquest100's '>= 10000') - scaled
    accordingly. mission_arrays must be the 4 per-class (Ranger/WingDiver/AirRaider/Fencer)
    completion bytearrays extract_mission_arrays()/self.mission_arrays already provides; returns {}
    if that shape isn't met or total_missions is falsy (e.g. no save loaded yet)."""
    if not mission_arrays or len(mission_arrays) < 4 or not total_missions:
        return {}
    is_frac = _game_is_edf41(game)
    def ratio(cleared, possible):
        if possible <= 0:
            return 0.0 if is_frac else 0
        frac = cleared / possible
        return frac if is_frac else int(round(frac * 10000))
    result = {}
    total_cleared_all = 0
    for ci, cls in enumerate(CLEAR_RATIO_CLASSES):
        arr = mission_arrays[ci][:total_missions]
        class_cleared_total = 0
        for dname, bit in CLEAR_RATIO_DIFFICULTIES:
            cleared = sum(1 for b in arr if b & bit)
            result[f'{cls}{dname}ClearRatio'] = ratio(cleared, total_missions)
            class_cleared_total += cleared
        total_cleared_all += class_cleared_total
    for dname, bit in CLEAR_RATIO_DIFFICULTIES:
        cleared = sum(1 for ci in range(4) for b in mission_arrays[ci][:total_missions] if b & bit)
        result[f'{dname}ClearRatio'] = ratio(cleared, total_missions * 4)
    result['AllClearRatio'] = ratio(total_cleared_all, total_missions * 20)
    return result

def format_clear_ratio_display(key: str, val, game) -> str:
    """Render one compute_clear_ratios() value as a human-readable percentage string, so the Kill
    Statistics panel never shows a bare '10000' that a user could easily misread as a raw count of
    10,000 kills rather than 100.00% - EDF5/EDF6's int scale is 0-10000 (100 units = 1%), EDF4.1's
    is a 0.0-1.0 float; both become e.g. '58.50%'. Only meaningful for *ClearRatio keys - callers
    should check is_clear_ratio_key(key) first."""
    try:
        pct = float(val) * 100.0 if _game_is_edf41(game) else float(val) / 100.0
    except (TypeError, ValueError):
        return str(val)
    return f"{pct:.2f}%"

# DEFP_M00.MST base offsets for the four class mission tables (0x200 bytes each), per player slot.
MISSION_TABLE_BASE_OFFSETS = {1: 0x1C, 2: 0xA1C}

# EDF5's MST header is 0x20 bytes (vs EDF6's 0x14), shifting the mission table body +0xC.
EDF5_MISSION_TABLE_BASE_OFFSETS = {1: 0x1C + 0xC, 2: 0xA1C + 0xC}

# EDF4.1's MST header shifts the mission table body +0x4.
EDF41_MISSION_TABLE_BASE_OFFSETS = {1: 0x1C + 0x4, 2: 0xA1C + 0x4}

def get_mission_table_base_offsets(game):
    """Return the right {player_slot: base_offset} dict for `game`."""
    if _game_is_edf5(game):
        return EDF5_MISSION_TABLE_BASE_OFFSETS
    if _game_is_edf41(game):
        return EDF41_MISSION_TABLE_BASE_OFFSETS
    return MISSION_TABLE_BASE_OFFSETS

def _extract_mission_arrays(mst_data, player_slot=1, game=None):
    """Slice mst_data into 4 per-class mission-completion bytearrays for one player slot."""
    base = get_mission_table_base_offsets(game).get(player_slot, 0x1C)
    if len(mst_data) < base + 0x800:
        return None
    arrays = [
        bytearray(mst_data[base:base+0x200]),            # Ranger
        bytearray(mst_data[base+0x200:base+0x400]),      # Wing Diver
        bytearray(mst_data[base+0x400:base+0x600]),      # Air Raider
        bytearray(mst_data[base+0x600:base+0x800]),      # Fencer
    ]
    for arr in arrays:
        for i in range(len(arr)):
            arr[i] &= 0x1F  # Mask to lower 5 bits for difficulties
    return arrays

# Strips a games_metadata key down to its game family (drops trailing " Online"/" Offline"/" DLC<N>").
FAMILY_SUFFIX_RE = re.compile(r'(?: (?:Online|Offline))?(?: DLC\d+)?$')

def load_all_mission_tables(app, folder):
    """Load every present game/DLC's .MST mission table in `folder` into app.mission_table_cache, keyed by games_metadata key, so switching Game/DLC is an instant in-memory swap; also picks up modded .MST files via _register_modded_mission_tables()."""
    # Scope to the current game's family: keeps EDF5/EDF6/EDF4.1 (same MST filename, separate folders) from colliding, while aliasing Online/Offline siblings to one shared cache entry.
    current_game_family = FAMILY_SUFFIX_RE.sub('', getattr(app, 'current_game', 'EDF6') or 'EDF6')
    app.mission_table_cache = {}
    seen_files = set()
    path_to_key = {}  # mst_path -> the game_key first cached under it, for the aliasing below
    for game_key, meta in app.games_metadata.items():
        if is_synthetic_pack_key(game_key):
            continue  # Runtime-added "Modded: ..." entries are claimed only by _register_modded_mission_tables()
        if meta.get('coming_soon', False):
            continue
        if FAMILY_SUFFIX_RE.sub('', game_key) != current_game_family:
            continue
        mst_filename = meta.get('missiontable')
        if not mst_filename or mst_filename == 'Unknown.MST':
            continue
        mst_path = os.path.join(folder, mst_filename)
        if mst_path in seen_files:
            # Same physical .MST already parsed under a sibling key - alias this key to that entry.
            owner_key = path_to_key.get(mst_path)
            if owner_key is not None:
                app.mission_table_cache[game_key] = app.mission_table_cache[owner_key]
            continue
        if not os.path.exists(mst_path):
            continue
        try:
            mst_data = _load_game_file(app, mst_path)
        except Exception as e:
            print(f"Warning: failed to load {mst_filename} for {game_key}: {e}")
            continue
        seen_files.add(mst_path)
        path_to_key[mst_path] = game_key
        entry = {'mst_file': mst_path, 'slots': {}}
        slot1 = _extract_mission_arrays(mst_data, 1, game=game_key)
        if slot1 is not None:
            entry['slots'][1] = slot1
        app.mission_table_cache[game_key] = entry

    _register_modded_mission_tables(app, folder, seen_files)


def _read_modded_mission_count(app, mst_path):
    """Best-effort lookup of a modded mission pack's real mission count, from config.json's modded_mission_totals or a JSON sidecar, else 512 (the safe per-class upper bound)."""
    filename = os.path.basename(mst_path)
    try:
        totals = getattr(app, 'config_data', {}).get('modded_mission_totals') or {}
        count = totals.get(filename)
        if isinstance(count, int) and 0 < count <= 512:
            return count
    except Exception as e:
        print(f"Warning: couldn't read modded_mission_totals from config for {mst_path}: {e}")
    try:
        json_path = os.path.splitext(mst_path)[0] + '.json'
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                sidecar = json.load(f)
            count = sidecar.get('total_missions', sidecar.get('mission_count'))
            if isinstance(count, int) and 0 < count <= 512:
                return count
    except Exception as e:
        print(f"Warning: couldn't read mission count sidecar for {mst_path}: {e}")
    return 512


# Prefixes a runtime-synthesized games_metadata key can carry: "Modded: " for mod-added .MST files, "EDF5 Official Pack (unidentified, " for real-but-unpinned numbered mode slots.
SYNTHETIC_PACK_PREFIXES = ('Modded: ', 'EDF5 Official Pack (unidentified, ')

def is_synthetic_pack_key(key) -> bool:
    key = str(key or '')
    return any(key.startswith(p) for p in SYNTHETIC_PACK_PREFIXES)

def _register_modded_mission_tables(app, folder, seen_files):
    """Pick up any *.MST in `folder` not already claimed by a known vanilla/DLC filename in
    games_metadata (see load_all_mission_tables above) - modded mission packs (e.g. AUK233's
    mppp plugin, which lets mod authors add a 3rd+ mission pack) can be named anything, so
    there's no fixed filename to hardcode ahead of time the way DEFP_M00.MST/DEFP_DLC1.MST/
    DEFP_DLC2.MST are. Each one found gets a synthetic games_metadata entry (keyed
    "Modded: <filename>") registered at runtime, so it's treated exactly like a built-in
    game/DLC everywhere else in the app (MST dropdown, game selector, pagination, Save) -
    total_missions defaults to the safe 512 upper bound unless _read_modded_mission_count()
    finds a more precise count (see that function's docstring)."""
    try:
        candidates = sorted(set(glob.glob(os.path.join(folder, '*.MST')) + glob.glob(os.path.join(folder, '*.mst'))))
    except Exception as e:
        print(f"Warning: modded .MST scan failed for {folder}: {e}")
        return
    for mst_path in candidates:
        if mst_path in seen_files:
            continue
        try:
            mst_data = _load_game_file(app, mst_path)
        except Exception as e:
            print(f"Warning: failed to load modded mission table {mst_path}: {e}")
            continue
        slot1 = _extract_mission_arrays(mst_data, 1, game=getattr(app, 'current_game', 'EDF6'))
        if slot1 is None:
            continue  # Too small to hold even one class's data - not a table this tool understands
        seen_files.add(mst_path)
        base_name = os.path.splitext(os.path.basename(mst_path))[0]
        # "DEFP_M01.MST".."DEFP_M05.MST" are official numbered mode slots (per Ghidra RE), not modder files.
        numbered_slot_match = re.match(r'^(.+)_M(\d{2})$', base_name, re.IGNORECASE)
        if numbered_slot_match:
            game_key = f"EDF5 Official Pack (unidentified, {base_name})"
        else:
            game_key = f"Modded: {base_name}"
        app.games_metadata[game_key] = {
            'total_missions': _read_modded_mission_count(app, mst_path),
            'missionlist': None,  # no translated mission names available - falls back to "Mission N"
            'missiontable': os.path.basename(mst_path),
            'auto_unlock_missions': [],
        }
        app.mission_table_cache[game_key] = {'mst_file': mst_path, 'slots': {1: slot1}}

def save_mission_arrays_for_slot(mst_data, mission_arrays, player_slot=1, game=None):
    """Write mission_arrays back into mst_data at the given player slot's offset; returns False if mst_data is too small."""
    base = get_mission_table_base_offsets(game).get(player_slot, 0x1C)
    if len(mst_data) < base + 0x800:
        return False
    mst_data[base:base+0x200] = mission_arrays[0]
    mst_data[base+0x200:base+0x400] = mission_arrays[1]
    mst_data[base+0x400:base+0x600] = mission_arrays[2]
    mst_data[base+0x600:base+0x800] = mission_arrays[3]
    return True

# Color customization region (0x15C-0x19DC in MAIN.GST): 4 classes x 4 tiers x (Primary/Secondary) groups.
COLOR_CLASSES = ["Ranger", "Wingdiver", "Air Raider", "Fencer"]
COLOR_TIERS = ["Soldier", "Civilian", "Devastation", "Up-and-Coming"]
COLOR_REGION_BASE = 0x15C
COLOR_GROUP_SIZE = 196  # 12 * 16 + 4
COLOR_PALETTES_PER_GROUP = 12

PLAYER2_COLOR_REGION_BASE = 0x3FBC  # Player 2's color region, confirmed via Ghidra + real co-op save

# Game-aware color region: EDF5 shifts base +0xC with only 2 real tiers/class; EDF4.1's base and
# tier count are unconfirmed, so get_color_region_base() returns None there (load/save no-op).
def get_color_tiers(game):
    """Return the 4-entry tier label list for `game`'s color-customization UI (EDF4.1's extra slots are labeled N/A - it has no unused-but-present storage like EDF5/6)."""
    g = str(game or '').upper()
    if g.startswith('EDF5'):
        return ["Soldier", "Civilian", "Unused (Devastation) Slot", "Unused (Up-and-Coming) Slot"]
    if g.startswith('EDF4'):
        return ["Soldier", "No Skins - N/A", "No Skins - N/A", "No Skins - N/A"]
    return COLOR_TIERS

def get_color_region_base(game, player: int = 1):
    """Return the color-region base offset in decrypted MAIN.GST for `game`/`player` (EDF4.1: 0x10C for P1, +0x101C stride for P2, both confirmed via real HSV-value matching)."""
    g = str(game or '').upper()
    if g.startswith('EDF4'):
        base = 0x10C
        if player != 1:
            base += 0x101C
        return base
    base = COLOR_REGION_BASE + (0xC if g.startswith('EDF5') else 0)
    if player != 1:
        base += 0x3E60  # PLAYER2_COLOR_BLOCK_SIZE stride - see PLAYER2_COLOR_REGION_BASE above
    return base

def color_group_offset(class_idx: int, tier_idx: int, is_secondary: bool, player: int = 1, game=None) -> int:
    """Compute the byte offset of one (class, tier, Primary/Secondary) color group (EDF4.1 uses a 2-group-per-class stride with no tier dimension, so tier_idx != 0 returns None)."""
    if game is not None:
        base = get_color_region_base(game, player)
        if base is None:
            return None
        if _game_is_edf41(game):
            if tier_idx != 0:
                return None
            group_index = class_idx * 2 + (1 if is_secondary else 0)
            return base + group_index * COLOR_GROUP_SIZE
    else:
        base = COLOR_REGION_BASE if player == 1 else PLAYER2_COLOR_REGION_BASE
    group_index = (class_idx * len(COLOR_TIERS) + tier_idx) * 2 + (1 if is_secondary else 0)
    return base + group_index * COLOR_GROUP_SIZE

def load_color_group(data, class_idx: int, tier_idx: int, is_secondary: bool, player: int = 1, game=None):
    """Return (palettes, swatch_id) for one color group; palettes is 12 (r,g,b,a) float tuples, swatch_id is the equipped index. All-default if the offset isn't confirmed."""
    off = color_group_offset(class_idx, tier_idx, is_secondary, player, game)
    if off is None or len(data) < off + COLOR_GROUP_SIZE:
        return [(0.0, 0.0, 0.0, 1.0)] * COLOR_PALETTES_PER_GROUP, 0
    palettes = []
    for i in range(COLOR_PALETTES_PER_GROUP):
        palettes.append(struct.unpack_from("<4f", data, off + i * 16))
    swatch_id = struct.unpack_from("<I", data, off + 192)[0]
    return palettes, swatch_id

def save_color_group(data: bytearray, class_idx: int, tier_idx: int, is_secondary: bool, palettes, swatch_id: int, player: int = 1, game=None) -> bool:
    off = color_group_offset(class_idx, tier_idx, is_secondary, player, game)
    if off is None or len(data) < off + COLOR_GROUP_SIZE:
        return False
    for i, rgba in enumerate(palettes[:COLOR_PALETTES_PER_GROUP]):
        struct.pack_into("<4f", data, off + i * 16, *rgba)
    struct.pack_into("<I", data, off + 192, int(swatch_id))
    return True

def load_all_color_groups(data, player: int = 1, game=None):
    """Return {(class_idx, tier_idx, is_secondary): (palettes, swatch_id)} for all 32 groups of the given player, to populate the color-customization UI's in-memory cache."""
    groups = {}
    for ci in range(len(COLOR_CLASSES)):
        for ti in range(len(COLOR_TIERS)):
            for sec in (False, True):
                groups[(ci, ti, sec)] = load_color_group(data, ci, ti, sec, player, game)
    return groups

def save_all_color_groups(data: bytearray, groups, player: int = 1, game=None) -> None:
    for (ci, ti, sec), (palettes, swatch_id) in groups.items():
        save_color_group(data, ci, ti, sec, palettes, swatch_id, player, game)

# Player 2's raw weapon/loadout/color block - EXPERIMENTAL, field layout not confirmed, treat as raw bytes only.
PLAYER2_COLOR_BLOCK_OFFSET = 0x3E98
PLAYER2_COLOR_BLOCK_SIZE = 0x3E60  # matches the constructor loop's per-player stride
def read_player2_color_block(data) -> bytes:
    """Return the raw bytes of the hypothesized Player 2 color/loadout block from decrypted MAIN.GST data, or b'' if too small."""
    end = PLAYER2_COLOR_BLOCK_OFFSET + PLAYER2_COLOR_BLOCK_SIZE
    if len(data) < end:
        return b''
    return bytes(data[PLAYER2_COLOR_BLOCK_OFFSET:end])

def write_player2_color_block(data: bytearray, block: bytes) -> bool:
    """Write raw bytes back into the Player 2 color/loadout block; block must be exactly PLAYER2_COLOR_BLOCK_SIZE bytes, else no-op."""
    end = PLAYER2_COLOR_BLOCK_OFFSET + PLAYER2_COLOR_BLOCK_SIZE
    if len(data) < end or len(block) != PLAYER2_COLOR_BLOCK_SIZE:
        return False
    data[PLAYER2_COLOR_BLOCK_OFFSET:end] = block
    return True

def _load_game_file(app, path: str) -> bytes:
    """Game-aware load: EDF4.1 uses a static key; EDF5/6 use dynamic AES-CTR keyed by game."""
    game = getattr(app, 'current_game', 'EDF6')
    if game.startswith('EDF4.1') or game.startswith('EDF4'):
        return load_save_edf41(path)
    # EDF5 and EDF6
    return load_save(path, game=game)

# Safety-net backups: name and retention for _backup_before_overwrite(). Kept per-original-filename
# so a multi-file save (MAIN.GST + TROPHY.DAT + MST + CFG in one click) doesn't crowd out any one
# file's history with another's backups.
EDITOR_BACKUP_DIRNAME = "EDFSaveEditor_Backups"
EDITOR_BACKUP_KEEP_PER_FILE = 10

def _backup_before_overwrite(path: str) -> None:
    """Best-effort safety net: before overwriting an existing save file, copy its current on-disk
    bytes into a per-folder EDFSaveEditor_Backups subfolder, timestamped, keeping only the newest
    EDITOR_BACKUP_KEEP_PER_FILE copies per original filename (oldest pruned). Never raises - a
    backup failure (permissions, read-only media, disk full) must not block the actual save, since
    losing the user's just-made edits would be worse than a missing backup; failures are logged
    instead. No-op if there's nothing on disk yet to protect (a brand-new file)."""
    try:
        if not path or not os.path.isfile(path):
            return
        folder = os.path.dirname(path)
        backup_dir = os.path.join(folder, EDITOR_BACKUP_DIRNAME)
        os.makedirs(backup_dir, exist_ok=True)
        base = os.path.basename(path)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_dir, f"{base}.{stamp}.bak")
        n = 1
        while os.path.exists(dest):  # multiple files saved within the same second - don't clobber
            dest = os.path.join(backup_dir, f"{base}.{stamp}_{n}.bak")
            n += 1
        shutil.copy2(path, dest)
        prefix = base + "."
        existing = sorted(
            (f for f in os.listdir(backup_dir) if f.startswith(prefix) and f.endswith(".bak")),
            reverse=True,  # timestamp-prefixed names sort newest-first lexicographically
        )
        for stale in existing[EDITOR_BACKUP_KEEP_PER_FILE:]:
            try:
                os.remove(os.path.join(backup_dir, stale))
            except OSError:
                pass
    except Exception as e:
        print(f"[WARN] Could not back up {path} before saving: {e}")

def _save_game_file(app, path: str, data: bytearray):
    """Game-aware save: EDF4.1 uses a static key; EDF5/6 use dynamic AES-CTR keyed by game.
    Always backs up the file's current on-disk contents first (see _backup_before_overwrite) -
    this is the single low-level write chokepoint every save path (main file, MST, CFG, color
    block import, etc.) funnels through, so hooking backup here covers all of them at once."""
    _backup_before_overwrite(path)
    game = getattr(app, 'current_game', 'EDF6')
    if game.startswith('EDF4.1') or game.startswith('EDF4'):
        return save_save_edf41(path, data)
    return save_save(path, data, game=game)

def export_player2_color_block(app, out_path: str) -> bool:
    """Dump the hypothesized Player 2 color/loadout block from app.current_file to out_path as raw bytes, for inspection in ImHex or similar."""
    if not getattr(app, 'current_file', None):
        return False
    data = _load_game_file(app, app.current_file)
    block = read_player2_color_block(data)
    if not block:
        return False
    with open(out_path, 'wb') as f:
        f.write(block)
    return True

def import_player2_color_block(app, in_path: str) -> bool:
    """Read raw bytes from in_path and write them into the hypothesized Player 2
    color/loadout block of app.current_file, re-encrypting and saving in place.
    EXPERIMENTAL - back up your save before using this. Returns True on success."""
    if not getattr(app, 'current_file', None):
        return False
    with open(in_path, 'rb') as f:
        block = f.read()
    if len(block) != PLAYER2_COLOR_BLOCK_SIZE:
        print(f"Warning: expected {PLAYER2_COLOR_BLOCK_SIZE} bytes, got {len(block)} - refusing to write")
        return False
    data = bytearray(_load_game_file(app, app.current_file))
    if not write_player2_color_block(data, block):
        return False
    _save_game_file(app, app.current_file, data)
    return True

# EDF5-only COMMON.CFG keyboard-keybind read/write (4 per-class groups, 1020 bytes apart).
EDF5_KEYBIND_GROUP_BASES = {
    "Ranger": 0x00A4,
    "Wing Diver": 0x04A0,
    "Air Raider": 0x089C,  # Inferred via elimination + stride math, not directly rebind-tested
    "Fencer": 0x0C98,
}
EDF5_KEYBIND_GROUP_SIZE = 0x03FC  # 255 slots x 4 bytes = 1020 bytes

PLAYER2_KEYBIND_OFFSET = 0x27F0  # Player 2 keybind offset, confirmed via signature search across all 4 class groups

# Per-class soldier action lists: (action_name, slot_index, confirmed_by_direct_diff).
EDF5_SOLDIER_ACTIONS = {
    "Ranger": [  # All 7 confirmed against a real in-game Key Config screenshot
        ("Attack", 6, True),
        ("Zoom/Activate", 7, True),
        ("Jump", 8, True),
        ("Switch Weapons", 9, True),
        ("Reload", 10, True),
        ("Dash", 11, True),
        ("Summon Vehicle", 12, True),
    ],
    "Wing Diver": [  # All 6 confirmed against a real in-game screenshot; a likely 7th (Summon Vehicle) slot 12 is unconfirmed and omitted
        ("Attack", 6, True),
        ("Zoom/Activate", 7, True),
        ("Jump", 8, True),
        ("Switch Weapons", 9, True),
        ("Reload", 10, True),
        ("Boost", 11, True),
    ],
    "Air Raider": [  # All 6 confirmed against a real in-game screenshot; slot 11 is an unused leftover, omitted
        ("Attack", 6, True),
        ("Zoom/Activate", 7, True),
        ("Jump", 8, True),
        ("Switch Weapons", 9, True),
        ("Reload", 10, True),
        ("Summon Vehicle", 12, True),
    ],
    "Fencer": [  # All 8 confirmed against a real in-game screenshot
        ("Attack - R.Hand", 13, True),
        ("Attack - L.Hand", 14, True),
        ("Use - R.Hand", 15, True),
        ("Use - L.Hand", 16, True),
        ("Jump", 17, True),
        ("Switch Weapons", 18, True),
        ("Reload", 19, True),
        ("Shield Reload", 20, True),
    ],
}

# EDF6 keyboard bindings - all 4 classes confirmed via rebind-and-diff testing; reuses EDF5's group bases with a per-class slot shift.
EDF6_SOLDIER_ACTIONS = {
    "Ranger": [
        ("Attack", 8, True),
        ("Zoom/Activate", 9, True),
        ("Jump", 10, True),
        ("Switch Weapons", 11, True),
        ("Reload", 12, True),
        ("Sprint", 13, True),
        ("Call Vehicles", 14, True),
        ("Use Backpack Tools", 15, True),
    ],
    "Wing Diver": [
        ("Attack", 8, True),
        ("Zoom/Activate", 9, True),
        ("Jump", 10, True),
        ("Switch Weapons", 11, True),
        ("Reload", 12, True),
        ("Boost", 13, True),
        ("Use Independently Operated Equipment", 15, True),  # slot 14 is real but inert, no UI row
    ],
    "Air Raider": [
        ("Attack", 8, True),
        ("Zoom/Activate", 9, True),
        ("Jump", 10, True),
        ("Switch Weapons", 11, True),
        ("Reload", 12, True),
        ("Call Vehicles", 14, True),  # slot 13 is real but inert, no UI row
        ("Use Backpack Tools", 15, True),
    ],
    "Fencer": [
        ("Attack - Right Hand", 16, True),
        ("Attack - Left Hand", 17, True),
        ("Use Equipment - Right Hand", 18, True),
        ("Use Equipment - Left Hand", 19, True),
        ("Jump", 20, True),
        ("Switch Weapons", 21, True),
        ("Reload", 22, True),
        ("Reload Shield", 23, True),
    ],
}

# EDF6 "Common Controls" keyboard bindings, confirmed via real save diff: 12 actions at slots -4..7 (a +2 shift from EDF5's own Common numbering), mirrored identically into all 4 soldier-class groups.
EDF6_COMMON_ACTIONS = {
    "Common": [
        ("Move - Front", -4, True),
        ("Move - Back", -3, True),
        ("Move - Left", -2, True),
        ("Move - Right", -1, True),
        ("Board / Rescue", 0, True),
        ("Location Marking", 1, True),
        ("Chat Window", 2, True),
        ("Canned Text Shortcut", 3, True),
        ("Weapon Shortcut 1", 4, True),
        ("Weapon Shortcut 2", 5, True),
        ("Weapon Shortcut 3", 6, True),
        ("Voice Chat", 7, True),
    ],
}

# EDF6's "Vehicle (B)" menu category is EDF5's "Drive" under a new display name. All EDF6 vehicle categories confirmed via brute-force scans against real save diffs/screenshots.
EDF6_VEHICLE_ACTIONS = {
    "Drive": [
        ("Accelerate", 24, True),
        ("Brake/Back", 25, True),
        ("Handbrake", 26, True),
        ("Attack 1", 27, True),
        ("Attack 2", 51, True),
        ("Horn", 28, True),
    ],
    "Tanks": [
        ("Attack 1", 29, True),
        ("Attack 2", 30, True),
        ("Horn", 31, True),
    ],
    "Heli": [
        ("Attack 1", 48, True),
        ("Attack 2", 49, True),
        ("Fly", 50, True),
    ],
    "Combat": [
        ("Attack - Right Hand", 32, True),
        ("Attack - Left Hand", 33, True),
        ("Attack - Right Shoulder", 34, True),
        ("Attack - Left Shoulder", 35, True),
        ("Jump", 36, True),
    ],
    "Barga": [
        ("Punch - Right Hand", 37, True),
        ("Punch - Left Hand", 38, True),
        ("Stamp - Right Foot", 39, True),
        ("Stamp - Left Foot", 40, True),
        ("Special Pose", 41, True),
        ("Special Attacks", 42, True),
    ],
    "Depth": [
        ("Bombard - Right", 43, True),
        ("Bombard - Left", 44, True),
        ("Gatling", 45, True),
        ("Emergency Avoidance", 46, True),
        ("Jump", 47, True),
    ],
}

EDF6_KEYCONFIG_CATEGORIES = ["Common"] + list(EDF6_SOLDIER_ACTIONS) + list(EDF6_VEHICLE_ACTIONS)

# EDF4.1's keyconfig menu has a different shape than EDF5/6 (7 categories, not Common+4-soldier+6-vehicle) - not wired to a byte offset/UI yet, kept as reference.

# EDF4.1 keyconfig byte offsets, confirmed via before/after COMMON.CFG diffs and cross-checked with Ghidra's key-name resolver.
EDF41_CONTROLLER_BUTTON_NAMES = {
    0: "Not Assigned",
    1: "A button", 2: "B button", 3: "X button", 4: "Y button",
    5: "Left trigger", 6: "Right trigger", 7: "LB", 8: "RB",
    9: "Left stick button", 10: "Right stick button",
}

# Tool's own cosmetic PS4 label overlay for EDF4.1 (the game itself has no native PS4 label mode) - safe because Xbox/PS4 pads share the same physical button layout, so it's a pure position-for-position rename of the same raw values.
EDF41_CONTROLLER_BUTTON_NAMES_PS4 = {
    0: "Not Assigned",
    1: "× button", 2: "○ button", 3: "□ button", 4: "△ button",
    5: "L2", 6: "R2", 7: "L1", 8: "R1",
    9: "Left stick button", 10: "Right stick button",
}
EDF41_CONTROLLER_BUTTON_TABLES = {
    "xbox": EDF41_CONTROLLER_BUTTON_NAMES,
    "ps4": EDF41_CONTROLLER_BUTTON_NAMES_PS4,
    # No "switch" entry - EDF4.1 never shipped on Switch, falls back to the Xbox/generic table.
}

# Confirmed via before/after diffs against the real "2PGame Settings" screenshot; byte order matches on-screen top-to-bottom order directly, no rotation.
EDF41_CONTROLLER_SOLDER_ACTIONS = [
    "Attack", "Zoom/Activate", "Jump", "Switch Weapons",
    "Reload", "Vehicle/Rescue", "Spot", "Chat Shortcuts",
]
# Confirmed via a direct screenshot search matching 10 real button values to their raw ints in COMMON.CFG.
EDF41_CONTROLLER_FENCER_ACTIONS = [
    "Attack - R. Hand", "Attack - L. Hand", "Use - R. Hand", "Use - L. Hand",
    "Jump", "Switch Weapons", "Reload", "Vehicle/Rescue",
    "Location Marking", "Chat Shortcuts",
]

# offset -> (action list, "direct" or the real rotation permutation if not direct order). Player 1's Solder block uniquely rotates Attack/Jump/Spot one slot from display order; Player 2's does not.
EDF41_CONTROLLER_SOLDER_ACTIONS_P1_ORDER = [
    "Spot", "Zoom/Activate", "Attack", "Switch Weapons",
    "Reload", "Vehicle/Rescue", "Jump", "Chat Shortcuts",
]
EDF41_CONTROLLER_KEYCONFIG_OFFSETS = {
    # player -> {category: (COMMON.CFG offset, action-list-in-real-storage-order)}
    1: {
        "Solder": (0x34, EDF41_CONTROLLER_SOLDER_ACTIONS_P1_ORDER),
        "Fencer": (0x80, EDF41_CONTROLLER_FENCER_ACTIONS),
    },
    2: {
        "Solder": (0x48C, EDF41_CONTROLLER_SOLDER_ACTIONS),
        "Fencer": (0x4D8, EDF41_CONTROLLER_FENCER_ACTIONS),
    },
}

# Real key-code table, confirmed via GhidraMCP decompilation of the game's own key-ID switch statement (not DirectInput/VK codes - a fully custom enum).
EDF41_KEYBOARD_KEY_NAMES = {
    0: "A", 1: "B", 2: "C", 3: "D", 4: "E", 5: "F", 6: "G", 7: "H", 8: "I", 9: "J",
    10: "K", 11: "L", 12: "M", 13: "N", 14: "O", 15: "P", 16: "Q", 17: "R", 18: "S", 19: "T",
    20: "U", 21: "V", 22: "W", 23: "X", 24: "Y", 25: "Z",
    26: "0", 27: "1", 28: "2", 29: "3", 30: "4", 31: "5", 32: "6", 33: "7", 34: "8", 35: "9",
    36: "Num0", 37: "Num1", 38: "Num2", 39: "Num3", 40: "Num4",
    41: "Num5", 42: "Num6", 43: "Num7", 44: "Num8", 45: "Num9",
    46: "F1", 47: "F2", 48: "F3", 49: "F4", 50: "F5", 51: "F6",
    52: "F7", 53: "F8", 54: "F9", 55: "F10", 56: "F11", 57: "F12",
    58: "Hyphen", 59: "Caret", 60: "Yen", 61: "At", 62: "Semicolon", 63: "Colon",
    64: "BracketsL", 65: "BracketsR", 66: "Comma", 67: "Period",
    68: "ShiftL", 69: "ShiftR", 70: "ControlL", 71: "ControlR", 72: "AltL", 73: "AltR",
    74: "WinL", 75: "WinR", 76: "Up", 77: "Down", 78: "Left", 79: "Right",
    80: "Return", 81: "Space", 82: "BackSpace", 83: "Tab", 84: "Insert", 85: "Delete",
    86: "Home", 87: "End", 88: "PageDown", 89: "PageUp", 90: "Help", 91: "Escape",
    92: "Print", 93: "Pause", 94: "NumLock", 95: "Multi", 96: "Add", 97: "Separator",
    98: "Subtract", 99: "Decimal", 100: "Divide", 101: "Sleep", 102: "Kana",
}
EDF41_KEYBOARD_RAW_OFFSET = 0xF  # raw_stored_byte = table_index + 0xF

# EDF4.1 mouse-button raw values, confirmed in-game; sits below EDF41_KEYBOARD_RAW_OFFSET's valid range and uses its own numbering, not EDF5's EDF5_MOUSE_TABLE.
EDF41_MOUSE_TABLE = {
    11: "MouseL",
    12: "MouseM",
    13: "MouseR",
    14: "MouseWheel",
}
_EDF41_MOUSE_NAME_TO_RAW = {name: raw for raw, name in EDF41_MOUSE_TABLE.items()}

def edf41_keyboard_key_name(raw_value: int) -> str:
    """Raw COMMON.CFG byte value -> display key or mouse-button name, or '' if unrecognized."""
    if raw_value in EDF41_MOUSE_TABLE:
        return EDF41_MOUSE_TABLE[raw_value]
    return EDF41_KEYBOARD_KEY_NAMES.get(raw_value - EDF41_KEYBOARD_RAW_OFFSET, "")

def edf41_keyboard_raw_value(key_name: str):
    """Inverse of edf41_keyboard_key_name(): display name -> raw byte value to store, or None."""
    if key_name in _EDF41_MOUSE_NAME_TO_RAW:
        return _EDF41_MOUSE_NAME_TO_RAW[key_name]
    for idx, name in EDF41_KEYBOARD_KEY_NAMES.items():
        if name == key_name:
            return idx + EDF41_KEYBOARD_RAW_OFFSET
    return None

# Confirmed via a real before/after diff. In real STORAGE order, not display order - Chat Shortcuts/Chat Window are swapped relative to the on-screen layout.
EDF41_KEYBOARD_SOLDER_ACTIONS = [
    "Move - Front", "Move - Back", "Move - Left", "Move - Right",
    "Rescue/Ride", "Spot", "Chat Shortcuts", "Chat Window",
    "Weapon Shortcut1", "Weapon Shortcut2", "Weapon Shortcut3",
]

# Ranger KB&M combat actions, confirmed via before/after diff; own category (byte-contiguous with, but organizationally separate from, Common Controls).
EDF41_KEYBOARD_RANGER_ACTIONS = ["Attack", "Zoom/Start up", "Jump", "Switch Weapons", "Reload"]

# Fencer KB&M actions, confirmed via before/after diff; storage order matches display order.
EDF41_KEYBOARD_FENCER_ACTIONS = [
    "Attack - R. Hand", "Attack - L. Hand", "Use - R. Hand", "Use - L. Hand",
    "Jump", "Switch Weapons", "Reload",
]

# Drive vehicle KB&M actions, confirmed via before/after diff; plain display order.
EDF41_KEYBOARD_DRIVE_ACTIONS = ["Attack1", "Attack2", "Hand brake"]

# Begarta vehicle KB&M actions, confirmed via before/after diff; storage order swaps L/R relative to on-screen display.
EDF41_KEYBOARD_BEGARTA_ACTIONS = [
    "Attack - L. Hand", "Attack - R. Hand", "Attack - L. Shldr", "Attack - R. Shldr", "Jump",
]

# Depth Crower vehicle KB&M actions, confirmed via before/after diff; storage order is the full reverse of the first 4 display-order actions.
EDF41_KEYBOARD_DEPTH_ACTIONS = [
    "Avoidance", "Gatling", "Attack - Left", "Attack - Right", "Jump",
]

# Balam vehicle KB&M actions, confirmed via before/after diff; same full-reverse storage order as Depth Crower.
EDF41_KEYBOARD_BALAM_ACTIONS = [
    "Attack - L. Stomp", "Attack - R. Stomp", "Attack - L. Hand", "Attack - R. Hand",
    "Special Pose", "Sub Weapon",
]

# Heli vehicle KB&M actions, confirmed via before/after diff; plain display order.
EDF41_KEYBOARD_HELI_ACTIONS = ["Attack1", "Attack2", "Flight"]

EDF41_KEYBOARD_KEYCONFIG_OFFSETS = {
    # player -> {category: (COMMON.CFG offset, action-list-in-real-storage-order)}. Player 2's
    # KB&M blocks are still unmapped; do not assume a constant shift from Player 1's offsets.
    1: {
        "Solder": (0xA8, EDF41_KEYBOARD_SOLDER_ACTIONS),
        "Ranger": (0xD4, EDF41_KEYBOARD_RANGER_ACTIONS),
        "Fencer": (0xE8, EDF41_KEYBOARD_FENCER_ACTIONS),
        "Drive": (0x104, EDF41_KEYBOARD_DRIVE_ACTIONS),
        "Begarta": (0x110, EDF41_KEYBOARD_BEGARTA_ACTIONS),
        "Depth Crower": (0x124, EDF41_KEYBOARD_DEPTH_ACTIONS),
        "Balam": (0x138, EDF41_KEYBOARD_BALAM_ACTIONS),
        "Heli": (0x150, EDF41_KEYBOARD_HELI_ACTIONS),
    },
}

# EDF4.1's vehicle submenu categories are folded directly into EDF41_KEYBOARD_CATEGORIES below; kept as an empty list for any future not-yet-confirmed category.
EDF41_VEHICLE_CATEGORY_NAMES = []

# Full EDF4.1 Keyboard-mode category list for the dropdown, in real in-game menu display order (not storage-offset order).
EDF41_KEYBOARD_CATEGORIES = ["Solder", "Ranger", "Fencer", "Drive", "Heli", "Begarta", "Depth Crower", "Balam"] + EDF41_VEHICLE_CATEGORY_NAMES

# EDF4.1 Key Config access layer: kept separate from EDF5/6's generic machinery since EDF4.1's per-player action order/offsets don't fit that shared-list-plus-shift model.

def get_keyconfig_actions_edf41(category: str, mode: str = "Keyboard", player: int = 1):
    """Return (action_name, index, confirmed) tuples for `category` in `mode` ("Keyboard"/"Controller") for `player`; Player 2 Keyboard mode always returns []."""
    if mode == "Controller":
        entry = EDF41_CONTROLLER_KEYCONFIG_OFFSETS.get(player, {}).get(category)
    else:
        if player != 1:
            return []
        entry = EDF41_KEYBOARD_KEYCONFIG_OFFSETS.get(1, {}).get(category)
    if not entry:
        return []
    _base, actions = entry
    return [(name, idx, True) for idx, name in enumerate(actions)]

def read_edf41_controller_keybind(data, category: str, action_name: str, player: int = 1):
    """Read one EDF4.1 controller binding's raw value, or None if unrecognized or the buffer is too small."""
    entry = EDF41_CONTROLLER_KEYCONFIG_OFFSETS.get(player, {}).get(category)
    if not entry:
        return None
    base, actions = entry
    if action_name not in actions:
        return None
    off = base + actions.index(action_name) * 4
    if len(data) < off + 4:
        return None
    return struct.unpack_from("<I", data, off)[0]

def write_edf41_controller_keybind(data: bytearray, category: str, action_name: str, raw_value: int, player: int = 1) -> bool:
    """Write one EDF4.1 controller binding's raw value in place. Returns True on success."""
    entry = EDF41_CONTROLLER_KEYCONFIG_OFFSETS.get(player, {}).get(category)
    if not entry:
        return False
    base, actions = entry
    if action_name not in actions:
        return False
    off = base + actions.index(action_name) * 4
    if len(data) < off + 4:
        return False
    struct.pack_into("<I", data, off, int(raw_value) & 0xFFFFFFFF)
    return True

def read_edf41_keyboard_keybind(data, category: str, action_name: str, player: int = 1):
    """Read one EDF4.1 keyboard binding's raw value (Player 1 only - always None for Player 2)."""
    if player != 1:
        return None
    entry = EDF41_KEYBOARD_KEYCONFIG_OFFSETS.get(1, {}).get(category)
    if not entry:
        return None
    base, actions = entry
    if action_name not in actions:
        return None
    off = base + actions.index(action_name) * 4
    if len(data) < off + 4:
        return None
    return struct.unpack_from("<I", data, off)[0]

def write_edf41_keyboard_keybind(data: bytearray, category: str, action_name: str, raw_value: int, player: int = 1) -> bool:
    """Write one EDF4.1 keyboard binding's raw value in place; no-op for Player 2 (offset unconfirmed)."""
    if player != 1:
        return False
    entry = EDF41_KEYBOARD_KEYCONFIG_OFFSETS.get(1, {}).get(category)
    if not entry:
        return False
    base, actions = entry
    if action_name not in actions:
        return False
    off = base + actions.index(action_name) * 4
    if len(data) < off + 4:
        return False
    struct.pack_into("<I", data, off, int(raw_value) & 0xFFFFFFFF)
    return True

def edf41_gamepad_button_names(controller_type: str = "xbox"):
    """Ordered (raw_value, display_name) pairs from EDF4.1's own 0-10 button table (own numeric scheme, not EDF5/6's)."""
    table = EDF41_CONTROLLER_BUTTON_TABLES.get(controller_type, EDF41_CONTROLLER_BUTTON_NAMES)
    return [(raw, name) for raw, name in sorted(table.items())]

def edf41_decode_gamepad_button(raw_value, controller_type: str = "xbox") -> str:
    """EDF4.1 analog of decode_gamepad_button()."""
    table = EDF41_CONTROLLER_BUTTON_TABLES.get(controller_type, EDF41_CONTROLLER_BUTTON_NAMES)
    return table.get(raw_value, f"#{raw_value}")

def _mirrored_actions_for_game(game: str):
    """Return the Common Controls + vehicle-category lookup table for `game` (all entries confirmed for EDF6)."""
    if _game_is_edf6(game):
        return {**EDF6_COMMON_ACTIONS, **EDF6_VEHICLE_ACTIONS}
    return EDF5_MIRRORED_ACTIONS

# Vehicle categories have no group of their own - the same byte is written into all 4 class groups at once, at the same relative slot.
# Common Controls is a genuine 6th top-level category: 12 actions at slots -6..5 relative to each class's group_base, confirmed via screenshot + Ghidra's case-order enum.
EDF5_COMMON_ACTIONS = {
    "Common": [
        ("Move - Front", -6, True),
        ("Move - Back", -5, True),
        ("Move - Left", -4, True),
        ("Move - Right", -3, True),
        ("Rescue / Ride", -2, True),
        ("Spot", -1, True),
        ("Chat Window", 0, True),
        ("Chat Shortcuts", 1, True),
        ("Weapon Shortcut 1", 2, True),
        ("Weapon Shortcut 2", 3, True),
        ("Weapon Shortcut 3", 4, True),
        ("Voice Chat", 5, True),
    ],
}

EDF5_VEHICLE_ACTIONS = {
    "Drive": [  # All 5 confirmed via rebind-and-diff testing + a real in-game screenshot
        ("Accelerate", 21, True),
        ("Brake", 22, True),
        ("Hand Brake", 23, True),
        ("Attack", 24, True),
        ("Horn", 25, True),
    ],
    "Tanks": [  # Confirmed via a real rebind-and-diff test; slots 26-28, Player 1 only
        ("Attack1", 26, True),
        ("Attack2", 27, True),
        ("Horn", 28, True),
    ],
    "Heli": [  # Confirmed via positional search; slots 44-46, last 3 in the vehicle block
        ("Attack1", 44, True),
        ("Attack2", 45, True),
        ("Flight", 46, True),
    ],
    "Combat": [  # Confirmed by elimination once Barga's rebind-and-diff test cleared slots 29-33
        ("Attack - R.Hand", 29, True),
        ("Attack - L.Hand", 30, True),
        ("Attack - R.Shldr", 31, True),
        ("Attack - L.Shldr", 32, True),
        ("Jump", 33, True),
    ],
    "Barga": [  # Confirmed via a real rebind-and-diff test
        ("Attack - R.Hand", 34, True),
        ("Attack - L.Hand", 35, True),
        ("Attack - R.Stomp", 36, True),
        ("Attack - L.Stomp", 37, True),
        ("Special Pose", 38, True),
    ],
    "Depth": [  # Confirmed via a real rebind-and-diff test
        ("Attack - Right", 39, True),
        ("Attack - Left", 40, True),
        ("Gatling", 41, True),
        ("Avoidance", 42, True),
        ("Jump", 43, True),
    ],
}

# Controller (gamepad) bindings - a separate storage region from keyboard binds, still inside COMMON.CFG (offset 56). Confirmed via rebind-and-diff testing.
GAMEPAD_BUTTON_TABLE = {
    0: "Not Assigned",
    1: "A button",
    2: "B button",
    3: "X button",
    4: "Y button",
    5: "Left trigger",
    6: "Right trigger",
    7: "LB",
    8: "RB",
    9: "Left stick button",
    10: "Right stick button",
    11: "BACK button",
}

# Controller-type display overlay - cosmetic relabeling of the same raw 0-11 encoding, EDF6-only (confirmed via Ghidra's 3 parallel string-key sets); EDF5 has no PS4/Switch strings, forces "xbox".
GAMEPAD_BUTTON_TABLE_PS4 = {
    0: "Not Assigned",
    1: "× Button",   # ×
    2: "○ Button",   # ○
    3: "□ Button",   # □
    4: "△ Button",   # △
    5: "L2 Button",
    6: "R2 Button",
    7: "L1 Button",
    8: "R1 Button",
    9: "L3 Button",
    10: "R3 Button",
    11: "SHARE Button",
}

# Note the real A/B and X/Y swap vs Xbox/PS4 - matches actual Switch Pro Controller hardware
# layout (its physical "A" sits where Xbox/PS4 put "B", etc.), not a transcription error.
GAMEPAD_BUTTON_TABLE_SWITCH = {
    0: "Not Assigned",
    1: "B Button",
    2: "A Button",
    3: "Y Button",
    4: "X Button",
    5: "ZL Button",
    6: "ZR Button",
    7: "L Button",
    8: "R Button",
    9: "press the L Stick",
    10: "press the R Stick",
    11: "- Button",
}

GAMEPAD_BUTTON_TABLES = {
    "xbox": GAMEPAD_BUTTON_TABLE,
    "ps4": GAMEPAD_BUTTON_TABLE_PS4,
    "switch": GAMEPAD_BUTTON_TABLE_SWITCH,
}

# Per-class controller action lists, in each class's real in-game controller-screen order. Each
# class's block is a uniform 10-int array (Fencer's 11-action layout is the exception, no padding);
# unused "extra" slots use a placeholder name starting with "(" so index-based offsets still resolve.
CONTROLLER_ACTIONS = {
    "Ranger": [
        "Attack", "Zoom/Activate", "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "Dash", "Summon Vehicle",
    ],
    "Wing Diver": [
        "Attack", "Zoom/Activate", "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "Boost", "(unused slot 9)",
    ],
    "Air Raider": [
        "Attack", "Zoom/Activate", "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "(unused slot 8)", "Summon Vehicle",
    ],
    "Fencer": [
        "Attack - R.Hand", "Attack - L.Hand", "Use - R.Hand", "Use - L.Hand",
        "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "Shield Reload",
    ],
}

# Absolute byte offsets (Player 1) for each class's controller block, hardcoded (not a fixed
# formula from EDF5_KEYBIND_GROUP_BASES). All 4 classes confirmed via rebind-and-diff testing;
# Player 2 uses the same PLAYER2_KEYBIND_OFFSET delta as keyboard binds.
CONTROLLER_GROUP_OFFSETS = {
    "Ranger": 56,
    "Fencer": 3156,
    "Wing Diver": 1076,
    "Air Raider": 2096,
}

CONTROLLER_CONFIRMED = {
    "Ranger": True,
    "Fencer": True,
    "Wing Diver": True,
    "Air Raider": True,
}

# EDF6 controller bindings - found via full-remap-and-diff testing; EDF6 reuses EDF5's GAMEPAD_BUTTON_TABLE encoding with 11 slots per class (one new action added vs EDF5's 10).
CONTROLLER_ACTIONS_EDF6 = {
    "Ranger": [
        "Attack", "Zoom/Activate", "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "Dash", "Summon Vehicle", "Use Backpack Tool",
    ],
    "Wing Diver": [
        "Attack", "Zoom/Activate", "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "Boost", "(unused slot 9)", "Use Independently Operated Equipment",
    ],
    "Air Raider": [
        "Attack", "Zoom/Activate", "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "(unused slot 8)", "Summon Vehicle", "Use Backpack Tool",
    ],
    "Fencer": [
        "Attack - R.Hand", "Attack - L.Hand", "Use - R.Hand", "Use - L.Hand",
        "Jump", "Switch Weapons", "Reload",
        "Vehicle/Rescue", "Location Marking", "Chat Shortcuts",
        "Shield Reload",
    ],
}

CONTROLLER_GROUP_OFFSETS_EDF6 = {
    "Ranger": 60,
    "Wing Diver": 1080,
    "Air Raider": 2100,
    "Fencer": 3164,
}

# All 4 classes CONFIRMED for both players via screenshot + rebind-and-diff testing.
CONTROLLER_CONFIRMED_EDF6 = {
    "Ranger": True,
    "Wing Diver": True,
    "Air Raider": True,
    "Fencer": True,
}

PLAYER2_KEYBIND_OFFSET_EDF6 = 10240  # Confirmed via real diff test

def _controller_tables_for_game(game):
    """Pick the right (actions, group_offsets, player2_offset) triple for `game` (EDF5 is the default)."""
    if _game_is_edf6(game):
        return CONTROLLER_ACTIONS_EDF6, CONTROLLER_GROUP_OFFSETS_EDF6, PLAYER2_KEYBIND_OFFSET_EDF6
    return CONTROLLER_ACTIONS, CONTROLLER_GROUP_OFFSETS, PLAYER2_KEYBIND_OFFSET

def get_controller_actions(class_name: str, game: str = "EDF5", player: int = 1):
    """Return the ordered list of controller action names for a soldier class in `game`, or [] if not recognized (`player` only matters for EDF4.1)."""
    if _game_is_edf41(game):
        entry = EDF41_CONTROLLER_KEYCONFIG_OFFSETS.get(player, {}).get(class_name)
        return list(entry[1]) if entry else []
    actions, _base, _p2 = _controller_tables_for_game(game)
    return actions.get(class_name, [])

def read_controller_keybind(data, class_name: str, action_name: str, player: int = 1, game: str = "EDF5"):
    """Read a single controller binding's raw value, or None if not recognized for that game."""
    if _game_is_edf41(game):
        return read_edf41_controller_keybind(data, class_name, action_name, player=player)
    actions_by_class, offsets_by_class, player2_offset = _controller_tables_for_game(game)
    actions = actions_by_class.get(class_name)
    base = offsets_by_class.get(class_name)
    if actions is None or base is None or action_name not in actions:
        return None
    offset = base + actions.index(action_name) * 4
    if player == 2:
        offset += player2_offset
    return struct.unpack_from("<i", data, offset)[0]

def write_controller_keybind(data, class_name: str, action_name: str, raw_value: int, player: int = 1, game: str = "EDF5"):
    """Write a single controller (gamepad) binding's raw value. Returns True on success, False
    if class_name or action_name isn't recognized for that game."""
    if _game_is_edf41(game):
        return write_edf41_controller_keybind(data, class_name, action_name, raw_value, player=player)
    actions_by_class, offsets_by_class, player2_offset = _controller_tables_for_game(game)
    actions = actions_by_class.get(class_name)
    base = offsets_by_class.get(class_name)
    if actions is None or base is None or action_name not in actions:
        return False
    offset = base + actions.index(action_name) * 4
    if player == 2:
        offset += player2_offset
    struct.pack_into("<i", data, offset, raw_value)
    return True

def decode_gamepad_button(raw_value: int, controller_type: str = "xbox", game=None) -> str:
    """Decode a raw controller button value to its display label; EDF4.1 routes to its own distinct button table."""
    if game is not None and _game_is_edf41(game):
        return edf41_decode_gamepad_button(raw_value, controller_type)
    table = GAMEPAD_BUTTON_TABLES.get(controller_type, GAMEPAD_BUTTON_TABLE)
    return table.get(raw_value, f"#{raw_value}")

# Ordered (raw_value, display_name) pairs for a UI dropdown, same data as GAMEPAD_BUTTON_TABLE.
GAMEPAD_BUTTON_NAMES = [(raw, name) for raw, name in sorted(GAMEPAD_BUTTON_TABLE.items())]

def gamepad_button_names(controller_type: str = "xbox", game=None):
    """Controller-type-aware analog of the GAMEPAD_BUTTON_NAMES constant above (which is just
    gamepad_button_names('xbox') - kept as-is for back-compat). Returns ordered (raw_value,
    display_name) pairs for whichever overlay is selected, for populating a UI dropdown. `game`,
    if passed and EDF4.1, routes to edf41_gamepad_button_names() instead - see
    decode_gamepad_button's own comment for why."""
    if game is not None and _game_is_edf41(game):
        return edf41_gamepad_button_names(controller_type)
    table = GAMEPAD_BUTTON_TABLES.get(controller_type, GAMEPAD_BUTTON_TABLE)
    return [(raw, name) for raw, name in sorted(table.items())]

def load_all_controller_keybinds(data, game: str = "EDF5"):
    """Read every controller binding into a {(player, class_name, action_name): raw_value} dict, game-aware."""
    if _game_is_edf41(game):
        keybinds = {}
        for player in (1, 2):
            for category in ("Solder", "Fencer"):
                for action_name in get_controller_actions(category, game=game, player=player):
                    keybinds[(player, category, action_name)] = read_controller_keybind(data, category, action_name, player=player, game=game)
        return keybinds
    actions_by_class, _base, _p2 = _controller_tables_for_game(game)
    keybinds = {}
    for player in (1, 2):
        for class_name, actions in actions_by_class.items():
            for action_name in actions:
                keybinds[(player, class_name, action_name)] = read_controller_keybind(data, class_name, action_name, player=player, game=game)
    return keybinds

def save_all_controller_keybinds(data: bytearray, keybinds: dict, game: str = "EDF5") -> None:
    """Inverse of load_all_controller_keybinds: writes each entry back into decrypted COMMON.CFG, skipping any class_name not in that game's actions table."""
    if _game_is_edf41(game):
        for key, raw_value in keybinds.items():
            if raw_value is None:
                continue
            player, category, action_name = key
            write_controller_keybind(data, category, action_name, raw_value, player=player, game=game)
        return
    actions_by_class, _base, _p2 = _controller_tables_for_game(game)
    for key, raw_value in keybinds.items():
        if raw_value is None:
            continue
        player, class_name, action_name = key
        if class_name in actions_by_class:
            write_controller_keybind(data, class_name, action_name, raw_value, player=player, game=game)

def save_common_cfg_controller_keybinds(app, keybinds: dict) -> bool:
    """Re-decrypt COMMON.CFG, apply every controller keybind entry, and write it back out; returns False if COMMON.CFG can't be located."""
    if not getattr(app, 'current_file', None):
        return False
    folder = os.path.dirname(app.current_file)
    cfg_file = os.path.join(folder, 'COMMON.CFG')
    if not os.path.exists(cfg_file):
        return False
    try:
        cfg_data = bytearray(_load_game_file(app, cfg_file))
    except Exception as e:
        print(f"Error reading COMMON.CFG for controller keybinds: {e}")
        return False
    save_all_controller_keybinds(cfg_data, keybinds, game=getattr(app, 'current_game', 'EDF5'))
    _save_game_file(app, cfg_file, cfg_data)
    return True

# Common Controls and every vehicle category share the same mirrored-into-all-4-classes storage, so they're unified into one lookup table.
EDF5_MIRRORED_ACTIONS = {**EDF5_COMMON_ACTIONS, **EDF5_VEHICLE_ACTIONS}

# Single ordered list of all 11 Key Config UI categories, matching the in-game screen's own top-level order (confirmed via screenshot + Ghidra's case-order enum).
KEYCONFIG_CATEGORIES = list(EDF5_COMMON_ACTIONS) + list(EDF5_SOLDIER_ACTIONS) + list(EDF5_VEHICLE_ACTIONS)

def get_keyconfig_actions(category: str, game: str = "EDF5"):
    """Return the (action_name, slot, confirmed) list for a Key Config category name, whether Common, a soldier class, or a vehicle category, game-aware."""
    if _game_is_edf41(game):
        return get_keyconfig_actions_edf41(category, mode="Keyboard", player=1)
    if _game_is_edf6(game):
        return EDF6_SOLDIER_ACTIONS.get(category) or _mirrored_actions_for_game(game).get(category) or []
    return EDF5_SOLDIER_ACTIONS.get(category) or EDF5_MIRRORED_ACTIONS.get(category) or []

def _keybind_slot_offset(group_base: int, slot: int) -> int:
    return group_base + slot * 4

def _keybind_group_base(class_name: str, player: int = 1):
    """Return `class_name`'s group base for the given player (1 or 2), or None if not recognized."""
    base = EDF5_KEYBIND_GROUP_BASES.get(class_name)
    if base is None:
        return None
    return base + (PLAYER2_KEYBIND_OFFSET if player == 2 else 0)

# Full keyboard-key decode/encode table, confirmed via Ghidra RE of EDF6's DLL: not a Win32 VK
# code, but the game's own custom 103-entry table where raw_stored_value = table_index + 0x12.
# Shared by both EDF5 and EDF6, cross-checked against every real rebind result from testing.
EDF5_KEY_TABLE = [
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "Num0", "Num1", "Num2", "Num3", "Num4", "Num5", "Num6", "Num7", "Num8", "Num9",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "Hyphen", "Caret", "Yen", "At", "Semicolon", "Colon", "BracketsL", "BracketsR",
    "Comma", "Period",
    "ShiftL", "ShiftR", "ControlL", "ControlR", "AltL", "AltR", "WinL", "WinR",
    "Up", "Down", "Left", "Right",
    "Return", "Space", "BackSpace", "Tab", "Insert", "Delete", "Home", "End",
    "PageDown", "PageUp", "Help", "Escape", "Print", "Pause", "NumLock", "Multi",
    "Add", "Separator", "Subtract", "Decimal", "Divide", "Sleep", "Kana",
]
EDF5_KEY_TABLE_OFFSET = 0x12  # raw_stored_value = EDF5_KEY_TABLE.index(name) + this
_EDF5_KEY_NAME_TO_INDEX = {name: i for i, name in enumerate(EDF5_KEY_TABLE)}

# EDF5 mouse button raw values (below EDF5_KEY_TABLE_OFFSET), confirmed via real in-game ground truth. 16/17 remain unmapped (likely MouseSide1/2).
EDF5_MOUSE_TABLE = {
    12: "MouseL",
    13: "MouseM",
    14: "MouseR",
    15: "MouseWheel",
}
_EDF5_MOUSE_NAME_TO_RAW = {name: raw for raw, name in EDF5_MOUSE_TABLE.items()}

def decode_keybind_letter(raw_value: int, game=None):
    """Return the bound key/mouse-button name, or None if raw_value is outside both known tables (show the raw int instead). EDF4.1 routes to edf41_keyboard_key_name() instead - own offset constant, not EDF5/6's."""
    if game is not None and _game_is_edf41(game):
        return edf41_keyboard_key_name(raw_value) or None
    if raw_value in EDF5_MOUSE_TABLE:
        return EDF5_MOUSE_TABLE[raw_value]
    idx = raw_value - EDF5_KEY_TABLE_OFFSET
    if 0 <= idx < len(EDF5_KEY_TABLE):
        return EDF5_KEY_TABLE[idx]
    return None

def encode_keybind_letter(name: str, game=None):
    """Inverse of decode_keybind_letter: key or mouse-button name -> raw stored value, or None if unrecognized. EDF4.1 routes to edf41_keyboard_raw_value() instead."""
    if game is not None and _game_is_edf41(game):
        return edf41_keyboard_raw_value(name) if name else None
    if not name:
        return None
    if name in _EDF5_MOUSE_NAME_TO_RAW:
        return _EDF5_MOUSE_NAME_TO_RAW[name]
    key = name if name in _EDF5_KEY_NAME_TO_INDEX else name.upper()
    idx = _EDF5_KEY_NAME_TO_INDEX.get(key)
    if idx is None:
        return None
    return idx + EDF5_KEY_TABLE_OFFSET

def read_soldier_keybind(data, class_name: str, action_name: str, player: int = 1, game: str = "EDF5"):
    """Read one soldier-class action's raw keybind value from decrypted COMMON.CFG, or None if unrecognized/buffer too small. EDF4.1 routes to read_edf41_keyboard_keybind instead."""
    if _game_is_edf41(game):
        return read_edf41_keyboard_keybind(data, class_name, action_name, player=player)
    group_base = _keybind_group_base(class_name, player)
    actions = (EDF6_SOLDIER_ACTIONS if _game_is_edf6(game) else EDF5_SOLDIER_ACTIONS).get(class_name)
    if group_base is None or actions is None:
        return None
    for name, slot, _confirmed in actions:
        if name == action_name:
            off = _keybind_slot_offset(group_base, slot)
            if len(data) < off + 4:
                return None
            return struct.unpack_from("<I", data, off)[0]
    return None

def write_soldier_keybind(data: bytearray, class_name: str, action_name: str, raw_value: int, player: int = 1, game: str = "EDF5") -> bool:
    """Write one soldier-class action's raw keybind value into decrypted COMMON.CFG in place; returns False if unrecognized/buffer too small."""
    if _game_is_edf41(game):
        return write_edf41_keyboard_keybind(data, class_name, action_name, raw_value, player=player)
    group_base = _keybind_group_base(class_name, player)
    actions = (EDF6_SOLDIER_ACTIONS if _game_is_edf6(game) else EDF5_SOLDIER_ACTIONS).get(class_name)
    if group_base is None or actions is None:
        return False
    for name, slot, _confirmed in actions:
        if name == action_name:
            off = _keybind_slot_offset(group_base, slot)
            if len(data) < off + 4:
                return False
            struct.pack_into("<I", data, off, int(raw_value) & 0xFFFFFFFF)
            return True
    return False

def read_vehicle_keybind(data, category_name: str, action_name: str, class_name: str = "Ranger", player: int = 1, game: str = "EDF5"):
    """Read one vehicle- or Common-category action's raw keybind value (mirrored identically across all 4 soldier classes, so defaults to reading Ranger's copy); None if unrecognized/buffer too small."""
    group_base = _keybind_group_base(class_name, player)
    actions = _mirrored_actions_for_game(game).get(category_name)
    if group_base is None or actions is None:
        return None
    for name, slot, _confirmed in actions:
        if name == action_name:
            off = _keybind_slot_offset(group_base, slot)
            if len(data) < off + 4:
                return None
            return struct.unpack_from("<I", data, off)[0]
    return None

def write_vehicle_keybind(data: bytearray, category_name: str, action_name: str, raw_value: int, player: int = 1, game: str = "EDF5") -> bool:
    """Write one vehicle- or Common-category action's raw keybind value into all 4 of that player's soldier-class groups at once (the game keeps them in sync); True if written to at least one."""
    actions = _mirrored_actions_for_game(game).get(category_name)
    if actions is None:
        return False
    slot = None
    for name, s, _confirmed in actions:
        if name == action_name:
            slot = s
            break
    if slot is None:
        return False
    wrote_any = False
    for class_name in EDF5_KEYBIND_GROUP_BASES:
        group_base = _keybind_group_base(class_name, player)
        off = _keybind_slot_offset(group_base, slot)
        if len(data) < off + 4:
            continue
        struct.pack_into("<I", data, off, int(raw_value) & 0xFFFFFFFF)
        wrote_any = True
    return wrote_any

def load_all_keybinds(data, game: str = "EDF5"):
    """Return every mapped keybind for both players as {(player, class_or_category, action): raw_value or None}, for a UI's in-memory cache. EDF4.1 reads its confirmed categories directly from EDF41_KEYBOARD_KEYCONFIG_OFFSETS[1]."""
    if _game_is_edf41(game):
        keybinds = {}
        for category in EDF41_KEYBOARD_KEYCONFIG_OFFSETS.get(1, {}):
            for action_name, _idx, _c in get_keyconfig_actions(category, game=game):
                keybinds[(1, category, action_name)] = read_soldier_keybind(data, category, action_name, player=1, game=game)
        return keybinds
    keybinds = {}
    soldier_actions = EDF6_SOLDIER_ACTIONS if _game_is_edf6(game) else EDF5_SOLDIER_ACTIONS
    mirrored_actions = _mirrored_actions_for_game(game)
    for player in (1, 2):
        for class_name, actions in soldier_actions.items():
            for action_name, _slot, _confirmed in actions:
                keybinds[(player, class_name, action_name)] = read_soldier_keybind(data, class_name, action_name, player=player, game=game)
        for category_name, actions in mirrored_actions.items():
            for action_name, _slot, _confirmed in actions:
                keybinds[(player, category_name, action_name)] = read_vehicle_keybind(data, category_name, action_name, player=player, game=game)
    return keybinds

def save_all_keybinds(data: bytearray, keybinds: dict, game: str = "EDF5") -> None:
    """Inverse of load_all_keybinds: writes every entry back into decrypted COMMON.CFG in place, skipping unrecognized keys and tolerating old 2-tuple (pre-Player-2) cache entries as player 1."""
    if _game_is_edf41(game):
        edf41_categories = EDF41_KEYBOARD_KEYCONFIG_OFFSETS.get(1, {})
        for key, raw_value in keybinds.items():
            if raw_value is None:
                continue
            if len(key) == 3:
                player, name, action_name = key
            else:
                player, (name, action_name) = 1, key
            if player == 1 and name in edf41_categories:
                write_soldier_keybind(data, name, action_name, raw_value, player=1, game=game)
        return
    soldier_actions = EDF6_SOLDIER_ACTIONS if _game_is_edf6(game) else EDF5_SOLDIER_ACTIONS
    mirrored_actions = _mirrored_actions_for_game(game)
    for key, raw_value in keybinds.items():
        if raw_value is None:
            continue
        if len(key) == 3:
            player, name, action_name = key
        else:
            player, (name, action_name) = 1, key
        if name in soldier_actions:
            write_soldier_keybind(data, name, action_name, raw_value, player=player, game=game)
        elif name in mirrored_actions:
            write_vehicle_keybind(data, name, action_name, raw_value, player=player, game=game)

def save_common_cfg_keybinds(app, keybinds: dict) -> bool:
    """Re-decrypt COMMON.CFG, apply every keybind entry via save_all_keybinds, and write it back out; returns False if COMMON.CFG can't be located."""
    if not getattr(app, 'current_file', None):
        return False
    folder = os.path.dirname(app.current_file)
    cfg_file = os.path.join(folder, 'COMMON.CFG')
    if not os.path.exists(cfg_file):
        return False
    try:
        cfg_data = bytearray(_load_game_file(app, cfg_file))
    except Exception as e:
        print(f"Error reading COMMON.CFG for keybinds: {e}")
        return False
    save_all_keybinds(cfg_data, keybinds, game=getattr(app, 'current_game', 'EDF5'))
    _save_game_file(app, cfg_file, cfg_data)
    return True

def load_save_data(app):
    # Start the dialog at app.default_save_dir so the user doesn't have to navigate AppData's hidden folders.
    initial_dir = getattr(app, 'default_save_dir', None)
    if not initial_dir or not os.path.isdir(initial_dir):
        initial_dir = None
    folder = filedialog.askdirectory(title="Select Save Folder", initialdir=initial_dir)
    if folder:
        # Sync the game selector to the picked folder if it belongs to a different EDF game.
        if hasattr(app, 'sync_game_selector_to_folder'):
            try:
                app.sync_game_selector_to_folder(folder)
            except Exception as e:
                print(f"[WARN] sync_game_selector_to_folder failed: {e}")
        gst_files = [f for f in os.listdir(folder) if f.endswith('.GST')]
        if not gst_files:
            print("No GST files found in the folder.")
            return
        gst_file = os.path.join(folder, 'MAIN.GST') if 'MAIN.GST' in gst_files else os.path.join(folder, gst_files[0])
        # Catch "these files don't share a generation ID" (e.g. a friend's save dropped in wholesale)
        # before it's parsed into the UI - see check_and_offer_generation_id_fix()'s docstring.
        if hasattr(app, 'check_and_offer_generation_id_fix'):
            try:
                app.check_and_offer_generation_id_fix(folder, getattr(app, 'current_game', 'EDF6'))
            except Exception as e:
                print(f"[WARN] check_and_offer_generation_id_fix failed: {e}")
        data = _load_game_file(app, gst_file)  # Decrypted bytes
        app.current_file = gst_file
        current_game = getattr(app, 'current_game', 'EDF6')
        armor_structure = get_armor_structure(current_game)
        for i, (offset, _, fmt, _, _) in enumerate(armor_structure):
            if len(data) < offset + 4:
                print(f"Warning: File too small for offset {offset}")
                continue
            v = struct.unpack_from(fmt, data, offset)[0]
            app.armor_entries[i].delete(0, "end")
            app.armor_entries[i].insert(0, str(v))
        loadout_structure = get_loadout_structure(current_game)
        for i, (offset, _, fmt, _) in enumerate(loadout_structure):
            if len(data) < offset + 4:
                print(f"Warning: File too small for offset {offset}")
                continue
            v = struct.unpack_from(fmt, data, offset)[0]
            app.loadout_entries[i].delete(0, "end")
            app.loadout_entries[i].insert(0, "-1" if v == LOADOUT_UNUSED_SLOT_RAW else str(v))  # -1 displays the unused-slot sentinel
        # Load color data for both players eagerly (cheap); app.color_data_cache holds both, app.color_data points at whichever is active.
        app.color_data_cache = {
            1: load_all_color_groups(data, player=1, game=current_game),
            2: load_all_color_groups(data, player=2, game=current_game),
        }
        app.color_player_slot = 1
        app.color_data = app.color_data_cache[1]
        if hasattr(app, 'refresh_color_panel'):
            app.refresh_color_panel()
        # Weapon table: this 4-byte field is an ownership/condition marker (0=unowned, else low
        # byte = WeaponCondition enum), not an "average" stat despite the historical name. Upper
        # 3 bytes are leftover/overflow, cached in app.weapon_condition_upper and preserved on save.
        weapon_data = []
        app.weapon_condition_upper = {}
        if _game_is_edf41(current_game):
            # EDF4.1: ownership flag array at EDF41_WEAPON_TABLE_BASE; names from WeaponNamesLang.json's EDF4.1 roster; Stat1-8 don't apply (EDF6/5-only).
            en_names = app.weapon_names_lang.get('EDF4.1', {}).get('languages', {}).get('en', {})
            max_id = max((int(k) for k in en_names.keys()), default=-1)
            for wid in range(max_id + 1):
                offset = EDF41_WEAPON_TABLE_BASE + wid * EDF41_WEAPON_TABLE_STRIDE
                if len(data) >= offset + 4:
                    raw = struct.unpack_from("<I", data, offset)[0]
                else:
                    raw = 0
                owned_display = raw & 0xFF
                app.weapon_condition_upper[wid] = raw & 0xFFFFFF00
                weapon_data.append([wid, "Unknown", owned_display] + [0] * 8)
        else:
            weapon_table_base = get_weapon_table_base(current_game)
            for i in range(0, 0x6000, 12):
                if len(data) < weapon_table_base + i + 12:
                    break
                entry = data[weapon_table_base + i : weapon_table_base + i + 12]
                condition_raw = struct.unpack("<I", entry[0:4])[0]  # was mislabeled "avg"; see note above
                condition_display = condition_raw & 0xFF
                app.weapon_condition_upper[i//12] = condition_raw & 0xFFFFFF00
                stats = list(entry[4:12])
                name = "Unknown"  # Overwritten right after load by get_weapon_name() in EDFSaveEditorMain.py
                weapon_data.append([i//12, name, condition_display] + stats)
        app.weapon_data = weapon_data
        if hasattr(app, 'rebuild_weapon_table_columns_for_game'):
            try: app.rebuild_weapon_table_columns_for_game()
            except Exception as e: print(f"[WARN] rebuild_weapon_table_columns_for_game failed: {e}")
        # Clear the full 0..2047 iid range (not just get_children()) so no stale detached row survives a reload.
        for idx in range(2048):
            iid = str(idx)
            if app.tree.exists(iid):
                app.tree.delete(iid)
        for idx, row in enumerate(weapon_data):
            app.tree.insert("", "end", iid=str(idx), values=row)
        load_all_mission_tables(app, folder)
        current_game = getattr(app, 'current_game', 'EDF6')
        player_slot = getattr(app, 'mission_player_slot', 1)
        cache_entry = app.mission_table_cache.get(current_game)
        if cache_entry:
            app.current_mst_file = cache_entry['mst_file']
            slot_arrays = cache_entry['slots'].get(player_slot)
            if slot_arrays is None:
                # Player 2 isn't eagerly parsed by load_all_mission_tables - read and cache it now.
                mst_data = _load_game_file(app, cache_entry['mst_file'])
                slot_arrays = _extract_mission_arrays(mst_data, player_slot, game=current_game)
                if slot_arrays is not None:
                    cache_entry['slots'][player_slot] = slot_arrays
            if slot_arrays is not None:
                app.mission_arrays[0:4] = [bytearray(a) for a in slot_arrays]
            else:
                print(f"Warning: {os.path.basename(cache_entry['mst_file'])} too small for player slot {player_slot} mission data")
        else:
            # No .MST found for the selected game/DLC - show an empty table rather than stale bytes.
            app.current_mst_file = None
            app.mission_arrays[0:4] = [bytearray(0x200) for _ in range(4)]
            print(f"Warning: mission table not found for {current_game} in this folder")
        # Load additional files from the same folder
        folder = os.path.dirname(app.current_file) if app.current_file else None
        if folder:
            # TROPHY.DAT
            trophy_file = os.path.join(folder, 'TROPHY.DAT')
            td = None
            if os.path.exists(trophy_file):
                if td is None:
                    # Read raw ciphertext
                    with open(trophy_file, 'rb') as f:
                        raw = f.read()
                    trophy_data = None
                    app.trophy_key = None
                    app.trophy_iv = None
                    app.trophy_encrypted = False
                    app.trophy_is_edf41 = False
                    game = getattr(app, 'current_game', 'EDF6')

                    # Try the standard per-file key derivation first; fall back to brute force below if it doesn't produce a valid MDB0 header.
                    try:
                        direct_key, direct_iv = generate_key_iv(trophy_file, game=game)
                        direct_pt = aes_ctr_decrypt(raw, direct_key, direct_iv)
                    except Exception:
                        direct_pt = None
                    if direct_pt is not None and direct_pt[:4] == b'MDB0':
                        trophy_data = direct_pt
                        app.trophy_encrypted = True
                        app.trophy_key = direct_key
                        app.trophy_iv = direct_iv
                    else:
                        # Fallback: try every known AES-CTR key/iv derivation (GST-derived key, digit/base-name brute force, MST-style variants).
                        candidates = generate_dat_key_iv_variants(trophy_file, app.current_file)
                        result = try_decrypt_variants(raw, candidates)
                        if result:
                            trophy_data, tag, key, iv = result
                            app.trophy_encrypted = True
                            app.trophy_key = key
                            app.trophy_iv = iv

                    # EDF4.1 uses a fixed key/iv cipher, not a per-filename derivation - tried separately as a last resort; app.trophy_is_edf41 flags it for save_save_data()'s trophy block to use edf41_encrypt/decrypt instead.
                    if trophy_data is None and game.startswith('EDF4'):
                        try:
                            dec = edf41_decrypt(raw)
                            if dec[:4] == b'MDB0':
                                trophy_data = dec
                                app.trophy_encrypted = True
                                app.trophy_is_edf41 = True
                        except Exception:
                            pass

                    if trophy_data is None:
                        trophy_data = raw
                        app.trophy_encrypted = False

                    td = trophy_data if isinstance(trophy_data, (bytes, bytearray)) else bytes(trophy_data)

                # Remember current trophy path
                app.current_trophy_file = trophy_file

                # EDF4.1 armor lives only in TROPHY.DAT (get_armor_structure() returns [] for it) - populate directly from these floats.
                if _game_is_edf41(current_game):
                    for i, label in enumerate(("Ranger Armor", "Wingdiver Armor", "Air Raider Armor", "Fencer Armor")):
                        if i >= len(app.armor_entries):
                            break
                        offset = EDF41_TROPHY_ARMOR_OFFSETS.get(label)
                        app.armor_entries[i].delete(0, "end")
                        if offset is None or offset + 4 > len(td):
                            app.armor_entries[i].insert(0, "0")
                            continue
                        v = struct.unpack_from("<f", td, offset)[0]
                        text = f"{v:.3f}".rstrip('0').rstrip('.') if v != int(v) else str(int(v))  # trim whole-number floats to plain ints
                        app.armor_entries[i].insert(0, text)

                # Interpret total-time value (ticks at 60Hz -> seconds), game-aware offset.
                playtime_offset = get_playtime_offset(current_game)
                if playtime_offset is not None and len(td) >= playtime_offset + 4:
                    v_le = struct.unpack_from("<I", td, playtime_offset)[0]
                    hours = v_le // 0x34bc0        # 0x34bc0 == 216000 == 3600*60 H
                    minutes = (v_le // 0xE10) % 60 # 0xE10 == 3600 == 60*60 M
                    seconds = (v_le // 0x3C) % 60  # 0x3C == 60 == ticks per S
                    formatted = f"{hours}h {minutes}m {seconds}s"
                    app.playtime_label.configure(text=formatted)
                elif playtime_offset is None:
                    app.playtime_label.configure(text="Unknown")
                else:
                    app.playtime_label.configure(text="TROPHY.DAT Too Small")

                if _game_is_edf41(current_game):
                    # EDF4.1 has no separate stored "unlocked" bit for achievements at all - unlike
                    # EDF6/EDF5's byte-per-achievement flags below, status is always DERIVED from the
                    # named counters themselves (the same ones Steam's own SetStat/SetAchievement calls
                    # use - see AchievementUtility / Achievement.sgo in SAVE_FORMAT_NOTES.md, confirmed
                    # 2026-09-08 via Ghidra RE + a real Achievement.sgo dump, cross-validated against the
                    # older sentinel-tested EDF41_KILL_FIELDS with zero conflicts). Extract those counters
                    # first, then evaluate every AchievementEvent formula against them - read-only by
                    # nature, there's nothing to toggle-and-persist the way EDF6/EDF5's flags are below.
                    edf41_kf = extract_kill_fields(td, EDF41_KILL_FIELDS)
                    app.achievement_data = compute_edf41_achievement_status(edf41_kf)
                else:
                    # Load achievements and normalize flags to 0/1. EDF6's 0x14-0x34/0x34-0x3C layout is
                    # CONFIRMED against a real save (see SAVE_FORMAT_NOTES.md's TROPHY.DAT table).
                    # 2026-09-07 (3-game audit): EDF5's "+0xC shift like the rest of its body" is
                    # asserted, not verified - unlike every other EDF5 offset in this file, there's no
                    # "byte-diffed against a real EDF5 save" note for this specific region.
                    achievement_edf5_shift = 0xC if _game_is_edf5(current_game) else 0
                    ach_progress_base = 0x14 + achievement_edf5_shift
                    ach_other_base = 0x34 + achievement_edf5_shift
                    achievement_data = []
                    percentages = list(range(5, 65, 5)) + list(range(62, 102, 2))
                    while len(percentages) < 32:
                        percentages.append(percentages[-1])
                    raw_progress = list(td[ach_progress_base:ach_progress_base+32])
                    for i in range(32):
                        raw_flag = td[ach_progress_base + i] if (ach_progress_base + i) < len(td) else 0
                        flag = 1 if raw_flag != 0 else 0
                        perc = percentages[i]
                        name = f"Conquest{perc} (Made {perc}% game progress)"
                        achievement_data.append([i, name, flag])
                    raw_other = list(td[ach_other_base:ach_other_base+7])
                    other_achievements_names = [
                        "Rescue (Rescued 5 other players in co-op play)",
                        "Super Rescue (Rescued 50 other players in co-op play)",
                        "Medic (Healed another player in co-op play)",
                        "Master Ranger (Ranger’s health has reached 1000)",
                        "Master Diver (Wing Diver’s health has reached 550)",
                        "Master Air Raider (Air Raider’s health has reached 1000)",
                        "Master Fencer (Fencer’s health has reached 1250)",
                    ]
                    for i in range(len(other_achievements_names)):
                        raw_flag = td[ach_other_base + i] if (ach_other_base + i) < len(td) else 0
                        flag = 1 if raw_flag != 0 else 0
                        name = other_achievements_names[i]
                        achievement_data.append([32 + i, name, flag])

                    app.achievement_data = achievement_data

            else:
                app.playtime_label.configure(text="TROPHY.DAT Not Found")

            # Extract kill fields from the already-loaded td using the game-appropriate table.
            if 'td' in locals() and td is not None:
                app.kill_fields = extract_kill_fields(td, get_kill_fields_table(current_game))
            else:
                app.kill_fields = {}

            # COMMON.CFG - default empty so a save with no COMMON.CFG leaves the Key Config panel blank rather than stale.
            app.keybind_data = {}
            app.controller_keybind_data = {}
            cfg_file = os.path.join(folder, 'COMMON.CFG')
            if os.path.exists(cfg_file):
                try:
                    # Prefer decrypted via game-aware loader, but fall back to raw bytes if decryption fails
                    try:
                        cfg_data = _load_game_file(app, cfg_file)
                    except ValueError:
                        with open(cfg_file, 'rb') as f:
                            cfg_data = f.read()
                    profile_name_offset = get_profile_name_offset(current_game)
                    if profile_name_offset is not None and len(cfg_data) >= profile_name_offset + 0x20:
                        v = cfg_data[profile_name_offset:profile_name_offset + 0x20]
                        name = v.decode("utf-16le", errors="replace").rstrip("\x00")
                        app.profile_name_label.configure(text=name)
                    elif profile_name_offset is None:
                        app.profile_name_label.configure(text="Unknown")
                    else:
                        # Try a best-effort decode of the file for a displayable name
                        try:
                            name_guess = cfg_data.decode("utf-16le", errors="replace").split("\x00")[0]
                            if name_guess:
                                app.profile_name_label.configure(text=name_guess)
                            else:
                                app.profile_name_label.configure(text="COMMON.CFG Too Small")
                        except Exception:
                            app.profile_name_label.configure(text="COMMON.CFG Too Small")
                    # Key Config - reuses the cfg_data already decrypted above.
                    if _game_is_edf5(current_game) or _game_is_edf6(current_game) or _game_is_edf41(current_game):
                        try:
                            app.keybind_data = load_all_keybinds(cfg_data, game=current_game)
                        except Exception as e:
                            print(f"Error reading Key Config data: {e}")
                            app.keybind_data = {}
                    # Controller Key Config.
                    if _game_is_edf5(current_game) or _game_is_edf6(current_game) or _game_is_edf41(current_game):
                        try:
                            app.controller_keybind_data = load_all_controller_keybinds(cfg_data, game=current_game)
                        except Exception as e:
                            print(f"Error reading controller Key Config data: {e}")
                            app.controller_keybind_data = {}
                except Exception as e:
                    print(f"Error reading COMMON.CFG: {e}")
                    app.profile_name_label.configure(text="COMMON.CFG Read Error")
            else:
                app.profile_name_label.configure(text="COMMON.CFG Not Found")
            if hasattr(app, 'refresh_keyconfig_panel'):
                app.refresh_keyconfig_panel()
        # Refresh sheet to apply sizes
        update_displays(app)
        app.update_loadout_names()
        app.update_achievement_table()
        if hasattr(app, 'update_kill_fields'):
            app.update_kill_fields()

        # Ensure header labels are refreshed immediately
        try:
            if hasattr(app, 'profile_name_label') and app.profile_name_label is not None:
                app.profile_name_label.update_idletasks()
        except Exception:
            pass
        try:
            if hasattr(app, 'playtime_label') and app.playtime_label is not None:
                app.playtime_label.update_idletasks()
        except Exception:
            pass

def save_save_data(app):
    if app.current_file is None:
        file = filedialog.asksaveasfilename(title="Save Save File", filetypes=(("GST Files", "*.GST"), ("All Files", "*.*")))
        if not file:
            return
        app.current_file = file
    else:
        file = app.current_file

    data = bytearray(_load_game_file(app, file))   # Load original as bytearray
    # Save armor - write both "max" and "current" offsets so the value is active in-game immediately.
    save_game = getattr(app, 'current_game', 'EDF6')
    armor_structure = get_armor_structure(save_game)
    armor_current_offsets = get_armor_current_offsets(save_game)
    armor_values = []  # Per-class, kept to sync TROPHY.DAT's TOTAL_ARMOR_POINTS_OFFSET below
    for i, (offset, _, fmt, _, _) in enumerate(armor_structure):
        try:
            v = int(app.armor_entries[i].get())
        except ValueError:
            v = 0
        armor_values.append(v)
        struct.pack_into(fmt, data, offset, v)
        if len(data) >= armor_current_offsets[i] + struct.calcsize(fmt):
            struct.pack_into(fmt, data, armor_current_offsets[i], v)
    loadout_structure = get_loadout_structure(save_game)
    for i, (offset, _, fmt, _) in enumerate(loadout_structure):
        try:
            v = int(app.loadout_entries[i].get())
        except ValueError:
            v = 0
        if v == -1:  # -1 is the display-friendly form of the 0xFFFFFFFF unused-slot sentinel
            v = LOADOUT_UNUSED_SLOT_RAW
        struct.pack_into(fmt, data, offset, v)
    # Save color data for both players: flush the active UI group into app.color_data_cache first, then write every cached player's set out.
    if hasattr(app, 'color_data_cache'):
        if hasattr(app, 'flush_color_ui_to_cache'):
            app.flush_color_ui_to_cache()
        active_slot = getattr(app, 'color_player_slot', 1)
        if hasattr(app, 'color_data'):
            app.color_data_cache[active_slot] = app.color_data
        for player, groups in app.color_data_cache.items():
            save_all_color_groups(data, groups, player=player, game=save_game)
    elif hasattr(app, 'color_data'):
        # Fallback if the cache dict never got built - still save app.color_data as Player 1.
        if hasattr(app, 'flush_color_ui_to_cache'):
            app.flush_color_ui_to_cache()
        save_all_color_groups(data, app.color_data, player=1, game=save_game)
    # Save weapon table: row[2] is the low-byte condition value; reassemble the full uint32 by OR-ing with the cached upper "overflow" bytes.
    weapon_data = app.weapon_data
    condition_upper = getattr(app, 'weapon_condition_upper', {})
    if _game_is_edf41(save_game):
        # EDF4.1 has a single ownership uint32 per weapon (no stats tail), same round-trip pattern.
        for r, row in enumerate(weapon_data):
            offset = EDF41_WEAPON_TABLE_BASE + r * EDF41_WEAPON_TABLE_STRIDE
            if offset + 4 > len(data):
                break  # Don't save beyond file size
            try:
                condition_display = int(row[2]) & 0xFF
            except (ValueError, TypeError):
                continue  # Skip invalid rows
            condition_raw = condition_upper.get(r, 0) | condition_display
            struct.pack_into("<I", data, offset, condition_raw)
    else:
        weapon_table_base = get_weapon_table_base(save_game)
        for r, row in enumerate(weapon_data):
            offset = weapon_table_base + r * 12
            if offset + 12 > len(data):
                break  # Don't save beyond file size
            try:
                condition_display = int(row[2]) & 0xFF
                stats = bytes([int(s) for s in row[3:11]])
            except ValueError:
                continue  # Skip invalid rows
            condition_raw = condition_upper.get(r, 0) | condition_display
            struct.pack_into("<I", data, offset, condition_raw)
            data[offset+4:offset+12] = stats
    # Save mission data for every game/DLC mission table in app.mission_table_cache, not just the active selection - otherwise editing multiple DLCs then saving once would drop all but the last.
    active_game = getattr(app, 'current_game', 'EDF6')
    active_slot = getattr(app, 'mission_player_slot', 1)
    cache = getattr(app, 'mission_table_cache', None)
    if cache:
        # Flush the currently-displayed table's live edits into its own cache slot first.
        if active_game in cache and hasattr(app, 'mission_arrays'):
            cache[active_game].setdefault('slots', {})[active_slot] = [bytearray(a) for a in app.mission_arrays]
        written_files = set()  # Online/Offline siblings can alias the same physical .MST - don't write it twice
        for game_key, entry in cache.items():
            mst_file = entry.get('mst_file')
            slots = entry.get('slots', {})
            if not mst_file or not slots or mst_file in written_files:
                continue
            written_files.add(mst_file)
            try:
                mst_data = bytearray(_load_game_file(app, mst_file))
            except Exception as e:
                print(f"Warning: could not re-read {mst_file} for saving ({game_key}): {e}")
                continue
            for slot, arrays in slots.items():
                save_mission_arrays_for_slot(mst_data, arrays, slot, game=game_key)
            _save_game_file(app, mst_file, mst_data)
    elif hasattr(app, 'current_mst_file') and app.current_mst_file:
        # Fallback if mission_table_cache was never built, to avoid silently saving nothing.
        mst_data = bytearray(_load_game_file(app, app.current_mst_file))
        save_mission_arrays_for_slot(mst_data, app.mission_arrays, active_slot, game=active_game)
        _save_game_file(app, app.current_mst_file, mst_data)
    # Save achievements to TROPHY.DAT, reusing the exact key/iv/encrypted-flag established at load time and recomputing its CRC32C checksum before re-encrypting (EDF4.1 uses its own fixed-key cipher + plain CRC-32 instead).
    if hasattr(app, 'current_trophy_file') and app.current_trophy_file:
        game = getattr(app, 'current_game', 'EDF6')
        trophy_is_edf41 = getattr(app, 'trophy_is_edf41', False)
        crc_body_start = 0x20 if str(game).upper().startswith('EDF5') else 0x14
        achievement_edf5_shift = 0xC if _game_is_edf5(game) else 0  # EDF5 shift unverified (3-game audit, 2026-09-07); irrelevant for EDF4.1 since its achievement_data is skipped entirely below (derived, not stored - see the matching load-side comment)
        with open(app.current_trophy_file, 'rb') as f:
            raw_trophy = f.read()
        trophy_key = getattr(app, 'trophy_key', None)
        trophy_iv = getattr(app, 'trophy_iv', None)
        trophy_encrypted = getattr(app, 'trophy_encrypted', False) and (
            trophy_is_edf41 or (trophy_key is not None and trophy_iv is not None)
        )
        if trophy_encrypted:
            if trophy_is_edf41:
                trophy_data = bytearray(edf41_decrypt(raw_trophy))
            else:
                trophy_data = bytearray(aes_ctr_decrypt(raw_trophy, trophy_key, trophy_iv))
        else:
            trophy_data = bytearray(raw_trophy)
        if not _game_is_edf41(game):
            # EDF4.1 skips this entirely: app.achievement_data holds DERIVED unlock status (computed
            # from the counters in app.kill_fields via compute_edf41_achievement_status), not a
            # separate stored byte-per-achievement flag - there's nothing here to write back. The
            # underlying counters themselves still round-trip normally via write_kill_fields below.
            for idx, row in enumerate(app.achievement_data):
                if idx < 32:
                    offset = 0x14 + achievement_edf5_shift + idx
                else:
                    offset = 0x34 + achievement_edf5_shift + (idx - 32)
                unlocked = 1 if row[2] else 0
                if offset < len(trophy_data):
                    trophy_data[offset] = unlocked
        # Override *ClearRatio keys with freshly-computed values before writing back - never trust
        # whatever extract_kill_fields() read for them (see compute_clear_ratios()'s module comment).
        kf_to_write = dict(getattr(app, 'kill_fields', {}))
        kf_to_write.update(compute_clear_ratios(getattr(app, 'mission_arrays', None), getattr(app, 'total_missions', 0), game))
        write_kill_fields(trophy_data, kf_to_write, get_kill_fields_table(game))
        # Keep TOTAL_ARMOR_POINTS_OFFSET in sync with the Armor tab (EDF6: single summed int).
        if _game_is_edf6(game) and armor_values:
            total_armor_points = sum(armor_values)
            if TOTAL_ARMOR_POINTS_OFFSET + 4 <= len(trophy_data):
                struct.pack_into("<I", trophy_data, TOTAL_ARMOR_POINTS_OFFSET, total_armor_points)
        # EDF5: each class gets its own recomputed "Base Game Gain" float32.
        elif _game_is_edf5(game) and armor_values:
            for i, (_, _, _, label, calc) in enumerate(armor_structure):
                gain_offset = EDF5_TROPHY_ARMOR_GAIN_OFFSETS.get(label)
                if gain_offset is None or gain_offset + 4 > len(trophy_data):
                    continue
                base_gain = calc(armor_values[i], 1.0)["Base Game Gain"]
                struct.pack_into("<f", trophy_data, gain_offset, base_gain)
        elif _game_is_edf41(game):
            # EDF4.1: armor_structure is [], so read app.armor_entries directly as floats and write into trophy_data - the single source of truth for EDF4.1 armor.
            for i, label in enumerate(("Ranger Armor", "Wingdiver Armor", "Air Raider Armor", "Fencer Armor")):
                if i >= len(app.armor_entries):
                    break
                offset = EDF41_TROPHY_ARMOR_OFFSETS.get(label)
                if offset is None or offset + 4 > len(trophy_data):
                    continue
                try:
                    v = float(app.armor_entries[i].get())
                except ValueError:
                    continue
                struct.pack_into("<f", trophy_data, offset, v)
        # Same backup chokepoint every other save file goes through (_save_game_file ->
        # _backup_before_overwrite) - TROPHY.DAT used to bypass it via a raw open()/write() here,
        # so achievement/trophy edits had no safety-net backup unlike GST/MST/CFG. Called once,
        # right before either write branch below, matching _save_game_file's own placement.
        _backup_before_overwrite(app.current_trophy_file)
        if trophy_encrypted:
            if trophy_is_edf41:
                if len(trophy_data) >= 0x18:
                    checksum = zlib.crc32(bytes(trophy_data[0x18:])) & 0xFFFFFFFF
                    struct.pack_into("<I", trophy_data, 0x0C, checksum)
                ciphertext = edf41_encrypt(bytes(trophy_data))
            else:
                if len(trophy_data) >= crc_body_start:
                    crc = crc32c(bytes(trophy_data[crc_body_start:]))
                    checksum = ~crc & 0xFFFFFFFF
                    struct.pack_into("<I", trophy_data, 0x0C, checksum)
                ciphertext = aes_ctr_encrypt(bytes(trophy_data), trophy_key, trophy_iv)
            with open(app.current_trophy_file, 'wb') as f:
                f.write(ciphertext)
        else:
            # Genuinely plain - no working decrypt candidate at load time - write back as plain.
            with open(app.current_trophy_file, 'wb') as f:
                f.write(trophy_data)

    # Save the modified GST data back to file
    _save_game_file(app, file, data)

    # Save Key Config edits: COMMON.CFG is a separate file, so this is its own read-modify-write step; a no-op if app.keybind_data is empty.
    if (_game_is_edf5(save_game) or _game_is_edf6(save_game) or _game_is_edf41(save_game)) and getattr(app, 'keybind_data', None):
        try:
            save_common_cfg_keybinds(app, app.keybind_data)
        except Exception as e:
            print(f"Error saving Key Config data: {e}")
    # Save controller Key Config edits, same self-contained shape as the keyboard save above.
    if (_game_is_edf5(save_game) or _game_is_edf6(save_game) or _game_is_edf41(save_game)) and getattr(app, 'controller_keybind_data', None):
        try:
            save_common_cfg_controller_keybinds(app, app.controller_keybind_data)
        except Exception as e:
            print(f"Error saving controller Key Config data: {e}")

def _read_modded_start_entry(app, i, vanilla_default):
    """Read app.armor_modded_start_entries[i] (the per-class 'Modded Starting AP' field added
    2026-09-07), falling back to that class's real vanilla constant if the widget doesn't exist
    yet (older UI build) or its text doesn't parse - callers pass that as `modded_start` to a
    calc() so "Modded Armor Gain" reflects a modded game's real starting AP instead of always
    assuming vanilla's."""
    entries = getattr(app, 'armor_modded_start_entries', None)
    if not entries or i >= len(entries):
        return vanilla_default
    try:
        return float(entries[i].get())
    except (ValueError, TypeError):
        return vanilla_default

def _read_modded_rate_entry(app, i, vanilla_default):
    """Same as _read_modded_start_entry above, but for the 'Modded Growth Rate' field added
    2026-09-07 alongside the Armor tab's card refactor - feeds `modded_rate` to a calc() so
    "Modded Armor Gain" reflects a modded game's real per-class growth rate."""
    entries = getattr(app, 'armor_modded_rate_entries', None)
    if not entries or i >= len(entries):
        return vanilla_default
    try:
        return float(entries[i].get())
    except (ValueError, TypeError):
        return vanilla_default

def update_displays(app):
    try:
        mg = float(app.modded_gain_entry.get())
    except ValueError:
        mg = 1.0
    current_game = getattr(app, 'current_game', 'EDF6')
    if _game_is_edf41(current_game):
        # EDF4.1: get_armor_structure() returns [], so use EDF41_ARMOR_CALC instead (same preview labels, different `v` meaning).
        for i, label in enumerate(("Ranger Armor", "Wingdiver Armor", "Air Raider Armor", "Fencer Armor")):
            if i >= len(app.armor_entries):
                break
            try:
                v = float(app.armor_entries[i].get())
            except ValueError:
                v = 0.0
            modded_start = _read_modded_start_entry(app, i, EDF41_ARMOR_STARTING_TOTALS[label])
            modded_rate = _read_modded_rate_entry(app, i, get_vanilla_armor_rate(current_game, label))
            results = EDF41_ARMOR_CALC[label](v, mg, modded_start, modded_rate)
            app.base_gain_labels[i].configure(text=f"Base Game Gain: {results['Base Game Gain']}")
            app.modded_gain_labels[i].configure(text=f"Modded Armor Gain: {results['Modded Armor Gain']}")
        return
    armor_structure = get_armor_structure(current_game)
    for i, (_, _, _, label, calc) in enumerate(armor_structure):
        try:
            v = int(app.armor_entries[i].get())
        except ValueError:
            v = 0
        modded_start = _read_modded_start_entry(app, i, EDF41_ARMOR_STARTING_TOTALS.get(label, 0))
        modded_rate = _read_modded_rate_entry(app, i, get_vanilla_armor_rate(current_game, label))
        results = calc(v, mg, modded_start, modded_rate)
        app.base_gain_labels[i].configure(text=f"Base Game Gain: {results['Base Game Gain']}")
        app.modded_gain_labels[i].configure(text=f"Modded Armor Gain: {results['Modded Armor Gain']}")