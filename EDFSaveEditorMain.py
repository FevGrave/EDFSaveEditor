# EDFSaveEditorMain.py
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from tkinter import colorchooser
import json, sys, os, math
from tksheet import Sheet
from EDFSaveEditorLogic import *
from EDFSaveEditorLogic import _load_game_file, _extract_mission_arrays, _game_is_edf5, _game_is_edf6, _game_is_edf41, _backup_before_overwrite
from EDFSaveEditorSave_Handler import *
import EDFWeaponFarming as wf
import EDFSaveEditorPS_SaveHandler as ps_saves

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def is_frozen():
    return getattr(sys, 'frozen', False)

def _resource_base():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS  # type: ignore
    return os.path.abspath(os.path.dirname(__file__))

def resource_path(name: str) -> str:
    return os.path.join(_resource_base(), name)

def _register_bundled_font():
    """Register fonts/RobotoCondensed-Bold.ttf as a private, process-only font (Windows AddFontResourceExW) so Tk can address it by family name; degrades silently to the system default on failure or on non-Windows."""
    ttf_path = resource_path(os.path.join('fonts', 'RobotoCondensed-Bold.ttf'))
    try:
        if sys.platform == 'win32' and os.path.isfile(ttf_path):
            import ctypes
            FR_PRIVATE = 0x10
            ctypes.windll.gdi32.AddFontResourceExW(ttf_path, FR_PRIVATE, 0)
    except Exception:
        pass

_register_bundled_font()

# Two-tier font scheme, both sizes using the bundled Roboto Condensed Bold face: FONT_FAMILY/BASE_FONT_SIZE for body text, HEADER_FONT_SIZE for section/tab headers.
FONT_FAMILY = "Roboto Condensed"
BASE_FONT_SIZE = 13
HEADER_FONT_SIZE = 15

# Separate, smaller sizing for dense data grids (tksheet Sheets + ttk Treeview) - the app-wide 13/15 scheme makes rows/columns too tall/wide for tables like Mission/Achievements/Kills. 11 is what fits all 15 mission rows in the fixed-height sheet.
TABLE_FONT_SIZE = 11
TABLE_HEADER_FONT_SIZE = 13

# Shared "this is the active/highlighted thing" style - active mission class label, Unlock Legend box.
ACTIVE_HIGHLIGHT_BG = "#f0c419"
ACTIVE_HIGHLIGHT_FG = "black"

# Global default font: overrides customtkinter's ThemeManager default so every widget without an explicit font= gets FONT_FAMILY/BASE_FONT_SIZE.
ctk.ThemeManager.theme["CTkFont"] = {"family": FONT_FAMILY, "size": BASE_FONT_SIZE, "weight": "normal"}

def _app_dir() -> str:
    """Directory for persistent files like config.json: the exe's own folder when frozen (not the temp _MEIPASS extraction folder), else the script's folder."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.dirname(__file__))

CONFIG_PATH = os.path.join(_app_dir(), 'config.json')

# Translation-data files (languages.json / WeaponNamesLang.json / MissionNames.json): writes must
# go through the exe-adjacent folder, not the frozen temp-extract folder, or edits vanish on exit.
def translation_data_path(name: str) -> str:
    """Where the Translation Editor should WRITE - always the exe-adjacent folder."""
    return os.path.join(_app_dir(), name)

def resolved_translation_path(name: str) -> str:
    """Where to READ a translation-data file from: an exe-adjacent saved copy if one exists, else the bundled resource copy."""
    app_dir_copy = translation_data_path(name)
    return app_dir_copy if os.path.exists(app_dir_copy) else resource_path(name)

def load_translation_data(name: str, default):
    return load_json_safe(resolved_translation_path(name), default)
DIFFICULTY_BITS = [0x01, 0x02, 0x04, 0x08, 0x10] # Easy 01, Normal 02, Hard 04, Very Hard 08, Inferno 10 hex values to add up to the byte total representing unlocked difficulties for a mission.
EDF_SAVE_FOLDER_NAMES = {
    'EDF6': ['EarthDefenceForce6', 'EDF6ModdedSaves'],
    'EDF5': ['EARTH DEFENSE FORCE 5', 'EDF5', 'EDF5_MODSAVES'],
    'EDF4.1': ['EDF4.1', 'EDF4.M'],
}
SAVE_PATHS_LABEL_WIDTH = 210
ARMOR_CLASS_LABEL_WIDTH = 190
ARMOR_BASE_GAIN_LABEL_WIDTH = 150
WEAPON_OWNED_CONDITION = 3

# Per-game "Own All"/"Poverty" protected weapon IDs - each game has its own independent roster, so
# EDF6's list can't be reused for EDF4.1/EDF5. Protects two things: "Poverty" won't strip these (so
# it can't leave a starter-required slot empty), and "Own All" granting them is at least consistent
# with what a real single-DLC purchase unlocks, not a blanket "everything" flip. FevGrave 2026-09-07:
# the game itself still enforces its own DLC ownership check before letting a weapon actually be
# equipped, for every game here - so Own All granting one of these when the DLC isn't owned doesn't
# functionally unlock it in-game, but it's still worth keeping the save's ownership flags honest.
EDF6_PROTECTED_IDS = {0,46,77,109,165,225,305,384,385,462,534,584,597,619,654,690,715,747,771,866,867,1041,1042,1080,1095,1124,1163,1174,1206,1262}
EDF6_PROTECTED_RANGES = [(1346,1362),(1561,1563)]
# Single-DLC weapon-pack IDs (per-weapon Steam DLC, not the 2 mission-pack DLCs) - matches
# EDF41_DLC_WEAPON_INDICES' own keys exactly, minus 101/377 (Genocide Gun/Armageddon Cluster: real
# level-100 bonus unlocks, not from a Steam DLC pack, so they're not ownership-gated the same way).
# Derived from that table rather than re-listed here so the two can't drift out of sync.
# Ground-truth verified 2026-09-08: decrypted 16 real single-weapon-DLC "addon:/Config.sgo" files
# (Ghidra RE of EDF41.exe FUN_1400d2360/FUN_1400d5360 -> key = _edf41_seed("edf4.1_dlc"), iv =
# _edf41_seed("edf4.1"), same scheme as save files with a different key seed). Every "unlock_weapon"
# entry found in those 16 files' own game data resolved to a name already in this set - independent
# confirmation from the game's own DLC manifests, not just internal cross-referencing.
EDF41_PROTECTED_IDS = set(EDF41_DLC_WEAPON_INDICES.keys()) - {101, 377}
# EDF4.1's 2 mission-pack DLCs (appid 410780 = MP01, 411380 = MP02) resolved 2026-09-08: their
# unpacked dlc.cpk trees were inspected directly (Config2.sgo -> PACKAGE.sgo, both already had
# decoded .json siblings on disk, no decryption needed). PACKAGE.sgo's WeaponTable/WeaponText point
# at the base game's own app:/Weapon/_WeaponTable.sgo, and SoldierInit only lists the vanilla starter
# loadout (AssultRifle01, RocketLauncher01, pRapier01, etc) - neither mission pack defines an
# unlock_weapon list at all (unlike each of the 16 single-weapon DLCs, which each had exactly one).
# They only add missions/enemies (Mission/M*, Object/GiantAnt04 etc). Confirmed: no weapon ids to add.
EDF41_PROTECTED_RANGES = []
# Single-DLC weapon-pack IDs (per-weapon Steam DLC).
EDF5_PROTECTED_IDS = {248,249,250,251,252,253,254,255,256,289,295,304,305,532,533,553,588,639,788,955,1023,1024,1025,1026,1027,1028,1029,1030,1032,1033,1074,1094}
# EDF5's 2 mission-pack DLCs, pulled straight from WeaponNamesLang.json's EDF5 weapon_meta table:
# each entry's "sgo" filename and "pack" field agree exactly, so these ranges are read off the game's
# own data, not guessed. MP1 = EX_A_Weapon001-034.sgo (pack:1) = ids 1114-1147. MP2 = EX_B_Weapon001-
# 039.sgo (pack:2) = ids 1148-1186. Both ranges are contiguous with no gaps or foreign ids mixed in.
EDF5_PROTECTED_RANGES = [(1114,1147),(1148,1186)]

def load_json_safe(path: str, fallback):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return fallback

class SaveEditor(ctk.CTk):
    # --- Core helpers & lifecycle ---
    def _warn(self, e, context=None):
        """Print a debug warning for a caught-and-suppressed exception, using the caller's real dynamically-captured source line instead of a hardcoded one."""
        frame = sys._getframe(1)
        where = f"{context} " if context else ""
        print(f"[WARN] {where}(EDFSaveEditorMain.py:{frame.f_lineno}): {e}")

    def _trans_dict(self):
        """The current language's translation dict, falling back to English if the current language code somehow isn't a key."""
        return self.translations.get(self.current_language, self.translations.get('en', {}))

    def tr(self, key, default=None):
        """Safe translated-string lookup: key -> current language -> English -> `default` if given -> the key itself. The English fallback lets languages.json stay lean, since a partial language file only needs to override the keys it translates."""
        val = self._trans_dict().get(key)
        if val is not None:
            return val
        en_val = self.translations.get('en', {}).get(key)
        if en_val is not None:
            return en_val
        return default if default is not None else key

    def _fit_text_button_width(self, text, min_width=140, padding=36):
        """Pixel-measure `text` at runtime via Tk's own font metrics and return a width comfortably wider than needed, so short languages stay compact instead of every language paying for a hardcoded worst-case width. Falls back to a character-count estimate if Tk font measurement isn't available."""
        try:
            import tkinter.font as tkfont
            measured = tkfont.Font(size=13).measure(text)
        except Exception:
            measured = len(text) * 16
        return max(min_width, measured + padding)

    def _mission_button_col_widths(self):
        """One shared width for every Unlock button and one for every Reset button (max needed across all 5 difficulties in the current language), so the mission-table button column lines up instead of each button being sized to its own text."""
        diffs = getattr(self, 'mission_diffs', None) or [
            self.tr('mission_table_col_easy'), self.tr('mission_table_col_normal'),
            self.tr('mission_table_col_hard'), self.tr('mission_table_col_hardest'),
            self.tr('mission_table_col_inferno'),
        ]
        unlock_w = max(self._fit_text_button_width(self.tr('unlock_button').format(difficulty=d)) for d in diffs)
        reset_w = max(self._fit_text_button_width(self.tr('reset_button').format(difficulty=d)) for d in diffs)
        return unlock_w, reset_w

    def _redraw_mission_btn_scroll(self):
        """Force self.mission_btn_scroll's backing canvas to fully repaint, fixing a ghost-pixel bug when a shrinking button leaves stale canvas pixels behind."""
        try:
            self.mission_btn_scroll.update_idletasks()
            canvas = getattr(self.mission_btn_scroll, '_parent_canvas', None)
            if canvas is not None:
                # Nudging the scrollregion forces a full canvas repaint, cheaper than recreating every button.
                bbox = canvas.bbox("all")
                if bbox:
                    canvas.configure(scrollregion=bbox)
                canvas.update_idletasks()
        except Exception:
            pass

    def _fit_mission_name_col_width(self, min_width=260, max_width=560, padding=24):
        """Measure the widest mission-name string in the sheet's column 0 (via tksheet's own text-width measurer) and return a comfortable width clamped to [min_width, max_width], falling back to min_width if unavailable."""
        widest = 0
        texts = []
        try:
            rows = self.sheet.get_sheet_data(only_columns=0)
            texts.extend(r[0] for r in rows if r)
        except Exception:
            pass
        try:
            header = self.sheet.headers()
            if header:
                texts.append(header[0])
        except Exception:
            pass
        for text in texts:
            text = str(text)
            w = None
            try:
                w = self.sheet.MT.get_txt_w(text)
            except Exception:
                try:
                    import tkinter.font as tkfont
                    w = tkfont.Font(size=11).measure(text)
                except Exception:
                    w = len(text) * 9
            if w:
                widest = max(widest, w)
        if widest <= 0:
            return min_width
        return max(min_width, min(max_width, widest + padding))

    # Canonical-value -> translation-key maps for dropdowns whose bound StringVar stays English but whose on-screen text should translate.
    _COLOR_CLASS_LABEL_KEYS = {
        "Ranger": 'mission_table_col_ranger',
        "Wingdiver": 'mission_table_col_wingdiver',
        "Air Raider": 'mission_table_col_airraider',
        "Fencer": 'mission_table_col_fencer',
    }
    _COLOR_TIER_LABEL_KEYS = {
        "Soldier": 'color_tier_soldier',
        "Civilian": 'color_tier_civilian',
        "Devastation": 'color_tier_devastation',
        "Up-and-Coming": 'color_tier_upandcoming',
    }
    # Key Config category labels - the 4 soldier classes reuse the mission table's translation keys; the 6 vehicle categories have no existing key and fall back to plain English.
    _KEYCONFIG_CATEGORY_LABEL_KEYS = {
        "Common": 'keyconfig_category_common',
        "Ranger": 'mission_table_col_ranger',
        "Wing Diver": 'mission_table_col_wingdiver',
        "Air Raider": 'mission_table_col_airraider',
        "Fencer": 'mission_table_col_fencer',
        "Drive": 'keyconfig_category_drive',
        "Tanks": 'keyconfig_category_tanks',
        "Heli": 'keyconfig_category_heli',
        "Combat": 'keyconfig_category_combat',
        "Barga": 'keyconfig_category_barga',
        "Depth": 'keyconfig_category_depth',
    }

    # Categories whose real in-game display name differs between EDF5 and EDF6 (confirmed via TEXTTABLE_STEAM.EN.TXT.json); every other category name is shared as-is.
    _KEYCONFIG_CATEGORY_LABEL_KEYS_EDF6 = {
        "Drive": ('keyconfig_category_drive_edf6', "Vehicle (B)"),
        "Tanks": ('keyconfig_category_tanks_edf6', "Combat Vehicle"),
        "Combat": ('keyconfig_category_combat_edf6', "Combat Frame"),
    }

    # EDF4.1's internal "Solder" category keeps its name for offset continuity, but the real in-game screen just says "Controls" - displayed here as "Common Controls" to match EDF5/6's naming convention.
    _KEYCONFIG_CATEGORY_LABEL_KEYS_EDF41 = {
        "Solder": ('keyconfig_category_solder_edf41', "Common Controls"),
    }

    def _keyconfig_category_label(self, canonical):
        game = getattr(self, 'current_game', 'EDF6')
        if _game_is_edf41(game) and canonical in self._KEYCONFIG_CATEGORY_LABEL_KEYS_EDF41:
            tr_key, fallback = self._KEYCONFIG_CATEGORY_LABEL_KEYS_EDF41[canonical]
            return self.tr(tr_key, fallback)
        if _game_is_edf6(game) and canonical in self._KEYCONFIG_CATEGORY_LABEL_KEYS_EDF6:
            tr_key, fallback = self._KEYCONFIG_CATEGORY_LABEL_KEYS_EDF6[canonical]
            return self.tr(tr_key, fallback)
        key = self._KEYCONFIG_CATEGORY_LABEL_KEYS.get(canonical)
        return self.tr(key, canonical) if key else canonical

    # Maps each raw per-row Key Config action name (e.g. "Attack", "Jump") to its translation key, same tr(key, fallback) pattern as _keyconfig_category_label.
    _KEYCONFIG_ACTION_LABEL_KEYS = {
        '(unused slot 8)': 'keyconfig_action_unused_slot_8',
        '(unused slot 9)': 'keyconfig_action_unused_slot_9',
        'Accelerate': 'keyconfig_action_accelerate',
        'Attack': 'keyconfig_action_attack',
        'Attack - L.Hand': 'keyconfig_action_attack_l_hand',
        'Attack - L.Shldr': 'keyconfig_action_attack_l_shldr',
        'Attack - L.Stomp': 'keyconfig_action_attack_l_stomp',
        'Attack - Left': 'keyconfig_action_attack_left',
        'Attack - Left Hand': 'keyconfig_action_attack_left_hand',
        'Attack - Left Shoulder': 'keyconfig_action_attack_left_shoulder',
        'Attack - R.Hand': 'keyconfig_action_attack_r_hand',
        'Attack - R.Shldr': 'keyconfig_action_attack_r_shldr',
        'Attack - R.Stomp': 'keyconfig_action_attack_r_stomp',
        'Attack - Right': 'keyconfig_action_attack_right',
        'Attack - Right Hand': 'keyconfig_action_attack_right_hand',
        'Attack - Right Shoulder': 'keyconfig_action_attack_right_shoulder',
        'Attack 1': 'keyconfig_action_attack_1',
        'Attack 2': 'keyconfig_action_attack_2',
        'Attack1': 'keyconfig_action_attack1',
        'Attack2': 'keyconfig_action_attack2',
        'Avoidance': 'keyconfig_action_avoidance',
        'Board / Rescue': 'keyconfig_action_board_rescue',
        'Bombard - Left': 'keyconfig_action_bombard_left',
        'Bombard - Right': 'keyconfig_action_bombard_right',
        'Boost': 'keyconfig_action_boost',
        'Brake': 'keyconfig_action_brake',
        'Brake/Back': 'keyconfig_action_brake_back',
        'Call Vehicles': 'keyconfig_action_call_vehicles',
        'Canned Text Shortcut': 'keyconfig_action_canned_text_shortcut',
        'Chat Shortcuts': 'keyconfig_action_chat_shortcuts',
        'Chat Window': 'keyconfig_action_chat_window',
        'Dash': 'keyconfig_action_dash',
        'Emergency Avoidance': 'keyconfig_action_emergency_avoidance',
        'Flight': 'keyconfig_action_flight',
        'Fly': 'keyconfig_action_fly',
        'Gatling': 'keyconfig_action_gatling',
        'Hand Brake': 'keyconfig_action_hand_brake',
        'Handbrake': 'keyconfig_action_handbrake',
        'Horn': 'keyconfig_action_horn',
        'Jump': 'keyconfig_action_jump',
        'Location Marking': 'keyconfig_action_location_marking',
        'Move - Back': 'keyconfig_action_move_back',
        'Move - Front': 'keyconfig_action_move_front',
        'Move - Left': 'keyconfig_action_move_left',
        'Move - Right': 'keyconfig_action_move_right',
        'Punch - Left Hand': 'keyconfig_action_punch_left_hand',
        'Punch - Right Hand': 'keyconfig_action_punch_right_hand',
        'Reload': 'keyconfig_action_reload',
        'Reload Shield': 'keyconfig_action_reload_shield',
        'Rescue / Ride': 'keyconfig_action_rescue_ride',
        'Shield Reload': 'keyconfig_action_shield_reload',
        'Special Attacks': 'keyconfig_action_special_attacks',
        'Special Pose': 'keyconfig_action_special_pose',
        'Spot': 'keyconfig_action_spot',
        'Sprint': 'keyconfig_action_sprint',
        'Stamp - Left Foot': 'keyconfig_action_stamp_left_foot',
        'Stamp - Right Foot': 'keyconfig_action_stamp_right_foot',
        'Summon Vehicle': 'keyconfig_action_summon_vehicle',
        'Switch Weapons': 'keyconfig_action_switch_weapons',
        'Use - L.Hand': 'keyconfig_action_use_l_hand',
        'Use - R.Hand': 'keyconfig_action_use_r_hand',
        'Use Backpack Tool': 'keyconfig_action_use_backpack_tool',
        'Use Backpack Tools': 'keyconfig_action_use_backpack_tools',
        'Use Equipment - Left Hand': 'keyconfig_action_use_equipment_left_hand',
        'Use Equipment - Right Hand': 'keyconfig_action_use_equipment_right_hand',
        'Use Independently Operated Equipment': 'keyconfig_action_use_independently_operated_equipment',
        'Vehicle/Rescue': 'keyconfig_action_vehicle_rescue',
        'Voice Chat': 'keyconfig_action_voice_chat',
        'Weapon Shortcut 1': 'keyconfig_action_weapon_shortcut_1',
        'Weapon Shortcut 2': 'keyconfig_action_weapon_shortcut_2',
        'Weapon Shortcut 3': 'keyconfig_action_weapon_shortcut_3',
        'Zoom/Activate': 'keyconfig_action_zoom_activate',
    }

    def _keyconfig_action_label(self, canonical):
        key = self._KEYCONFIG_ACTION_LABEL_KEYS.get(canonical)
        return self.tr(key, canonical) if key else canonical

    _MISSION_DIFF_LABEL_KEYS = {
        "Easy": 'mission_table_col_easy',
        "Normal": 'mission_table_col_normal',
        "Hard": 'mission_table_col_hard',
        "Hardest": 'mission_table_col_hardest',
        "Inferno": 'mission_table_col_inferno',
    }

    def _color_class_label(self, canonical):
        key = self._COLOR_CLASS_LABEL_KEYS.get(canonical)
        return self.tr(key, canonical) if key else canonical

    def _color_tier_label(self, canonical):
        """Return the display label for a COLOR_TIERS canonical value; `canonical` stays fixed for indexing/storage, but the displayed text swaps to get_color_tiers(self.current_game)'s label at the same position (e.g. EDF5's tier_idx 2 shows "Unused (Devastation) Slot")."""
        game = getattr(self, 'current_game', 'EDF6')
        try:
            idx = COLOR_TIERS.index(canonical)
            game_label = get_color_tiers(game)[idx]
        except (ValueError, IndexError):
            game_label = canonical
        key = self._COLOR_TIER_LABEL_KEYS.get(game_label)
        return self.tr(key, game_label) if key else game_label

    def _mission_diff_label(self, canonical):
        """Reuses the mission table's own mission_table_col_<difficulty> keys - this is the
        SAME set of difficulty names as the mission table and Boring Missions List, so it
        deliberately doesn't duplicate them under new weapon_farming_* keys."""
        key = self._MISSION_DIFF_LABEL_KEYS.get(canonical)
        return self.tr(key, canonical) if key else canonical

    def __init__(self):
        super().__init__()
        # Initialize language_var early
        self.language_var = ctk.StringVar(value="English")
        # Add current_theme default before loading config
        self.current_theme = 'dark'
        self.current_language = 'en'  # Default language
        self.current_game = "EDF6"  # For future expansion
        # Load translations - prefers an exe-adjacent copy (earlier saved edits) over the
        # bundled resource copy, see resolved_translation_path()'s docstring.
        translations_raw = load_translation_data('languages.json', {})
        # Support both original and flattened structures
        if 'EDF6' in translations_raw and 'languages' in translations_raw.get('EDF6', {}):
            self.translations = translations_raw['EDF6']['languages']
        elif 'languages' in translations_raw:
            self.translations = translations_raw['languages']
        else:
            self.translations = {'en': {}}
        # Load weapon names for all languages/games
        self.weapon_names_lang = load_translation_data('WeaponNamesLang.json', {})
        # Load mission names for all languages/games
        self.mission_names_data = load_translation_data('MissionNames.json', {})
        # Weapon Farming Helper data: weapon_drop_data_by_game is per-weapon drop fields per game family; weapon_drop_curves is the per-mode/difficulty level-band curve, both read from WeaponNamesLang.json.
        self.weapon_drop_data_by_game = {}
        for game_key in ('EDF6', 'EDF5', 'EDF4.1'):
            try:
                self.weapon_drop_data_by_game[game_key] = wf.load_weapon_drop_data(
                    resolved_translation_path('WeaponNamesLang.json'), game_key=game_key)
            except Exception as e:
                self._warn(e, f'load_weapon_drop_data({game_key})')
                self.weapon_drop_data_by_game[game_key] = []
        self.weapon_drop_data = self.weapon_drop_data_by_game['EDF6']  # Back-compat alias for EDF6's list
        self.weapon_drop_curves = {}
        try:
            self.weapon_drop_curves.update(
                wf.load_drop_curves(resolved_translation_path('WeaponNamesLang.json')))
        except Exception as e:
            self._warn(e, 'load_drop_curves')
        try:
            self.weapon_drop_curves.update(
                wf.load_drop_curves(resolved_translation_path('WeaponNamesLang.json'),
                                     game_key='EDF5', modes=wf.EDF5_FARMING_SUBMODES))
        except Exception as e:
            self._warn(e, 'load_drop_curves(EDF5)')
        try:
            self.weapon_drop_curves.update(
                wf.load_drop_curves(resolved_translation_path('WeaponNamesLang.json'),
                                     game_key='EDF4.1', modes=wf.EDF41_FARMING_SUBMODES))
        except Exception as e:
            self._warn(e, 'load_drop_curves(EDF4.1)')
        # Remap EDF5/EDF4.1's compact JSON submode keys onto the display-string keys the UI looks up (EDF6's submode keys already match, no remap needed).
        for display_mode, (game_key, submode_key) in self.FARMING_MODE_INFO.items():
            if game_key in ('EDF5', 'EDF4.1') and submode_key in self.weapon_drop_curves:
                self.weapon_drop_curves[display_mode] = self.weapon_drop_curves.pop(submode_key)
        # Category id -> internal enum name, sourced from TEXTTABLE_STEAM.EN.TXT.json's SoldierWeaponCategory table; see _farming_category_label() for display formatting.
        self.weapon_category_names_by_game = {}
        for game_key in ('EDF6', 'EDF5', 'EDF4.1'):
            try:
                self.weapon_category_names_by_game[game_key] = wf.load_category_names(
                    resolved_translation_path('WeaponNamesLang.json'), game_key=game_key)
            except Exception as e:
                self._warn(e, f'load_category_names({game_key})')
                self.weapon_category_names_by_game[game_key] = {}
        self.weapon_category_names = self.weapon_category_names_by_game['EDF6']
        # Build language_map dynamically from translations
        self.language_map = {}
        for lang_code, lang_dict in self.translations.items():
            display_name = None
            # lang_dict may be a dict with several possible display-name keys
            if isinstance(lang_dict, dict):
                display_name = lang_dict.get('display_name') or lang_dict.get('name') or lang_dict.get(lang_code)
            # Fallback to the language code if no nicer name found
            if not display_name:
                display_name = lang_code
            # Persist a normalized display_name in the translations dict for future use
            try:
                if isinstance(self.translations.get(lang_code), dict):
                    self.translations[lang_code]['display_name'] = display_name
            except Exception as e:
                self._warn(e)
            self.language_map[lang_code] = display_name
        # Also build a reverse map for display name -> code
        self.language_map_reverse = {v: k for k, v in self.language_map.items()}

        # Config attribute defaults, initialized before load_config so it has something to merge into.
        self.config_data = {'language': 'en', 'theme': 'dark', 'modded_mission_totals': {}, 'boring_missions': {}, 'controller_display': 'xbox', 'weapon_limit_mods_dir': ''}  # In-memory config fallback; weapon_limit_mods_dir: WeaponLimit mod sidecar (.bin) support - path to the EDF6 install's "Mods" folder
        self.config_file_enabled = not is_frozen()
        # Load config after language_var is initialized
        self.load_config()
        # Apply loaded theme early
        try:
            ctk.set_appearance_mode(self.config_data.get('theme', 'dark'))
            self.current_theme = self.config_data.get('theme', 'dark')
        except Exception as e:
            self._warn(e)
        
        # After load_config ensure selector reflects language
        # (language_selector created later; store desired code)
        self._pending_language_code = self.current_language
        # Replace local version variable with instance attribute
        self.version = "--- V 1.1.0.1"
        self.title(self.tr('title') + " " + self.version)
        self.geometry("1320x960")
        # Window/taskbar icon while running; AppIcon.ico is optional and silently no-ops if absent. The .exe's own file icon is set separately at build time via --icon.
        try:
            icon_path = resource_path('AppIcon.ico')
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception as e:
            self._warn(e, 'set window icon')
        # Accordion registry for collapsible sections, used by _close_other_sections to enforce only one open at a time.
        self._collapsible_registry = []
        self.armor_entries = []
        self.armor_modded_start_entries = []
        self.armor_modded_rate_entries = []  # "Modded Growth Rate" per class, added alongside the 2026-09-07 card refactor - same pattern as armor_modded_start_entries
        self.base_gain_labels = []
        self.modded_gain_labels = []
        self.loadout_entries = []
        self.loadout_name_labels = []
        self.current_file = None
        self.weapon_data = []
        self.profile_name_label = None
        self.playtime_label = None

        self.mission_arrays = [bytearray(512) for _ in range(4)]

        self.mission_player_slot = 1
        self.mission_table_cache = {}
        self.color_player_slot = 1
        self.color_data_cache = {}
        self.current_page = 1
        self.missions_per_page = 14  # Fills the sheet's fixed height with real rows instead of blank padding
        self.total_missions = 147
        self.total_pages = self._recompute_total_pages()
        self.achievement_data = []
        percentages = list(range(5, 65, 5)) + list(range(62, 102, 2))
        for i in range(32):
            perc = percentages[i]
            name = f"Conquest{perc} (Made {perc}% game progress)"
            self.achievement_data.append([i, name, 0])
        other_names = [
            "Rescue (Rescued 5 other players in co-op play)",
            "Super Rescue (Rescued 50 other players in co-op play)",
            "Medic (Healed another player in co-op play)",
            "Master Ranger (Ranger’s health has reached 1000)",
            "Master Diver (Wing Diver’s health has reached 550)",
            "Master Air Raider (Air Raider’s health has reached 1000)",
            "Master Fencer (Fencer’s health has reached 1250)"
        ]
        for i in range(7):
            name = other_names[i]
            self.achievement_data.append([32 + i, name, 0])

        self.colors = ["#82baf2", "#81de81", "#f0d198", "#ff6565", "#c06bea"]
        self.text_colors = ["#000000", "#000000", "#000000", "#000000", "#000000"]

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.scrollable_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.scrollable_frame.grid(row=0, column=0, sticky="nsew")
        # Capture customtkinter's app-wide scroll bindings so _pause_global_scroll/_resume_global_scroll can temporarily disable and restore them over a nested scrollable table.
        self._global_scroll_bindings = {
            seq: self.scrollable_frame.bind_all(seq) or ""
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>")
        }

        header_frame = ctk.CTkFrame(self.scrollable_frame)
        header_frame.pack(side="top", fill="x", pady=5, padx=10)
        header_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        header_frame.grid_columnconfigure(5, weight=0)  # new column for language selector
        header_frame.grid_columnconfigure(6, weight=0)
        header_frame.grid_columnconfigure(7, weight=0)  # Save Sharing platform switch + action button (see save_share_frame)
        header_frame.grid_rowconfigure(0, weight=1)

        self.games_metadata = {
            # Placeholder: EDF6.2 (announced, unreleased) - coming_soon-gated, total_missions borrows EDF6's counts as an unconfirmed guess until the real game/save format exists.
            # Listed above EDF6 (newest game first) - this is display order only, NOT the default
            # selection: self.game_var below is still explicitly set to 'EDF6', unaffected by
            # dict order, so EDF6 stays what actually loads first.
            'EDF6.2':            {'total_missions': 147, 'missionlist': 'EDF6.2',     'missiontable': 'Unknown.MST',   'coming_soon': True, 'auto_unlock_missions': []},
            'EDF6.2 DLC1':       {'total_missions': 19,  'missionlist': 'EDF6.2DLC1', 'missiontable': 'Unknown.MST',   'coming_soon': True, 'auto_unlock_missions': []},
            'EDF6.2 DLC2':       {'total_missions': 40,  'missionlist': 'EDF6.2DLC2', 'missiontable': 'Unknown.MST',   'coming_soon': True, 'auto_unlock_missions': []},
            'EDF6':              {'total_missions': 147, 'missionlist': 'EDF6',       'missiontable': 'DEFP_M00.MST',                       'auto_unlock_missions': [1]},
            'EDF6 DLC1':         {'total_missions': 19,  'missionlist': 'EDF6DLC1',   'missiontable': 'DEFP_DLC1.MST', 'coming_soon': False, 'auto_unlock_missions': []},
            'EDF6 DLC2':         {'total_missions': 40,  'missionlist': 'EDF6DLC2',   'missiontable': 'DEFP_DLC2.MST', 'coming_soon': False, 'auto_unlock_missions': []},
            # EDF5: crypto/checksum layer confirmed fixed and verified against real saves; base Offline/Online, DLC1, and DLC2 are all un-gated. Mission-table filenames derived via Ghidra RE.
            'EDF5 Offline':      {'total_missions': 110, 'missionlist': 'EDF5',       'missiontable': 'DEFP_M00.MST',  'coming_soon': False, 'auto_unlock_missions': [1, 33, 37]},
            'EDF5 Offline DLC1': {'total_missions': 15,  'missionlist': 'EDF5DLC1',   'missiontable': 'DEFP_M02.MST',  'coming_soon': False, 'auto_unlock_missions': []},
            'EDF5 Offline DLC2': {'total_missions': 14,  'missionlist': 'EDF5DLC2',   'missiontable': 'DEFP_M04.MST',  'coming_soon': False, 'auto_unlock_missions': []},
            'EDF5 Online':       {'total_missions': 111, 'missionlist': 'EDF5ON',     'missiontable': 'DEFP_M01.MST',  'coming_soon': False, 'auto_unlock_missions': []},
            'EDF5 Online DLC1':  {'total_missions': 15,  'missionlist': 'EDF5ONDLC1', 'missiontable': 'DEFP_M03.MST',  'coming_soon': False, 'auto_unlock_missions': []},
            'EDF5 Online DLC2':  {'total_missions': 14,  'missionlist': 'EDF5ONDLC2', 'missiontable': 'DEFP_M05.MST',  'coming_soon': False, 'auto_unlock_missions': []},
            # EDF4.1 base/Offline mission table is DEFP_M00.MST, confirmed via byte-match against EDF_Cryptor.exe's reference decrypt; uses EDF4.1's fixed AES-CTR key/IV.
            'EDF4.1 Offline':    {'total_missions': 89,  'missionlist': 'EDF4.1',     'missiontable': 'DEFP_M00.MST',  'coming_soon': False, 'auto_unlock_missions': []},
            # MP01/MP02 are EDF4.1's 2 Mission Pack DLCs; total_missions cross-checked between MissionList.json and MissionText.json.
            'EDF4.1 Offline DLC1': {'total_missions': 26, 'missionlist': 'EDF4.1DLC1', 'missiontable': 'MP01_M00.MST', 'coming_soon': False, 'auto_unlock_missions': []},
            'EDF4.1 Offline DLC2': {'total_missions': 23, 'missionlist': 'EDF4.1DLC2', 'missiontable': 'MP02_M00.MST', 'coming_soon': False, 'auto_unlock_missions': []},
            # EDF4.1 Online mission table CONFIRMED 2026-09-06: DEFP_M01.MST, found sitting in a real save slot (saveslot03) alongside DEFP_M00.MST/MP01_M00.MST, same M00=Offline/M01=Online numbering EDF5 uses. Byte-decrypted with EDF4.1's fixed AES-CTR key/IV and read real Wing Diver progress through mission 93 (Normal/Hard/VeryHard/Inferno bits populated) - not template/zero data. total_missions=98 is still the pre-existing unverified figure (highest nonzero index seen was 93, but missions 94-98 being simply not-yet-played is consistent with that) - re-check if a save with full DLC/Online completion turns up.
            'EDF4.1 Online':     {'total_missions': 98,  'missionlist': 'EDF4.1ON',   'missiontable': 'DEFP_M01.MST',  'coming_soon': False, 'auto_unlock_missions': []},
            # EDF4.1 Online DLC1 mission table CONFIRMED 2026-09-06: MP01_M01.MST appeared in saveslot03 right after FevGrave played DLC1 online (didn't exist before - the game creates the Online variant on first online play, same as DEFP_M01.MST). Byte-decrypted with EDF4.1's fixed AES-CTR key/IV: valid MDB0 header, same 5928-byte size and layout as MP01_M00.MST, Wing Diver mission #1 = 0x01 (Easy) - matches the Offline file in the same slot exactly, confirming the M00=Offline/M01=Online numbering extends to the MP0N DLC packs as hypothesized.
            'EDF4.1 Online DLC1': {'total_missions': 26, 'missionlist': 'EDF4.1DLC1ON', 'missiontable': 'MP01_M01.MST', 'coming_soon': False, 'auto_unlock_missions': []},
            # EDF4.1 Online DLC2 mission table CONFIRMED 2026-09-06: MP02_M01.MST appeared in saveslot03 right after FevGrave played DLC2 online (didn't exist before, same generate-on-first-online-play behavior as MP01_M01.MST/DEFP_M01.MST - now 3-for-3). Byte-decrypted: valid MDB0 header, same 5928-byte size/layout as MP02_M00.MST, Wing Diver mission #1 = 0x01 (Easy) - independently tracked from the Offline file in the same slot, which has mission #1 = 0x02 (Normal). Different values on the same mission# confirms Online/Offline really are separate progress, not the same data duplicated.
            'EDF4.1 Online DLC2': {'total_missions': 23, 'missionlist': 'EDF4.1DLC2ON', 'missiontable': 'MP02_M01.MST', 'coming_soon': False, 'auto_unlock_missions': []},
        }
        # Internal mission list key used to look up MissionNames.json (maps UI entry -> data key)
        self.missionlist_key = self.games_metadata['EDF6'].get('missionlist', 'EDF6')
        self.game_var = ctk.StringVar(value='EDF6')
        self.previous_game = 'EDF6'
        self.game_selector = ctk.CTkOptionMenu(
            header_frame,
            values=list(self.games_metadata.keys()),
            variable=self.game_var,
            command=self.on_game_change
        )
        self.game_selector.grid(row=0, column=3, padx=5, sticky="e")
        try: self._colorize_game_selector_dropdown()
        except Exception as e:
            self._warn(e)
        try: self.update_default_save_dir()
        except Exception as e:
            self._warn(e)

        self.save_status_label = ctk.CTkLabel(header_frame, text="", font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"))
        self.save_status_label.grid(row=0, column=6, padx=10, sticky="e")

        # Save Sharing platform switch: PC is real and working (fixes the save-generation-ID mismatch); PS4 stays gated pending a real keystone+param.sfo sample; Xbox/Switch are unimplemented ideas.
        self.save_share_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        self.save_share_frame.grid(row=0, column=7, padx=10, sticky="e")
        self.save_share_platform_var = ctk.StringVar(value="PC")
        self.save_share_platform_menu = ctk.CTkSegmentedButton(
            self.save_share_frame,
            values=["PC", "PS4"],
            variable=self.save_share_platform_var,
            command=self.on_save_share_platform_change,
            width=100,
        )
        self.save_share_platform_menu.pack(side="left", padx=(0, 6))
        self.save_share_action_btn = ctk.CTkButton(
            self.save_share_frame,
            text="Save Sharing",
            command=self.on_save_share_action_clicked,
        )
        self.save_share_action_btn.pack(side="left")
        self.ps_samples_info = []
        self._refresh_save_share_button()

        self.theme_switch = ctk.CTkSwitch(
            header_frame,
            text=self.tr('theme_switch'),
            command=self.toggle_theme
        )
        # Initialize switch state from stored theme (selected = dark)
        if self.current_theme == 'dark':
            self.theme_switch.select()
        else:
            self.theme_switch.deselect()
        self.theme_switch.grid(row=0, column=4, padx=10, sticky="e")

        self.save_btn = ctk.CTkButton(
            header_frame,
            text=self.tr('save_button'),
            command=self.on_save_clicked  # changed to wrapper
        )
        self.save_btn.grid(row=0, column=2, padx=5, sticky="e")

        self.load_btn = ctk.CTkButton(
            header_frame,
            text=self.tr('load_button'),
            command=self.on_load_clicked  # changed to wrapper
        )
        self.load_btn.grid(row=0, column=1, padx=5, sticky="e")

        stats_frame = ctk.CTkFrame(header_frame)
        stats_frame.grid(row=0, column=0, columnspan=2, padx=10, sticky="w")
        stats_frame.grid_columnconfigure((0, 1), weight=1)

        self.profile_frame = ctk.CTkFrame(stats_frame)
        self.profile_frame.grid(row=0, column=0, sticky="w", padx=5)
        ctk.CTkLabel(
            self.profile_frame,
            text=self.tr('profile_label'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold")
        ).pack(side="left", padx=2)
        self.profile_name_label = ctk.CTkLabel(self.profile_frame, text=self.tr('load_save_info'), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.profile_name_label.pack(side="left", padx=2)

        self.playtime_frame = ctk.CTkFrame(stats_frame)
        self.playtime_frame.grid(row=0, column=1, sticky="e", padx=5)
        ctk.CTkLabel(
            self.playtime_frame,
            text=self.tr('playtime_label'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold")
        ).pack(side="left", padx=2)
        self.playtime_label = ctk.CTkLabel(self.playtime_frame, text=self.tr('load_save_info'), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.playtime_label.pack(side="left", padx=2)

        main_content = ctk.CTkFrame(self.scrollable_frame)
        main_content.pack(side="top", fill="both", expand=True, pady=10, padx=10)

        # Save Paths | Translation Editor share one dual-purpose header bar. height=None auto-sizes to content - a fixed height used to clip the "Save Translation" button outside the visible area.
        self.save_paths_section_content, self.translation_content = self.create_dual_collapsible_section(
            main_content, "save_paths_section", "translation_section", left_height=None, right_height=None
        )
        try:
            self.init_save_paths_section()
        except Exception as e:
            print(f"[WARN] init_save_paths_section failed: {e}")

        # Default open state: Save Paths open, Translation Editor collapsed (accordion enforcement in _close_other_sections only allows one of this dual pair open at a time anyway).
        try:
            reorder_group = [self.save_paths_section_content, self.translation_content]
            self.toggle_collapsible_frame(self.save_paths_section_content, self.save_paths_section_button, "save_paths_section", reorder_group)
        except Exception as e:
            print(f"[WARN] failed to auto-open save_paths_section: {e}")
        # Language dropdown and add button (above segmented button)
        lang_frame = ctk.CTkFrame(self.translation_content)
        lang_frame.pack(fill="x", padx=10, pady=(5, 0))
        # Dropdown shows human-friendly display names. Store/display the display name in the var.
        default_display = self.language_map.get(self.current_language, self.current_language)
        self.translation_lang_var = ctk.StringVar(value=default_display)
        # Backwards compatibility alias (bug fix for code referencing translation_language_var)
        self.translation_language_var = self.translation_lang_var  # alias
        # Option menu values use display names so users see readable names.
        self.translation_lang_dropdown = ctk.CTkOptionMenu(
            lang_frame,
            values=list(self.language_map.values()),
            variable=self.translation_lang_var,
            command=self.on_translation_lang_change
        )
        self.translation_lang_dropdown.pack(side="left", padx=(0, 10))
        self.add_lang_btn = ctk.CTkButton(
            lang_frame,
            text=self.tr('add_language_button', 'Add Language'),
            command=self.add_new_language
        )
        self.add_lang_btn.pack(side="left")
        # Segmented button for file selection: translation_tab_var stays canonical English for data lookups; translation_tab_display_var is the widget-bound, possibly-translated label.
        self.translation_tab_var = ctk.StringVar(value="UI Strings")
        self.translation_tab_display_var = ctk.StringVar(value=self._translation_tab_label("UI Strings"))
        self.translation_segmented = ctk.CTkSegmentedButton(
            self.translation_content,
            values=self._translation_tab_labels(),
            variable=self.translation_tab_display_var,
            command=self.on_translation_tab_display_change
        )
        self.translation_segmented.pack(padx=10, pady=5, anchor="w")
        # Translation frame (will be updated by update_translation_tab)
        self.translation_frame = ctk.CTkFrame(self.translation_content)
        self.translation_frame.pack(fill="both", expand=True, padx=10, pady=5)
        # Bound on this stable outer frame, not the CTkTextbox itself, since update_translation_tab() rebuilds the textbox on every tab/language change.
        self._exempt_from_global_scroll(self.translation_frame)
        self.update_translation_tab("UI Strings")

        # Mission Table | Loadouts share one dual-purpose header bar; left_height=None auto-sizes rather than clipping long JP/KR button text.
        self.mission_content, self.loadout_content = self.create_dual_collapsible_section(
            main_content, "mission_table_section", "loadouts_section", left_height=None, right_height=None
        )
        # Stored as self.loadout_note_label so refresh_loadout_labels() can reach it directly (it's a child of loadout_content, not loadout_grid). Packed first (before loadout_grid) so it sits above the 4 class tables, not below them.
        self.loadout_note_label = ctk.CTkLabel(
            self.loadout_content,
            text=self.tr('loadout_note'),
            font=(FONT_FAMILY, BASE_FONT_SIZE + 1, "bold"),  # matches the +1 bump given to the rest of this panel's text
            wraplength=1250, justify="left", anchor="w"
        )
        self.loadout_note_label.translation_key = 'loadout_note'
        self.loadout_note_label.pack(pady=(4,2), padx=10, anchor="w", fill="x")

        self.loadout_grid = ctk.CTkFrame(self.loadout_content)
        # Slightly reduce vertical padding so the section takes up less room
        self.loadout_grid.pack(fill="both", expand=True, padx=10, pady=(6,2))
        self.loadout_grid.grid_columnconfigure((0, 1), weight=1)
        self.loadout_grid.grid_rowconfigure((0, 1), weight=1)

        self.rebuild_loadout_panel_for_game()  # Rebuildable since EDF4.1's loadout shape (4 slots/class) differs from EDF5/6's

        # Weapon Table and Weapon Farming Helper share one dual-purpose header bar; height=None auto-sizes so the Farming panel isn't clipped.
        self.weapon_farming_content, self.weapon_content = self.create_dual_collapsible_section(
            main_content, "weapon_farming_section", "weapon_table_section", left_height=None, right_height=None
        )
        self.search_entry = ctk.CTkEntry(
            master=self.weapon_content,
            placeholder_text="Search by weapon name...",
            width=300,
            font=(FONT_FAMILY, BASE_FONT_SIZE)
        )
        self.search_entry.pack(pady=10, padx=10, fill="x")
        self.search_entry.bind("<KeyRelease>", self.filter_table)
        self.search_placeholder_key = 'search_placeholder'
        self.search_placeholder_value = self._trans_dict().get(self.search_placeholder_key, 'Search by weapon name...')
        try:
            # Ensure current placeholder text matches translation
            self.search_entry.configure(placeholder_text=self.search_placeholder_value)
        except Exception as e:
            self._warn(e)

        self.tree_frame = tk.Frame(self.weapon_content)
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._exempt_from_global_scroll(self.tree_frame)

        self.update_tree_style()

        # Use translations for column headers
        stat_label = self.tr('weapon_table_col_stat')
        columns = [
            self.tr('weapon_table_col_id'),
            self.tr('weapon_table_col_name'),
            self.tr('weapon_table_col_condition'),
        ] + [f"{stat_label}{i+1}" for i in range(8)]

        self.tree = ttk.Treeview(
            master=self.tree_frame,
            columns=columns,
            show="headings",
            height=10
        )
        for col in columns:
            self.tree.heading(col, text=col)
        self.tree.column(self.tr('weapon_table_col_id'), width=50, anchor="c")
        self.tree.column(self.tr('weapon_table_col_name'), width=300, anchor="w")
        self.tree.column(self.tr('weapon_table_col_condition'), width=80, anchor="c")
        for col in columns[3:]:
            self.tree.column(col, width=50, anchor="c")

        self.vsb = ttk.Scrollbar(master=self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", expand=True, fill="both")

        # Controls and note for weapon table: mass-edit buttons and quick help, stored as self attributes so refresh_weapon_table_controls() can update their text on language change.
        control_frame = ctk.CTkFrame(self.weapon_content)
        control_frame.pack(fill="x", padx=10, pady=(6,4))
        self.own_all_btn = ctk.CTkButton(control_frame, text=self.tr('own_all_button'), width=120, command=lambda: self.mass_edit_weapon_stats('own_all'))
        self.sudo_max_btn = ctk.CTkButton(control_frame, text=self.tr('sudo_max_button'), width=120, command=lambda: self.mass_edit_weapon_stats('sudo_max'))
        self.poverty_btn = ctk.CTkButton(control_frame, text=self.tr('poverty_button'), width=120, command=lambda: self.mass_edit_weapon_stats('poverty'))
        self.own_all_btn.pack(side='left', padx=6)
        self.sudo_max_btn.pack(side='left', padx=6)
        self.poverty_btn.pack(side='left', padx=6)
        # Instruction note (editable via translations.json)
        note_text = self.tr('weapon_table_note')
        # Use a read-only textbox so long notes wrap and remain visible; allow expanding horizontally
        self.weapon_table_note_box = ctk.CTkTextbox(control_frame, height=56, font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"))
        try:
            self.weapon_table_note_box.insert('1.0', note_text)
            self.weapon_table_note_box.configure(state='disabled')
        except Exception:
            # Fallback to label if CTkTextbox is unavailable
            self.weapon_table_note_box = None
            note_label = ctk.CTkLabel(control_frame, text=note_text, font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"))
            note_label.translation_key = 'weapon_table_note'
            self.weapon_table_note_label = note_label
            note_label.pack(side='left', padx=12, fill='x', expand=True)
        else:
            self.weapon_table_note_box.translation_key = 'weapon_table_note'
            self.weapon_table_note_box.pack(side='left', padx=12, fill='x', expand=True)

        # WeaponLimit mod sidecar (.bin) support: the Mods-folder setting itself (and its status
        # line) now live in the Save Paths panel (init_save_paths_section) alongside the other
        # one-time setup - it's a stable, rarely-changed path, not something to browse to every
        # time you open this tab. What's left here is just the GST/BIN view for whatever data
        # ends up loaded (see EDFSaveEditorLogic.py's get_weapon_limit_bin_path() for the full
        # story on where that .bin sidecar lives).
        #
        # GST vs BIN source switch: once a WeaponLimit sidecar is active, MAIN.GST's own copy of
        # the table is frozen (the mod stops the game from ever touching it again) while the .bin
        # keeps changing from gameplay, so the two drift apart over time. "GST" shows the
        # read-only snapshot of what MAIN.GST itself still says (app.weapon_limit_gst_snapshot),
        # taken at load time; "BIN" (default) shows/edits the live, save-authoritative table
        # (app.weapon_data). The Weapon Table always displays every slot WeaponLimit loaded (no
        # separate "show extended slots" toggle - that only ever duplicated what switching to GST
        # already does, since GST is naturally capped at whatever MAIN.GST itself held). The diff
        # label/highlighting and the Port button let you see and pull GST's values back into BIN
        # slot-by-slot instead of guessing which weapons regressed.
        weapon_limit_source_row = ctk.CTkFrame(self.weapon_content, fg_color="transparent")
        weapon_limit_source_row.pack(fill='x', padx=16, pady=(0, 6))
        self.weapon_limit_source_label = ctk.CTkLabel(weapon_limit_source_row, text=self.tr('weapon_limit_source_label', "Viewing:"))
        self.weapon_limit_source_label.pack(side='left', padx=(0, 6))
        self.weapon_limit_source_var = ctk.StringVar(value="GST")
        self.weapon_limit_source_menu = ctk.CTkSegmentedButton(
            weapon_limit_source_row, values=["GST", "BIN"], variable=self.weapon_limit_source_var,
            command=self.on_weapon_limit_source_changed, width=100)
        self.weapon_limit_source_menu.pack(side='left', padx=(0, 12))
        self.weapon_limit_diff_label = ctk.CTkLabel(weapon_limit_source_row, text='',
                                                      font=(FONT_FAMILY, BASE_FONT_SIZE - 1))
        self.weapon_limit_diff_label.pack(side='left', padx=(0, 12))
        self.weapon_limit_port_btn = ctk.CTkButton(weapon_limit_source_row, text=self.tr('weapon_limit_port_button', "Port GST -> BIN"),
                                                     width=140, state='disabled', command=self.on_click_port_gst_to_bin)
        self.weapon_limit_port_btn.pack(side='left')

        self.tree.bind("<Double-1>", self.edit_cell)

        # Initialize weapon_data with valid IDs and placeholder data (restore full range 0..2047)
        self.weapon_data = [[i, "Unknown", 0, 0, 0, 0, 0, 0, 0, 0, 0] for i in range(2048)]
        self._weapon_table_last_row_count = len(self.weapon_data)
        # Populate the weapon table
        for idx, row in enumerate(self.weapon_data):
            self.tree.insert("", "end", iid=str(idx), values=row)
        # Update weapon names in the table
        self.update_weapon_table_names()
        self.refresh_weapon_limit_status()

        # Weapon Farming Helper lives in its own content frame, toggled by the left half of the header bar shared with Weapon Table.
        try:
            self.build_weapon_farming_section()
        except Exception as e:
            self._warn(e, 'build_weapon_farming_section')

        # Color Customization | Armor share one dual-purpose header bar, both auto-sizing (height=None).
        self.color_content, self.armor_content = self.create_dual_collapsible_section(
            main_content, "color_section", "armor_section", left_height=None, right_height=None
        )
        self.modded_frame = ctk.CTkFrame(self.armor_content)
        # Slightly reduce vertical padding so the element takes up less room
        self.modded_frame.pack(pady=(6,2), padx=10, fill="x")
        # Use new modded_multiplier_label key (static label without {value})
        self.modded_multiplier_label_widget = ctk.CTkLabel(
            self.modded_frame,
            text=self.tr('modded_multiplier_label'),
            font=(FONT_FAMILY, BASE_FONT_SIZE)
        )
        self.modded_multiplier_label_widget.translation_key = 'modded_multiplier_label'
        self.modded_multiplier_label_widget.pack(side="left", padx=5)
        # Purple like the mission table's "Inferno" column (self.colors[4]) - one of the 5
        # value inputs on this panel (this multiplier + the 4 per-class totals below).
        self.modded_gain_entry = ctk.CTkEntry(self.modded_frame, width=100, fg_color=self.colors[4], text_color=self.text_colors[4])
        self.modded_gain_entry.pack(side="left", padx=5)
        self.modded_gain_entry.insert(0, "1.0")
        self.modded_gain_entry.bind("<KeyRelease>", lambda e: self.update_armor_display())
        # Slightly smaller font and spacing for the helper note
        note_label = ctk.CTkLabel(
            self.modded_frame,
            text=self.tr('modded_gain_note'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold")
        )
        note_label.translation_key = 'modded_gain_note'
        note_label.pack(side="left", padx=10)

        # 2026-09-07 refactor (FevGrave: EDF 6.9 changes per-class armor gain RATE too, and cramming
        # a 6th value into one row "will not fit and look good") - each class now gets its own
        # bordered card with 2 rows: row 1 = the save-editing controls (Total You Really Have +
        # +100/-100), row 2 = the preview math (Base Gain / Modded Start / Modded Rate / Modded
        # Gain). 4 cards stack vertically. refresh_armor_labels() below was updated to recurse into
        # the new row sub-frames when retranslating.
        for i in range(4):
            class_name = PLAYER_CLASS_MAP[i]
            card = ctk.CTkFrame(self.armor_content, border_width=2, border_color=self.colors[4])
            if i == 3:
                card.pack(pady=(3, 0), padx=10, fill="x")
            else:
                card.pack(pady=3, padx=10, fill="x")

            # 2026-09-07: rebuilt as two side-by-side columns (not stacked rows) so each gain-bar
            # readout sits directly under its own column instead of an independent 50/50 split that
            # drifted out of alignment with the controls above it. Left column = real save data
            # (class label/Total You Really Have/+100/-100, then Base Game Gain below); right column
            # = modded preview inputs (Modded Start/Rate, then Modded Armor Gain below); a vertical
            # splitter divides them.
            # Per FevGrave's feedback (screenshot with arrows pointing at the dead gap between -100
            # and the splitter): left gets weight=0 so its column shrinks to exactly the controls'
            # natural width - no more gap - and the splitter sits right after -100. Right gets ALL
            # the leftover width (weight=1), so Modded Start/Rate + the Modded Armor Gain bar get
            # noticeably bigger, not just a larger share of a 50/50-ish split. Base Game Gain still
            # fills left_col's full (now-tighter) width via fill="x", so it stays flush with the
            # controls above it instead of a gap of its own.
            # (The previous version's splitter had no explicit height, so it inherited CTkFrame's
            # ~200px default and forced every card to that height - fixed here with height=1.)
            columns = ctk.CTkFrame(card, fg_color="transparent")
            columns.pack(padx=8, pady=(5, 5), fill="x")
            columns.grid_columnconfigure(0, weight=0)
            columns.grid_columnconfigure(1, weight=0)
            columns.grid_columnconfigure(2, weight=1)

            left_col = ctk.CTkFrame(columns, fg_color="transparent")
            left_col.grid(row=0, column=0, sticky="nsew")
            ctrl_row = ctk.CTkFrame(left_col, fg_color="transparent")
            ctrl_row.pack(fill="x", pady=(0, 4))
            armor_label_key = f"{class_name.lower().replace(' ', '_')}_armor_label"  # FIX: ensure underscore for Air Raider
            armor_label = ctk.CTkLabel(ctrl_row, text=self.tr(armor_label_key, f'{class_name} MAX Armor:'), font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"), width=ARMOR_CLASS_LABEL_WIDTH, anchor="w")
            armor_label.translation_key = armor_label_key
            armor_label.pack(side="left", padx=10)
            total_label_key = 'total_armor_label'
            total_label = ctk.CTkLabel(ctrl_row, text=self.tr(total_label_key, 'Total You Really Have:'), font=(FONT_FAMILY, BASE_FONT_SIZE))
            total_label.translation_key = total_label_key
            total_label.pack(side="left", padx=5)
            # Same purple as the multiplier entry above (self.colors[4], the mission table's
            # "Inferno" color) - one of this card's preview-input-colored fields.
            entry = ctk.CTkEntry(ctrl_row, width=100, fg_color=self.colors[4], text_color=self.text_colors[4])
            entry.pack(side="left", padx=5)
            entry.insert(0, "0")
            entry.bind("<KeyRelease>", lambda e: self.update_armor_display())
            self.armor_entries.append(entry)
            # Reuse the mission table's difficulty palette so +100/-100 read as green=add / red=subtract at a glance.
            inc_button = ctk.CTkButton(
                ctrl_row, text="+100", width=60,
                fg_color=self.colors[1], hover_color="#5fc95f", text_color=self.text_colors[1],
                command=lambda idx=i: self.adjust_armor(idx, 100)
            )
            inc_button.pack(side="left", padx=5)
            dec_button = ctk.CTkButton(
                ctrl_row, text="-100", width=60,
                fg_color=self.colors[3], hover_color="#e64545", text_color=self.text_colors[3],
                command=lambda idx=i: self.adjust_armor(idx, -100)
            )
            dec_button.pack(side="left", padx=5)
            # base_label is a display-only readout built as a disabled CTkButton for the mission-table
            # color coding; fill="x" makes it match left_col's actual (auto-sized) width exactly.
            base_label = ctk.CTkButton(
                left_col, text=self.tr('base_gain_label').format(value=0.0), font=(FONT_FAMILY, BASE_FONT_SIZE),
                anchor="w", state="disabled",
                fg_color=self.colors[0], text_color=self.text_colors[0], text_color_disabled=self.text_colors[0],
            )
            base_label.translation_key = 'base_gain_label'
            base_label.pack(fill="x")
            self.base_gain_labels.append(base_label)

            # Vertical splitter dividing "real save data" (left) from "modded preview inputs" (right).
            splitter = ctk.CTkFrame(columns, width=2, height=1, fg_color=self.colors[4])
            splitter.grid(row=0, column=1, sticky="ns", padx=10)

            right_col = ctk.CTkFrame(columns, fg_color="transparent")
            right_col.grid(row=0, column=2, sticky="nsew")
            modded_row = ctk.CTkFrame(right_col, fg_color="transparent")
            modded_row.pack(fill="x", pady=(0, 4))
            # Modded Starting AP: added 2026-09-07 (FevGrave, playing a modded game - EDF 6.9 -
            # whose starting armor differs from vanilla's 200/150/200/250) so "Modded Armor Gain"
            # can reflect what a mod's real starting AP actually is, instead of always silently
            # assuming vanilla's constant regardless of the multiplier above. Pre-filled with the
            # vanilla value per class - only needs changing for a mod that actually alters it.
            # Preview-only like the multiplier/other armor fields on this panel - never written
            # to the save, only feeds the "Modded Armor Gain" readout via update_displays().
            modded_start_label = ctk.CTkLabel(modded_row, text=self.tr('armor_modded_start_label', 'Modded Start:'), font=(FONT_FAMILY, BASE_FONT_SIZE))
            modded_start_label.translation_key = 'armor_modded_start_label'
            modded_start_label.pack(side="left", padx=(0, 2))
            modded_start_entry = ctk.CTkEntry(modded_row, width=70, fg_color=self.colors[4], text_color=self.text_colors[4])
            vanilla_start = EDF41_ARMOR_STARTING_TOTALS.get(f"{class_name} Armor", 0)
            modded_start_entry.insert(0, str(vanilla_start))
            modded_start_entry.pack(side="left", padx=(0, 8))
            modded_start_entry.bind("<KeyRelease>", lambda e: self.update_armor_display())
            self.armor_modded_start_entries.append(modded_start_entry)
            # Modded Growth Rate: added 2026-09-07 alongside this card refactor, same pattern as
            # Modded Start above - pre-filled with vanilla's per-class rate for whatever game is
            # currently selected (see get_vanilla_armor_rate()), purple/preview-only, feeds only the
            # "Modded Armor Gain" formula. Base Game Gain always keeps the true vanilla rate.
            modded_rate_label = ctk.CTkLabel(modded_row, text=self.tr('armor_modded_rate_label', 'Modded Rate:'), font=(FONT_FAMILY, BASE_FONT_SIZE))
            modded_rate_label.translation_key = 'armor_modded_rate_label'
            modded_rate_label.pack(side="left", padx=(0, 2))
            modded_rate_entry = ctk.CTkEntry(modded_row, width=70, fg_color=self.colors[4], text_color=self.text_colors[4])
            vanilla_rate = get_vanilla_armor_rate(getattr(self, 'current_game', 'EDF6'), f"{class_name} Armor")
            modded_rate_entry.insert(0, str(round(vanilla_rate, 4)))
            modded_rate_entry.pack(side="left", padx=(0, 8))
            modded_rate_entry.bind("<KeyRelease>", lambda e: self.update_armor_display())
            self.armor_modded_rate_entries.append(modded_rate_entry)
            # modded_label mirrors base_label - fill="x" so it matches right_col's actual width.
            modded_label = ctk.CTkButton(
                right_col, text=self.tr('modded_gain_label').format(value=0.0), font=(FONT_FAMILY, BASE_FONT_SIZE),
                anchor="w", state="disabled",
                fg_color=self.colors[2], text_color=self.text_colors[2], text_color_disabled=self.text_colors[2],
            )
            modded_label.translation_key = 'modded_gain_label'
            modded_label.pack(fill="x")
            self.modded_gain_labels.append(modded_label)

        # Stored as self.armor_note_label so refresh_armor_labels() can reach it (a direct child of armor_content, not the per-class row frames).
        self.armor_note_label = ctk.CTkLabel(
            self.armor_content,
            text=self.tr('armor_note'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"),
            wraplength=1250, justify="left"
        )
        self.armor_note_label.translation_key = 'armor_note'
        self.armor_note_label.pack(pady=(0,5), padx=10, anchor="w")

        # Color customization: 4 classes x 4 tiers x Primary/Secondary, each holding 12 RGBA palettes + a swatch ID; Primary/Secondary shown side by side, edits cached in app.color_data.
        self.color_current_key = (0, 0)  # (class_idx, tier_idx) - both Primary and Secondary shown for this pair

        selector_row = ctk.CTkFrame(self.color_content)
        selector_row.pack(fill="x", padx=10, pady=(6, 4))

        self.color_class_label_widget = ctk.CTkLabel(selector_row, text=self.tr('color_class_label'), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.color_class_label_widget.translation_key = 'color_class_label'
        self.color_class_label_widget.pack(side="left", padx=(0, 4))
        # color_class_var/color_tier_var stay canonical English for .index() lookups elsewhere; the _display_var pair is what's bound to the dropdowns and gets mapped back on change.
        self.color_class_var = ctk.StringVar(value=COLOR_CLASSES[0])
        self.color_class_display_var = ctk.StringVar(value=self._color_class_label(COLOR_CLASSES[0]))
        self.color_class_menu = ctk.CTkOptionMenu(
            selector_row, values=[self._color_class_label(c) for c in COLOR_CLASSES],
            variable=self.color_class_display_var,
            command=lambda v: self.on_color_selector_display_change('class', v)
        )
        self.color_class_menu.pack(side="left", padx=(0, 10))

        self.color_tier_label_widget = ctk.CTkLabel(selector_row, text=self.tr('color_tier_label'), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.color_tier_label_widget.translation_key = 'color_tier_label'
        self.color_tier_label_widget.pack(side="left", padx=(0, 4))
        self.color_tier_var = ctk.StringVar(value=COLOR_TIERS[0])
        self.color_tier_display_var = ctk.StringVar(value=self._color_tier_label(COLOR_TIERS[0]))
        self.color_tier_menu = ctk.CTkOptionMenu(
            selector_row, values=[self._color_tier_label(t) for t in COLOR_TIERS],
            variable=self.color_tier_display_var,
            command=lambda v: self.on_color_selector_display_change('tier', v)
        )
        self.color_tier_menu.pack(side="left", padx=(0, 10))

        # Toggle between Player 1 and Player 2 color customization, same pattern as the mission table's Player 1/2 toggle.
        self.color_player_toggle_btn = ctk.CTkButton(
            selector_row, text=self._color_player_toggle_text(1), width=160,
            command=self.toggle_color_player_slot
        )
        self.color_player_toggle_btn.pack(side="left", padx=(10, 0))

        # Current Swatch ID - Primary and Secondary each have their own, sitting above each column's 12 palette rows. Widget dicts declared here so the flush/load helpers can find them.
        self.color_swatch_id_entries = {}
        self.color_swatch_id_label_widgets = {}
        self.color_palette_rows = {False: [], True: []}
        self.color_column_title_widgets = {}
        # PERF: the actual 2-column x 12-row swatch grid (~260 individual CTk widgets - the single
        # heaviest chunk of UI in the app, each one a canvas-based custom-drawn widget) is NOT built
        # here. Building it unconditionally for every launch, even for the many users who never open
        # this accordion section in a given session, was the direct cause of the visible "elements
        # drawing in one at a time" startup slowdown - customtkinter widget construction is the
        # actual expensive part, not any of the interaction handlers (those were already fixed
        # separately - see _highlight_active_swatch_row's docstring). It's now built once, lazily,
        # the first time the Color Customization section is actually expanded - see
        # _build_color_grid() and its call from toggle_collapsible_frame(). self._color_grid_built
        # tracks whether that's happened yet; flush_color_ui_to_cache()/refresh_color_panel() check
        # it too, so in-progress data is never read from (or written into) a grid that doesn't exist.
        self._color_grid_built = False

        self.color_warning_label = ctk.CTkLabel(
            self.color_content,
            text=self.tr('color_panel_warning'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"), wraplength=1250, justify="left",
        )
        self.color_warning_label.translation_key = 'color_panel_warning'
        self.color_warning_label.pack(anchor="w", padx=10, pady=(0, 4))

        # Achievements | Key Config share one dual-purpose header bar; Key Config covers both EDF5 and EDF6 now, using a Category dropdown (one group visible at a time). Left keeps a fixed height (650), Key Config auto-sizes.
        self.achievement_content, self.keyconfig_content = self.create_dual_collapsible_section(
            main_content, "achievements_section", "keyconfig_section", left_height=650, right_height=None
        )

        self.keyconfig_warning_label = ctk.CTkLabel(
            self.keyconfig_content,
            text=self.tr('keyconfig_panel_warning', "Keyboard: EDF5 and EDF6 both have all 11 categories mapped (Common, Ranger/Wing Diver/Air Raider/Fencer, and all 6 vehicle categories - Drive/Tanks/Heli/Combat/Barga/Depth). Controller: EDF5 and EDF6, same 4 soldier classes (Common/vehicles have no controller data in either game). EDF4.1 is supported too (Keyboard: Solder/Ranger/Fencer plus its own vehicle categories; Controller: Solder/Fencer only), confirmed via before/after COMMON.CFG diffs and Ghidra RE of the game's own key-code table. Rows marked (unverified) are predicted slot positions, not individually confirmed - see EDF5_SAVE_FORMAT_NOTES.md before relying on one of those for anything that matters."),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"), wraplength=1250, justify="left",
        )
        self.keyconfig_warning_label.translation_key = 'keyconfig_panel_warning'
        self.keyconfig_warning_label.pack(anchor="w", padx=10, pady=(0, 4))

        kc_selector_row = ctk.CTkFrame(self.keyconfig_content, fg_color="transparent")
        kc_selector_row.pack(fill="x", padx=10, pady=(0, 4))

        # Keyboard/Controller mode toggle - controller bindings live at different offsets and only exist for the 4 soldier classes, so the Category dropdown's values switch per mode.
        self.keyconfig_mode_label_widget = ctk.CTkLabel(kc_selector_row, text=self.tr('keyconfig_mode_label', "Mode:"), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.keyconfig_mode_label_widget.translation_key = 'keyconfig_mode_label'
        self.keyconfig_mode_label_widget.pack(side="left", padx=(0, 4))
        # Highlight color for a keybind row's button while actively capturing input; reuses the panel's existing "(unverified)" gold/amber accent.
        self._KEYCONFIG_CAPTURE_COLOR = "#c9a227"
        self._KEYCONFIG_CAPTURE_HOVER_COLOR = "#a5841f"

        self.keyconfig_mode_var = ctk.StringVar(value="Keyboard")
        self.keyconfig_mode_display_var = ctk.StringVar(value=self.tr('keyconfig_mode_keyboard', "Keyboard"))
        self.keyconfig_mode_menu = ctk.CTkSegmentedButton(
            kc_selector_row,
            values=[self.tr('keyconfig_mode_keyboard', "Keyboard"), self.tr('keyconfig_mode_controller', "Controller")],
            variable=self.keyconfig_mode_display_var,
            command=self.on_keyconfig_mode_display_change,
        )
        self.keyconfig_mode_menu.pack(side="left", padx=(0, 10))

        self.keyconfig_category_label_widget = ctk.CTkLabel(kc_selector_row, text=self.tr('keyconfig_category_label', "Category:"), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.keyconfig_category_label_widget.translation_key = 'keyconfig_category_label'
        self.keyconfig_category_label_widget.pack(side="left", padx=(0, 4))
        # keyconfig_category_var stays canonical for get_keyconfig_actions() lookups, same display/canonical split as color_class_var above; in Controller mode it holds a CONTROLLER_ACTIONS key instead.
        self.keyconfig_category_var = ctk.StringVar(value=KEYCONFIG_CATEGORIES[0])
        self.keyconfig_category_display_var = ctk.StringVar(value=self._keyconfig_category_label(KEYCONFIG_CATEGORIES[0]))
        self.keyconfig_category_menu = ctk.CTkOptionMenu(
            kc_selector_row, values=[self._keyconfig_category_label(c) for c in KEYCONFIG_CATEGORIES],
            variable=self.keyconfig_category_display_var,
            command=self.on_keyconfig_category_display_change,
        )
        self.keyconfig_category_menu.pack(side="left", padx=(0, 10))

        # keyconfig_player_var holds '1' or '2' as a plain string; read/write keybind functions take an int, so callers int()-convert it.
        self.keyconfig_player_label_widget = ctk.CTkLabel(kc_selector_row, text=self.tr('keyconfig_player_label', "Player:"), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.keyconfig_player_label_widget.translation_key = 'keyconfig_player_label'
        self.keyconfig_player_label_widget.pack(side="left", padx=(0, 4))
        self.keyconfig_player_var = ctk.StringVar(value="1")
        self.keyconfig_player_menu = ctk.CTkSegmentedButton(
            kc_selector_row, values=["1", "2"],
            variable=self.keyconfig_player_var,
            command=lambda _v: self.rebuild_keyconfig_rows(),
            width=70,
        )
        self.keyconfig_player_menu.pack(side="left", padx=(0, 10))

        # Controller-type display overlay - cosmetic relabeling of button names (Xbox/PlayStation/Switch Pro), EDF6-only (disabled/forced to Xbox elsewhere); persisted to config.json like theme/language.
        self._controller_type_labels = {
            "xbox": self.tr('keyconfig_controller_type_xbox', "Xbox / Generic"),
            "ps4": self.tr('keyconfig_controller_type_ps4', "PlayStation"),
            "switch": self.tr('keyconfig_controller_type_switch', "Switch Pro"),
        }
        # Brand colors per controller type (Xbox green/PlayStation blue/Nintendo red), reconfigured on selection change since CTkSegmentedButton only exposes one active-segment color.
        self._controller_type_brand_colors = {
            "xbox": ("#107C10", "#0C5F0C"),     # Xbox green
            "ps4": ("#0070D1", "#00589F"),       # PlayStation blue
            "switch": ("#E60012", "#B8000E"),    # Nintendo/Switch red
        }
        # Real per-face-button legend colors (A/B/X/Y etc.), keyed by raw_value then controller type since the same raw value maps to a different physical button per type.

        self._GAMEPAD_FACE_BUTTON_COLORS = {
            1: {"xbox": ("#3CB043", "#2E8934"), "ps4": ("#3B82C4", "#2F6699"), "switch": ("#D9453D", "#B23A33")},
            2: {"xbox": ("#D9453D", "#B23A33"), "ps4": ("#D9453D", "#B23A33"), "switch": ("#D9B23D", "#B29433")},
            3: {"xbox": ("#3B82C4", "#2F6699"), "ps4": ("#D14FB0", "#A83E8D"), "switch": ("#3CB043", "#2E8934")},
            4: {"xbox": ("#D9B23D", "#B29433"), "ps4": ("#3CB043", "#2E8934"), "switch": ("#3B82C4", "#2F6699")},
        }
        self.keyconfig_controller_type_label_widget = ctk.CTkLabel(kc_selector_row, text=self.tr('keyconfig_controller_type_label', "Controller:"), font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.keyconfig_controller_type_label_widget.translation_key = 'keyconfig_controller_type_label'
        self.keyconfig_controller_type_label_widget.pack(side="left", padx=(0, 4))
        self.controller_type_var = ctk.StringVar(value=self.config_data.get('controller_display', 'xbox'))
        self.controller_type_display_var = ctk.StringVar(value=self._controller_type_labels[self.controller_type_var.get()])
        _initial_brand = self._controller_type_brand_colors.get(self.controller_type_var.get(), self._controller_type_brand_colors["xbox"])
        self.keyconfig_controller_type_menu = ctk.CTkSegmentedButton(
            kc_selector_row, values=list(self._controller_type_labels.values()),
            variable=self.controller_type_display_var,
            command=self.on_controller_type_display_change,
            selected_color=_initial_brand[0],
            selected_hover_color=_initial_brand[1],
            width=130,
        )
        self.keyconfig_controller_type_menu.pack(side="left", padx=(0, 10))

        self.keyconfig_rows_frame = ctk.CTkFrame(self.keyconfig_content, fg_color="transparent")
        self.keyconfig_rows_frame.pack(fill="x", padx=10, pady=(0, 8))
        self.keyconfig_rows = []          # current category's row widgets
        self.keyconfig_unavailable_label = None  # shown instead of rows for a non-EDF5 game
        self.keyconfig_rebind_target = None      # (player, category, action_name, key_btn, default_fg, default_hover, default_text) currently capturing keyboard/mouse input, or None - see start_keyconfig_rebind

        # Mission section: create_collapsible_section fixes this frame's height (745, tuned to fit the note/header/buttons/table/Boring Missions block) - if content clips, nudge left_height above instead.
        mission_note_label = ctk.CTkLabel(
            self.mission_content,
            text=self.tr('mission_table_note'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"), wraplength=1250, justify="left",
        )
        mission_note_label.translation_key = 'mission_table_note'
        mission_note_label.pack(pady=(4, 2), padx=10, anchor="w", fill="x")
        # Header frame for Mission Table and Completion
        header_grid = ctk.CTkFrame(self.mission_content)
        header_grid.pack(fill="x", pady=5)
        header_grid.grid_columnconfigure((0, 1), weight=1)

        # Dropdown listing only the .MST tables actually found in the loaded save folder; picking an entry drives the same game/DLC switch as the top game selector.
        mst_row = ctk.CTkFrame(header_grid, fg_color="transparent")
        mst_row.grid(row=0, column=0, padx=10, sticky="w")

        self.mst_dropdown_var = ctk.StringVar(value=self.current_game)
        self.mst_dropdown = ctk.CTkOptionMenu(
            mst_row, variable=self.mst_dropdown_var, values=[self.current_game],
            width=200, command=self.on_mst_dropdown_change
        )
        self.mst_dropdown.pack(side="left")

        # Mission-total override for modded packs, entered here and persisted to config.json since the real count isn't exposed automatically; disabled/greyed for vanilla/DLC entries.
        self.mst_total_label = ctk.CTkLabel(mst_row, text=self.tr('mst_total_label', 'Missions:'))
        self.mst_total_label.pack(side="left", padx=(10, 2))
        self.mst_total_var = ctk.StringVar(value=str(self.total_missions))
        self.mst_total_entry = ctk.CTkEntry(mst_row, textvariable=self.mst_total_var, width=55, state="disabled")
        self.mst_total_entry.pack(side="left")
        self.mst_total_entry.bind("<Return>", self.on_mst_total_changed)
        self.mst_total_entry.bind("<FocusOut>", self.on_mst_total_changed)

        # Dynamic completion label uses total_missions * 20 (4 classes * 5 difficulties)
        self.total_possible = self.total_missions * 20
        self.completion_label = ctk.CTkLabel(header_grid, text=f"Completion: 0.00% (0/{self.total_possible})", font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.completion_label.grid(row=0, column=1, padx=10, sticky="e")

        # Grid for the class "View" buttons, mission table, and side panels, all sharing the same two-column (table + sidebar) split so everything lines up.
        mission_grid = ctk.CTkFrame(self.mission_content)
        mission_grid.pack(fill="both", expand=True, padx=10, pady=5)
        mission_grid.grid_columnconfigure(0, weight=1)
        mission_grid.grid_columnconfigure(1, weight=0)
        mission_grid.grid_rowconfigure(0, weight=0)
        # weight=0 (not 1) so leftover vertical space shows as plain empty space below row 2, instead of stretching the pagination sidebar into a dead gap.
        mission_grid.grid_rowconfigure(1, weight=0)
        mission_grid.grid_rowconfigure(2, weight=0)

        # Buttons frame - class "View" buttons, aligned above the table (column 0)
        buttons_frame = ctk.CTkFrame(mission_grid)
        buttons_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        buttons_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        classes = [
            self.tr('mission_table_col_ranger'),
            self.tr('mission_table_col_wingdiver'),
            self.tr('mission_table_col_airraider'),
            self.tr('mission_table_col_fencer')
        ]
        classes_short = [
            self.tr('mission_table_col_ranger_short'),
            self.tr('mission_table_col_wingdiver_short'),
            self.tr('mission_table_col_airraider_short'),
            self.tr('mission_table_col_fencer_short')
        ]
        diffs = [
            self.tr('mission_table_col_easy'),
            self.tr('mission_table_col_normal'),
            self.tr('mission_table_col_hard'),
            self.tr('mission_table_col_hardest'),
            self.tr('mission_table_col_inferno')
        ]
        diffs_short = [
            self.tr('mission_table_col_easy_short'),
            self.tr('mission_table_col_normal_short'),
            self.tr('mission_table_col_hard_short'),
            self.tr('mission_table_col_hardest_short'),
            self.tr('mission_table_col_inferno_short')
        ]

        # Keep easily-accessible copies on the instance for use by the class-switch helpers
        self.mission_class_names = classes
        self.mission_class_short_names = classes_short
        self.mission_diffs = diffs
        self.mission_diffs_short = diffs_short

        self.mission_unlock_buttons = [[None for _ in range(len(diffs))] for _ in range(len(classes))]
        self.mission_reset_buttons = [[None for _ in range(len(diffs))] for _ in range(len(classes))]
        self.mission_class_labels = []
        self.mission_class_label_defaults = []  # (fg_color, text_color) captured pre-highlight, so the active-class style can be reverted cleanly
        self.mission_view_buttons = []  # BUG FIX: was a local var, never refreshed on language switch
        for cl_idx, cl in enumerate(classes):
            class_frame = ctk.CTkFrame(buttons_frame)
            class_frame.grid(row=0, column=cl_idx, sticky="ew", padx=5)
            class_label = ctk.CTkLabel(class_frame, text=cl, font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"))
            class_label.pack(fill="x")
            self.mission_class_labels.append(class_label)
            self.mission_class_label_defaults.append((class_label.cget("fg_color"), class_label.cget("text_color")))

            # Add a small 'View' button to hot-swap the active class shown in the mission sheet
            view_btn = ctk.CTkButton(class_frame,
                                     text=self.tr('view_button'),
                                     width=70,
                                     command=lambda i=cl_idx: self.set_active_mission_class(i))
            view_btn.pack(pady=(4,6), fill='x')
            self.mission_view_buttons.append(view_btn)

            # No per-class unlock/reset buttons here — a single set will be shown in the side panel for the active class

        # Side-top panel above the pagination sidebar: just the Y/N legend now.
        side_top_frame = ctk.CTkFrame(mission_grid)
        side_top_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=(0, 5))

        yn_yes = self.tr('mission_table_cell_yes')
        yn_no = self.tr('mission_table_cell_no')
        self.completion_legend_label = ctk.CTkLabel(side_top_frame, text=f"{yn_yes}: {self.tr('mission_table_cell_yes_desc')}   {yn_no}: {self.tr('mission_table_cell_no_desc')}", font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"))
        self.completion_legend_label.pack(pady=(2, 6), fill="x")

        # Unlock Legend: solid yellow/black since Unlock/Reset are bulk, one-click, no-undo actions - same cautionary highlight style as the active-class label.
        self.unlock_legend_label = ctk.CTkLabel(
            side_top_frame,
            text=self.tr('unlock_legend_text'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"),
            fg_color=ACTIVE_HIGHLIGHT_BG,
            text_color=ACTIVE_HIGHLIGHT_FG,
            corner_radius=4,
            wraplength=260, justify="left",
        )
        self.unlock_legend_label.pack(pady=(0, 6), fill="x")

        sheet_container = ctk.CTkFrame(mission_grid)
        sheet_container.grid(row=1, column=0, sticky="nsew")
        self.sheet_container = sheet_container  # kept so reset_sheet_formatting() can measure real available width and grow the Mission column to fill it
        self._exempt_from_global_scroll(sheet_container)  # Isolates the fixed 15-row table from the page's scroll
        self.sheet = Sheet(
            sheet_container,
            height=385,  # Shows all 15 rows without scrolling or a trailing blank strip
            width=1210,
            show_y_scrollbar=False,
            show_x_scrollbar=False,
            font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),  # Smaller table-only size, not the app's body size - see TABLE_FONT_SIZE.
            header_font=(FONT_FAMILY, TABLE_HEADER_FONT_SIZE, "bold"),
            index_font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
            popup_menu_font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
        )
        # fill="y" + anchor="nw" keeps the Sheet sized to its real column widths, flush top-left - fill="both" used to stretch it and leave a blank gap before the pagination sidebar.
        self.sheet.pack(fill="y", anchor="nw")

        # Default active class is 0 (first class). This will populate headers/columns appropriately.
        self.active_mission_class = 0
        # Build initial headers/columns for the active class
        headers = ["Mission"]
        active_short = self.mission_class_short_names[self.active_mission_class]
        for d in self.mission_diffs_short:
            headers.append(f"{active_short} {d}")

        self.sheet.headers(headers)

        # Separator & data columns for the single visible class
        self.sep_cols = []
        # data columns are 1..number_of_difficulties
        self.data_cols = list(range(1, len(self.mission_diffs_short) + 1))

        self.reset_sheet_formatting()

        self.sheet.readonly_columns(columns=[0] + self.sep_cols)
        self.sheet.enable_bindings(("single_select", "row_select", "column_select", "drag_select", "shift_select", "edit_cell", "copy", "cut", "paste", "delete", "undo", "redo"))

        self.sheet.extra_bindings([("double_click_cell", self.toggle_mission_cell), ("edit_cell", self.on_cell_edit)])
        self._suppress_sheet_wheel_propagation(self.sheet)
        self._lock_sheet_vertical_scroll(self.sheet)

        # Custom "Boring Missions" controls: lets the user program which missions the Unlock Boring Missions button unlocks, instead of only the hardcoded auto_unlock_missions list; persisted per-game in config.json.
        try:
            boring_missions_frame = ctk.CTkFrame(mission_grid)
            boring_missions_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

            self.boring_missions_label = ctk.CTkLabel(
                boring_missions_frame,
                text=self.tr('boring_missions_section_label'),
                font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"),
                anchor="w",
            )
            self.boring_missions_label.pack(fill='x', padx=6, pady=(6, 2))

            self.boring_missions_note_label = ctk.CTkLabel(
                boring_missions_frame,
                text=self.tr('boring_missions_note'),
                font=(FONT_FAMILY, BASE_FONT_SIZE),
                anchor="w", justify="left", wraplength=1250,
            )
            self.boring_missions_note_label.pack(fill='x', padx=6, pady=(0, 4))

            self.boring_missions_var = ctk.StringVar(value="")
            self.boring_missions_entry = ctk.CTkEntry(
                boring_missions_frame,
                textvariable=self.boring_missions_var,
                placeholder_text=self.tr('boring_missions_placeholder'),
            )
            self.boring_missions_entry.pack(fill='x', padx=6, pady=(0, 4))
            # Commit on Enter/focus-out, not every keystroke, so partial typing never mutates saved state.
            self.boring_missions_entry.bind('<Return>', lambda e: self.on_boring_missions_changed())
            self.boring_missions_entry.bind('<FocusOut>', lambda e: self.on_boring_missions_changed())

            # Difficulty + class checkboxes on one shared bar; a wider gap before "Ranger" separates the two groups visually.
            boring_checks_row = ctk.CTkFrame(boring_missions_frame, fg_color="transparent")
            boring_checks_row.pack(fill='x', padx=6, pady=(0, 4))
            self.boring_diff_vars = []
            self.boring_diff_checkboxes = []
            for d_idx, short in enumerate(self.mission_diffs_short):
                var = ctk.BooleanVar(value=True)
                cb = ctk.CTkCheckBox(
                    boring_checks_row,
                    text=short,
                    variable=var,
                    width=1,
                    checkbox_width=16,
                    checkbox_height=16,
                    fg_color=self.colors[d_idx],
                    command=self.on_boring_missions_changed,
                )
                cb.pack(side='left', padx=4)
                self.boring_diff_vars.append(var)
                self.boring_diff_checkboxes.append(cb)

            # Per-class checkboxes - any combination can be picked, not just "one" or "all".
            self.boring_class_vars = []
            self.boring_class_checkboxes = []
            for cl_idx, cl_name in enumerate(self.mission_class_names):
                var = ctk.BooleanVar(value=True)
                cb = ctk.CTkCheckBox(
                    boring_checks_row,
                    text=cl_name,
                    variable=var,
                    width=1,
                    checkbox_width=16,
                    checkbox_height=16,
                    command=self.on_boring_missions_changed,
                )
                cb.pack(side='left', padx=(20, 4) if cl_idx == 0 else 4)
                self.boring_class_vars.append(var)
                self.boring_class_checkboxes.append(cb)

            self.unlock_defined_btn = ctk.CTkButton(
                boring_missions_frame,
                text=self.tr('unlock_defined_button'),
                command=self.on_unlock_defined_click,
            )
            self.unlock_defined_btn.pack(fill='x', padx=6, pady=(2, 6))
        except Exception as e:
            self._warn(e)

        pag_frame = ctk.CTkFrame(mission_grid)
        pag_frame.grid(row=1, column=1, sticky="ns", padx=(10, 0))

        # Prev/Next split left/right on the same row, reading as a pair rather than bracketing the unlock/reset button column.
        nav_row = ctk.CTkFrame(pag_frame, fg_color="transparent")
        nav_row.pack(pady=5, fill="x")
        self.prev_btn = ctk.CTkButton(nav_row, text=self.tr('prev_button'), command=self.prev_page)
        self.prev_btn.pack(side='left', fill="x", expand=True, padx=(0, 3))
        self.next_btn = ctk.CTkButton(nav_row, text=self.tr('next_button'), command=self.next_page)
        self.next_btn.pack(side='left', fill="x", expand=True, padx=(3, 0))

        self.page_label = ctk.CTkLabel(pag_frame, text=self.tr('page_label').format(current=self.current_page, total=self.total_pages))
        self.page_label.pack(pady=5, expand=True, fill="both")

        # Single column of Unlock/Reset buttons for the active class (one row per difficulty).
        self.active_mission_unlock_buttons = []
        self.active_mission_reset_buttons = []
        # Wrapping the 5 rows in a horizontally-scrollable, fixed-width frame caps the footprint regardless of translated text length, since longer languages would otherwise blow out pag_frame's width.
        self.mission_btn_scroll = ctk.CTkScrollableFrame(
            pag_frame, orientation="horizontal", width=340, height=190,
            fg_color="transparent"
        )
        self.mission_btn_scroll.pack(pady=6, fill='x')
        self._exempt_from_global_scroll(self.mission_btn_scroll)
        btn_frame = self.mission_btn_scroll
        try:
            # Shared widths (not per-button _fit_text_button_width) so every Unlock button lines up with every other Unlock button, same for Reset, instead of each being sized to its own text length.
            unlock_w, reset_w = self._mission_button_col_widths()
            for d_idx, d in enumerate(self.mission_diffs):
                row = ctk.CTkFrame(btn_frame, fg_color="transparent")
                row.pack(pady=2, fill='x')
                # small difficulty short label
                diff_label = ctk.CTkLabel(row, text=self.mission_diffs_short[d_idx], width=40)
                diff_label.pack(side='left', padx=(2,6))
                unlock_text = self.tr('unlock_button').format(difficulty=d)
                unlock_btn = ctk.CTkButton(
                    row,
                    text=unlock_text,
                    fg_color=self.colors[d_idx],
                    text_color=self.text_colors[d_idx],
                    width=unlock_w,
                    command=lambda di=d_idx: self.unlock_mission(self.active_mission_class, di)
                )
                unlock_btn.pack(side='left', padx=4)
                reset_text = self.tr('reset_button').format(difficulty=d)
                reset_btn = ctk.CTkButton(
                    row,
                    text=reset_text,
                    width=reset_w,
                    command=lambda di=d_idx: self.reset_mission(self.active_mission_class, di)
                )
                reset_btn.pack(side='left')
                self.active_mission_unlock_buttons.append(unlock_btn)
                self.active_mission_reset_buttons.append(reset_btn)
        except Exception as e:
            self._warn(e)

        # Ensure the mission sheet marks Ranger (index 0) active on startup and refresh labels
        try:
            if not hasattr(self, 'active_mission_class'):
                self.active_mission_class = 0
            self.set_active_mission_class(0)
        except Exception as e:
            self._warn(e)

        # Populate the Boring Missions field/checkboxes for the active game at startup with the user's saved list or the hardcoded default.
        try:
            self.refresh_boring_missions_field()
        except Exception as e:
            self._warn(e)

        # Achievements section: 650 comfortably fits both the achievement sheet and the compact kill_sheet.
        ach_frame = ctk.CTkFrame(self.achievement_content)
        ach_frame.pack(fill="both", expand=True)
        ach_frame.grid_rowconfigure(0, weight=1)
        ach_frame.grid_columnconfigure(0, weight=1, minsize=600)
        ach_frame.grid_columnconfigure(1, weight=1, minsize=400)
        # Left: Achievements List - the same tksheet widget as Kill Statistics (right) for consistent look/behavior.
        ach_frame_left = ctk.CTkFrame(ach_frame)
        ach_frame_left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ach_frame_left.grid_columnconfigure(0, weight=1)
        self.achievements_box_label = ctk.CTkLabel(ach_frame_left, text=self.tr('achievements_box_label'), font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"))
        self.achievements_box_label.translation_key = 'achievements_box_label'
        self.achievements_box_label.pack(pady=(0, 5), fill="x")

        ach_sheet_container = ctk.CTkFrame(ach_frame_left)
        ach_sheet_container.pack(fill="both", expand=True)
        self._exempt_from_global_scroll(ach_sheet_container)
        self.ach_sheet = Sheet(
            ach_sheet_container,
            height=560,
            width=580,
            show_y_scrollbar=True,
            show_x_scrollbar=False,
            # Was leaving a big blank strip to the right of the Unlocked column whenever the
            # panel was wider than the two columns' fixed pixel widths - tksheet doesn't stretch
            # columns to fill unused width on its own. auto_resize_columns tells it to proportionally
            # grow every column (respecting this as each one's minimum) to use all available space.
            auto_resize_columns=60,
            font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
            header_font=(FONT_FAMILY, TABLE_HEADER_FONT_SIZE, "bold"),
            index_font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
            popup_menu_font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
        )
        self.ach_sheet.pack(expand=True, fill="both")
        # ID column dropped - it duplicated tksheet's own built-in row index.
        ach_columns = [
            self.tr('achievement_table_col_name'),
            self.tr('achievement_table_col_unlocked')
        ]
        self.ach_sheet.headers(ach_columns)
        # Widths are re-applied in update_achievement_table() - tksheet resets them once real data is pushed in via set_sheet_data().
        # Unlocked only ever holds "Yes"/"No" (EDF6/EDF5) so it doesn't need much - Name gets the rest.
        self.ach_sheet.column_width(0, 515)
        self.ach_sheet.column_width(1, 65)
        self.ach_sheet.readonly_columns(columns=[0, 1])  # Unlocked toggles via double-click, not freeform edit
        self.ach_sheet.enable_bindings(("single_select", "row_select", "copy"))
        self.ach_sheet.extra_bindings([("double_click_cell", self.on_achievement_cell_double_click)])
        self._suppress_sheet_wheel_propagation(self.ach_sheet)
        # Right: Kill Statistics - a compact, scrollable, editable tksheet table; values round-trip to TROPHY.DAT on Save.
        kills_frame = ctk.CTkFrame(ach_frame, width=400)
        kills_frame.grid(row=0, column=1, sticky="nsew")
        kills_frame.grid_columnconfigure(0, weight=1)
        kills_frame.grid_rowconfigure(1, weight=1)
        self.kills_box_label = ctk.CTkLabel(kills_frame, text=self.tr('kills_box_label'), font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"))
        self.kills_box_label.translation_key = 'kills_box_label'
        self.kills_box_label.pack(pady=(0, 5), fill="x")
        self.kill_field_keys = [
            'android_kills','super_android_kills','high_mobility_android_kills','grenadier_kills','cyclops_kills','giant_grenadier_kills','giant_android_kills','king_kills','teleport_ship_kills','gamma_kills','deroys_kills','giant_tadpole_kills','tadpole_kills','colonists_kills','species_alpha_kills','mother_monster_kills','flying_aggressors_kills','queen_kills','beta_kills','high_grade_drone_kills','drone_kills','cosmonaut_kills','small_hive_kills','imperial_drone_kills','tier2_drone_kills','primer_kills','kruuls_kills','scylla_kills','erginues_kills','archeluses_kills','arnea_kills','offline_games_started','online_games_started','rescues_done','ring_kills','high_grade_excavators_kills','excavators_kills','shield_bearer_kills','high_grade_tier3_drone_kills','tier3_drone_kills','haze_kills','teleport_anchor_kills','tail_anchor_kills','kraken_kills','weapons_collected']

        kill_sheet_container = ctk.CTkFrame(kills_frame)
        kill_sheet_container.pack(fill="both", expand=True)
        self._exempt_from_global_scroll(kill_sheet_container)
        self.kill_sheet = Sheet(
            kill_sheet_container,
            height=560,
            width=380,
            show_y_scrollbar=True,
            # Was False: with EDF4.1's longer field names now in the mix (e.g. "Underground Tunnel
            # Exits Destroyed", "Easy Completion Rate Overall"), a fixed 260px Stat column silently
            # clipped text with no way to see the full label ("Armor Value Air Rai...", three
            # different "Easy Completion Ra..." rows all looking identical even though they're for
            # Overall/Fencer/Ranger respectively) - turned on so anything still too long to fit is
            # scrollable instead of invisible.
            show_x_scrollbar=True,
            # Same fix as ach_sheet above: proportionally grow columns to fill unused width
            # instead of leaving a blank strip past the Count column whenever the panel is wider
            # than Stat+Count's fixed pixel widths.
            auto_resize_columns=60,
            font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
            header_font=(FONT_FAMILY, TABLE_HEADER_FONT_SIZE, "bold"),
            index_font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
            popup_menu_font=(FONT_FAMILY, TABLE_FONT_SIZE, "normal"),
        )
        self.kill_sheet.pack(expand=True, fill="both")
        self.kill_sheet.headers([self.tr('kill_table_col_stat', 'Stat'), self.tr('kill_table_col_count', 'Count')])
        self.kill_sheet.set_sheet_data(
            [[self.tr(key, key.replace('_', ' ').title()), "0"] for key in self.kill_field_keys],
            redraw=False,
        )
        # Count only ever holds a plain int or a "NN.NN%" ClearRatio string (2 decimals max, see
        # format_clear_ratio_display()) - neither needs anywhere near 100px, so it stays narrow and
        # Stat (real field names now run long, e.g. "Easy Difficulty Completion Rate (Air Raider)")
        # gets the rest. Also re-applied in rebuild_kill_sheet_for_game() - tksheet resets column
        # widths once real data lands via set_sheet_data(), same as ach_sheet below.
        self.kill_sheet.column_width(0, 400)
        self.kill_sheet.column_width(1, 70)
        # Only the Count column (1) is editable - stat names are identity, not data.
        self.kill_sheet.readonly_columns(columns=[0])
        self.kill_sheet.enable_bindings(("single_select", "row_select", "edit_cell", "copy", "cut", "paste", "undo", "redo"))
        self.kill_sheet.extra_bindings([("edit_cell", self.on_kill_cell_edit)])
        self._suppress_sheet_wheel_propagation(self.kill_sheet)
        self.update_kill_fields()

        # Player 2 Data (Experimental) GUI section removed; the underlying export/import_player2_color_block functions are left in place.

        # Re-run theming now that every tksheet.Sheet exists - the earlier call only styled the ttk.Treeview widgets.
        try: self.update_tree_style()
        except Exception as e:
            self._warn(e)

        # sheet_container isn't at its real on-screen width yet during __init__ (window not drawn), so reset_sheet_formatting()'s fill-to-edge sizing is a no-op the first time; re-run it once after the window is actually mapped so the Mission column fills correctly on first load too, not just after a page turn/class switch.
        try: self.after(200, self.reset_sheet_formatting)
        except Exception as e:
            self._warn(e)
        # That one-shot only covered the window's size at launch - resizing or maximizing the
        # window afterward left the Mission column (and the dead grey strip before the pagination
        # sidebar it's meant to eliminate) stuck at whatever width was computed back then, since
        # nothing previously re-ran the fill-to-edge sizing on a live resize. Bound here instead.
        try: self.bind("<Configure>", self._on_root_configure_resize_sheet)
        except Exception as e:
            self._warn(e)

    # --- Config persistence ---
    def save_config(self):
        self.config_data['language'] = self.current_language
        if hasattr(self, 'controller_type_var'):
            self.config_data['controller_display'] = self.controller_type_var.get()
        # Persist current theme
        try:
            self.config_data['theme'] = 'dark' if ctk.get_appearance_mode().lower() == 'dark' else 'light'
        except Exception:
            # Fallback to switch state if appearance_mode unavailable
            try:
                self.config_data['theme'] = 'dark' if self.theme_switch.get() else 'light'
            except Exception as e:
                self._warn(e)
        if self.config_file_enabled:
            # Never let a settings write (permissions, read-only install dir, disk full) crash a
            # caller that didn't think to wrap this itself - some callers already did (belt-and-
            # suspenders), but this is the actual chokepoint, matching load_config()'s own
            # (FileNotFoundError, json.JSONDecodeError) handling on the read side.
            try:
                with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(self.config_data, f)
            except OSError as e:
                print(f"[WARN] Could not save config.json: {e}")
        # else: do nothing, keep in-memory only

    def load_config(self):
        if self.config_file_enabled:
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.current_language = config.get('language', 'en')
                self.language_var.set(self.language_map.get(self.current_language, "English"))
                # Load theme
                self.config_data['theme'] = config.get('theme', 'dark')
                self.current_theme = self.config_data['theme']
                # Merge these back rather than cherry-picking only language/theme, so they persist across restarts instead of resetting to {}.
                self.config_data['modded_mission_totals'] = config.get('modded_mission_totals', {})
                self.config_data['boring_missions'] = config.get('boring_missions', {})
                self.config_data['controller_display'] = config.get('controller_display', 'xbox')
                self.config_data['weapon_limit_mods_dir'] = config.get('weapon_limit_mods_dir', '')
            except (FileNotFoundError, json.JSONDecodeError):
                self.current_language = 'en'
                self.language_var.set("English")
        else:
            self.current_language = self.config_data.get('language', 'en')
            self.language_var.set(self.language_map.get(self.current_language, "English"))
            self.current_theme = self.config_data.get('theme', 'dark')

    # --- Language / Translation editor ---
    def change_language(self, language):  # backward compatibility
        # Accept either code or display name; prefer direct code
        if language in self.translations:
            self.on_language_change(language)
            return
        # If a display name was passed map to code
        reverse_map = {v: k for k, v in self.language_map.items()}
        code = reverse_map.get(language, 'en')
        self.on_language_change(code)

    def on_language_change(self, lang_code):
        if lang_code not in self.translations:
            return
        self.current_language = lang_code
        if hasattr(self, 'translation_lang_var'):
            try: self.translation_lang_var.set(lang_code)
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'language_selector'):
            try: self.language_selector.set(lang_code)
            except Exception as e:
                self._warn(e)
        try: self.update_ui_text()
        except Exception as e:
            self._warn(e)
        if hasattr(self, 'update_weapon_table_headers'):
            try: self.update_weapon_table_headers()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'update_weapon_table_names'):
            try: self.update_weapon_table_names()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'refresh_armor_labels'):
            try: self.refresh_armor_labels()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'refresh_loadout_labels'):
            try: self.refresh_loadout_labels()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'update_loadout_names'):
            try: self.update_loadout_names()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'update_achievement_table'):
            try: self.update_achievement_table()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'refresh_kill_labels'):
            try: self.refresh_kill_labels()
            except Exception as e:
                self._warn(e)
        try: update_displays(self)
        except Exception as e:
            self._warn(e)
        if hasattr(self, 'filter_table'):
            try: self.filter_table()
            except Exception as e:
                self._warn(e)
        try: self.update_search_placeholder()
        except Exception as e:
            self._warn(e)
        if hasattr(self, 'update_translation_tab'):
            try: self.update_translation_tab()
            except Exception as e:
                self._warn(e)
        self.save_config()

    def on_translation_lang_change(self, lang):
        # The OptionMenu passes a display name; accept either code or display name
        if lang in self.translations:
            code = lang
            disp = self.language_map.get(code, code)
        else:
            code = self.language_map_reverse.get(lang, lang)
            disp = self.language_map.get(code, code)
        self.current_language = code  # sync app language with selection
        # Ensure the var shows the display name
        try:
            self.translation_lang_var.set(disp)
        except Exception as e:
            self._warn(e)
        # Refresh all language dependent UI
        if hasattr(self, 'update_ui_text'):
            self.update_ui_text()
        if hasattr(self, 'update_weapon_table_headers'):
            self.update_weapon_table_headers()
        if hasattr(self, 'update_weapon_table_names'):
            self.update_weapon_table_names()
        if hasattr(self, 'update_mission_table'):
            try:
                self.update_mission_table()
            except Exception as e:
                self._warn(e)
        # Refresh translation editor view last
        self.update_translation_tab()

    def add_new_language(self):
        new_code = simpledialog.askstring("New Language Code", "Enter new language code (e.g. 'fr'):")
        if not new_code:
            return
        new_code = new_code.strip()
        if not new_code or any(new_code.upper() == existing.upper() for existing in self.translations):
            return
        new_name = simpledialog.askstring("New Language Name", "Enter display name for this language:")
        if not new_name:
            return
        # UI Strings clone
        self.translations[new_code] = self.translations.get('en', {}).copy()
        self.translations[new_code][new_code] = new_name
        def _seed_language(container, code):
            if not isinstance(container, dict):
                return
            langs = container.get('languages') if isinstance(container.get('languages'), dict) else container
            if code not in langs:
                langs[code] = dict(langs.get('en', {}))
        for game, game_data in self.weapon_names_lang.items():
            _seed_language(game_data, new_code)
        for game, game_data in self.mission_names_data.items():
            _seed_language(game_data, new_code)
        # Always persist via translation_data_path (the exe-adjacent folder), so a packaged build survives a restart instead of silently losing new languages.
        try:
            with open(translation_data_path('languages.json'), 'w', encoding='utf-8') as f: json.dump({'languages': self.translations}, f, ensure_ascii=False, indent=2)
            with open(translation_data_path('WeaponNamesLang.json'), 'w', encoding='utf-8') as f: json.dump(self.weapon_names_lang, f, ensure_ascii=False, indent=2)
            with open(translation_data_path('MissionNames.json'), 'w', encoding='utf-8') as f: json.dump(self.mission_names_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] Could not save new language files: {e}")
            messagebox.showwarning("Save Failed", f"New language was added in-memory but could not be saved to disk:\n{e}")
        # Update UI
        if hasattr(self, 'translation_lang_dropdown'):
            self.translation_lang_dropdown.configure(values=list(self.translations.keys()))
        self.translation_lang_var.set(new_code)
        self.current_language = new_code
        self.update_translation_tab()
        self.update_ui_text()

    def save_translation(self):
        # translation_lang_var holds a display name; map it to a language code if needed
        sel = self.translation_lang_var.get()
        if sel in self.translations:
            lang = sel
        else:
            lang = self.language_map_reverse.get(sel, sel)
        tab = self.translation_tab_var.get()
        json_text = self.translation_textbox.get("1.0", "end").strip()
        try:
            data = json.loads(json_text)
        except Exception as e:
            messagebox.showerror("Error", f"Invalid JSON: {e}")
            return
        # Disk writes below can fail (permissions, read-only media, disk full); the in-memory
        # dict update above always succeeds, so on a write failure the edit stays live in the UI
        # for this session but isn't silently reported as saved - mirrors add_new_language()'s
        # existing "saved in-memory but not to disk" handling instead of raising unhandled.
        try:
            if tab == "UI Strings":
                self.translations[lang] = data
                with open(translation_data_path('languages.json'), 'w', encoding='utf-8') as f:
                    json.dump({"languages": self.translations}, f, ensure_ascii=False, indent=2)
            elif tab == "Weapon Names":
                base_game = self.get_weapon_data_key()
                if base_game not in self.weapon_names_lang:
                    self.weapon_names_lang[base_game] = {lang: data}
                else:
                    if 'languages' in self.weapon_names_lang[base_game]:
                        self.weapon_names_lang[base_game]['languages'][lang] = data
                    else:
                        self.weapon_names_lang[base_game][lang] = data
                with open(translation_data_path('WeaponNamesLang.json'), 'w', encoding='utf-8') as f:
                    json.dump(self.weapon_names_lang, f, ensure_ascii=False, indent=2)
            elif tab == "Mission Names":
                mission_key = self.missionlist_key
                if mission_key not in self.mission_names_data:
                    self.mission_names_data[mission_key] = {lang: data}
                else:
                    self.mission_names_data[mission_key][lang] = data
                with open(translation_data_path('MissionNames.json'), 'w', encoding='utf-8') as f:
                    json.dump(self.mission_names_data, f, ensure_ascii=False, indent=2)
                # Ensure in-memory reload to reflect any external structure adjustments
                self.reload_mission_names()  # Already refreshes the mission table live
        except Exception as e:
            print(f"[WARN] Could not save {tab} for '{lang}' to disk: {e}")
            messagebox.showwarning("Save Failed", f"{tab} for '{lang}' was updated in-memory but could not be saved to disk:\n{e}")
            return
        # Refresh the rest of the UI immediately (only meaningful if the edited language is the one on screen).
        if lang == self.current_language:
            if tab == "UI Strings":
                try: self.update_ui_text()
                except Exception as e: self._warn(e)
            elif tab == "Weapon Names":
                try: self.update_weapon_table_names()
                except Exception as e: self._warn(e)
        messagebox.showinfo("Saved", f"{tab} for '{lang}' saved.")
        self.update_translation_tab()

    def _translation_tab_label(self, canonical):
        """Translated display text for one of translation_tab_var's canonical English values; `canonical` must always be the internal English key."""
        key_map = {
            "UI Strings": 'translation_tab_ui_strings',
            "Weapon Names": 'translation_tab_weapon_names',
            "Mission Names": 'translation_tab_mission_names',
        }
        key = key_map.get(canonical)
        return self.tr(key, canonical) if key else canonical

    def _translation_tab_labels(self):
        return [self._translation_tab_label(c) for c in ("UI Strings", "Weapon Names", "Mission Names")]

    def on_translation_tab_display_change(self, display_value):
        """Map the clicked (possibly translated) label back to canonical, update translation_tab_var, and rebuild."""
        canonical_map = {self._translation_tab_label(c): c for c in ("UI Strings", "Weapon Names", "Mission Names")}
        self.translation_tab_var.set(canonical_map.get(display_value, display_value))
        self.update_translation_tab()

    def update_translation_tab(self, selected=None):
        for widget in self.translation_frame.winfo_children():
            widget.destroy()
        # Translation var stores a display name; map to code for lookups
        sel = self.translation_lang_var.get()
        lang = sel if sel in self.translations else self.language_map_reverse.get(sel, self.current_language)
        tab = self.translation_tab_var.get()
        label = ctk.CTkLabel(
            self.translation_frame,
            text=self.tr('translation_editing_label', 'Editing: {tab} ({lang})').format(
                tab=self._translation_tab_label(tab), lang=lang
            ),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold")
        )
        label.pack(anchor="w", pady=(0, 5))
        self.translation_textbox = ctk.CTkTextbox(self.translation_frame, height=300, font=(FONT_FAMILY, BASE_FONT_SIZE))
        self.translation_textbox.pack(fill="both", expand=True)
        self._suppress_textbox_wheel_propagation(self.translation_textbox)
        data = {}
        if tab == "UI Strings":
            data = self.translations.get(lang, {})
        elif tab == "Weapon Names":
            base_game = self.get_weapon_data_key()
            game_block = self.weapon_names_lang.get(base_game, {})
            if 'languages' in game_block:
                data = game_block.get('languages', {}).get(lang, {})
            else:
                data = game_block.get(lang, {})
        elif tab == "Mission Names":
            mission_key = self.missionlist_key
            data = self.mission_names_data.get(mission_key, {}).get(lang, {})
        self.translation_textbox.delete("1.0", "end")
        self.translation_textbox.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
        save_btn = ctk.CTkButton(self.translation_frame, text=self.tr('save_translation_button'), command=self.save_translation)
        save_btn.pack(pady=5, anchor="e")

    # --- UI text refresh cluster (all driven by update_ui_text) ---
    def update_ui_text(self):
        trans = self._trans_dict()
        # Title
        try:
            base_title = self.tr('title')
            if hasattr(self, 'version'):
                self.title(f"{base_title} {self.version}")
            else:
                self.title(base_title)
        except Exception as e:
            self._warn(e)
        if hasattr(self, 'save_btn'): self.save_btn.configure(text=self.tr('save_button'))
        if hasattr(self, 'load_btn'): self.load_btn.configure(text=self.tr('load_button'))
        if hasattr(self, 'theme_switch'): self.theme_switch.configure(text=self.tr('theme_switch'))
        if hasattr(self, 'profile_frame'):
            for child in self.profile_frame.winfo_children():
                if isinstance(child, ctk.CTkLabel) and child is not self.profile_name_label:
                    child.configure(text=self.tr('profile_label'))
        if hasattr(self, 'playtime_frame'):
            for child in self.playtime_frame.winfo_children():
                if isinstance(child, ctk.CTkLabel) and child is not self.playtime_label:
                    child.configure(text=self.tr('playtime_label'))
        # Pagination / navigation
        if hasattr(self, 'prev_btn'): self.prev_btn.configure(text=self.tr('prev_button'))
        if hasattr(self, 'next_btn'): self.next_btn.configure(text=self.tr('next_button'))
        if hasattr(self, 'page_label'): self.page_label.configure(text=self.tr('page_label').format(current=self.current_page, total=self.total_pages))
        if hasattr(self, 'search_entry'):
            try: self.update_search_placeholder()
            except Exception as e:
                self._warn(e)
        # Mission completion legend
        if hasattr(self, 'completion_legend_label'):
            yn_yes = self.tr('mission_table_cell_yes'); yn_no = self.tr('mission_table_cell_no')
            self.completion_legend_label.configure(text=f"{yn_yes}: {self.tr('mission_table_cell_yes_desc')}   {yn_no}: {self.tr('mission_table_cell_no_desc')}")
        if hasattr(self, 'unlock_legend_label'):
            self.unlock_legend_label.configure(text=self.tr('unlock_legend_text'))
        if hasattr(self, 'kills_box_label'):
            try:
                self.kills_box_label.configure(text=trans.get(getattr(self.kills_box_label, 'translation_key', 'kills_box_label'), 'Battle History Statistics (double-click Count to edit)'))
            except Exception as e:
                self._warn(e)
        for key in ['armor_section','loadouts_section','weapon_table_section','weapon_farming_section','mission_table_section','achievements_section','translation_section','save_paths_section','color_section','keyconfig_section']:
            btn_attr = f"{key}_button"
            content_attr = f"{key}_content"
            if hasattr(self, btn_attr):
                btn = getattr(self, btn_attr)
                opened = hasattr(self, content_attr) and getattr(self, content_attr).winfo_ismapped()
                t_key = getattr(btn, 'translation_key', key)
                btn.configure(text=trans.get(t_key, t_key) + (" ▼" if opened else " ▶"))
        # Update save paths section info + copy buttons
        if hasattr(self, 'save_paths_section_content'):
            try:
                for child in self.save_paths_section_content.winfo_children():
                    if isinstance(child, ctk.CTkLabel) and 'save directories' in child.cget('text').lower():
                        child.configure(text=self.tr('save_paths_info'))
                    elif isinstance(child, ctk.CTkFrame):
                        for w in child.winfo_children():
                            if isinstance(w, ctk.CTkButton) and w.cget('text') in ('Copy', self.tr('copy_button', 'Copy')):
                                w.configure(text=self.tr('copy_button'))
            except Exception as e:
                self._warn(e)
        # How-to-use instructions (translation_key-tagged, unlike the generic loop above)
        if hasattr(self, 'save_paths_howto_header_label'):
            self.save_paths_howto_header_label.configure(text=self.tr('save_paths_howto_header'))
        if hasattr(self, 'save_paths_howto_labels'):
            for key, lbl in self.save_paths_howto_labels.items():
                lbl.configure(text=trans.get(key, lbl.cget('text')))
        # Refresh dependent labels
        try: self.refresh_armor_labels()
        except Exception as e:
            self._warn(e)
        try: self.refresh_loadout_labels()
        except Exception as e:
            self._warn(e)
        try: self.refresh_mission_labels()
        except Exception as e:
            self._warn(e)
        try: self.refresh_weapon_farming_labels()
        except Exception as e:
            self._warn(e)
        try: self.refresh_kill_labels()
        except Exception as e:
            self._warn(e)
        try: self.refresh_color_labels()
        except Exception as e:
            self._warn(e)
        try: self.refresh_weapon_table_controls()
        except Exception as e:
            self._warn(e)
        try: self.refresh_placeholder_labels()
        except Exception as e:
            self._warn(e)
        try: self.refresh_translation_editor_controls()
        except Exception as e:
            self._warn(e)
        try: self.refresh_color_selector_controls()
        except Exception as e:
            self._warn(e)
        try: self.refresh_keyconfig_selector_controls()
        except Exception as e:
            self._warn(e)
        try: self.refresh_weapon_farming_diff_dropdown()
        except Exception as e:
            self._warn(e)

    def _collect_label_widgets(self, container):
        """Recursively gathers CTkLabel/CTkButton widgets under `container` in creation order,
        descending into child CTkFrames. Added 2026-09-07 so refresh_armor_labels() keeps working
        after the Armor tab's per-class rows became 2-row cards (card -> row1/row2 sub-frames ->
        actual label/button widgets) instead of one flat frame of widgets."""
        out = []
        for w in container.winfo_children():
            if isinstance(w, (ctk.CTkLabel, ctk.CTkButton)):
                out.append(w)
            elif isinstance(w, ctk.CTkFrame):
                out.extend(self._collect_label_widgets(w))
        return out

    def refresh_armor_labels(self):
        trans = self._trans_dict()
        # Update multiplier label
        if hasattr(self, 'modded_multiplier_label_widget'):
            self.modded_multiplier_label_widget.configure(text=self.tr('modded_multiplier_label'))
        # Update note label
        for child in self.modded_frame.winfo_children():
            if isinstance(child, ctk.CTkLabel) and getattr(child, 'translation_key', '') == 'modded_gain_note':
                child.configure(text=self.tr('modded_gain_note'))
        # Update armor rows. Each armor_content child is now a 2-row card (added 2026-09-07) rather
        # than a flat row of widgets, so labels/buttons are gathered by recursing into the card's
        # row sub-frames instead of reading frame.winfo_children() directly - _collect_label_widgets
        # walks in creation order so row 1's widgets still come before row 2's.
        idx = 0
        for frame in self.armor_content.winfo_children():
            if frame is self.modded_frame:
                continue
            labels = self._collect_label_widgets(frame)
            if len(labels) < 2:
                continue
            class_name = PLAYER_CLASS_MAP[idx]
            # First label = armor label
            labels[0].configure(text=trans.get(f'{class_name.lower().replace(" ", "_")}_armor_label', f'{class_name} MAX Armor:'))
            # Second label = total armor label
            labels[1].configure(text=self.tr('total_armor_label'))
            # Base / modded gain labels, and the Modded Start/Rate labels, if present
            for lab in labels[2:]:
                key = getattr(lab, 'translation_key', '')
                if key == 'base_gain_label':
                    # Preserve numeric value portion after last space
                    try:
                        value_part = lab.cget('text').split(':')[-1]
                        lab.configure(text=self.tr('base_gain_label').format(value=value_part.strip()))
                    except Exception:
                        lab.configure(text=self.tr('base_gain_label').format(value=0.0))
                elif key == 'modded_gain_label':
                    try:
                        value_part = lab.cget('text').split(':')[-1]
                        lab.configure(text=self.tr('modded_gain_label').format(value=value_part.strip()))
                    except Exception:
                        lab.configure(text=self.tr('modded_gain_label').format(value=0.0))
                elif key == 'armor_modded_start_label':
                    lab.configure(text=self.tr('armor_modded_start_label', 'Modded Start:'))
                elif key == 'armor_modded_rate_label':
                    lab.configure(text=self.tr('armor_modded_rate_label', 'Modded Rate:'))
            idx += 1
        # armor_note_label is a sibling of the per-class frames, not walked by the loop above - refreshed directly.
        if hasattr(self, 'armor_note_label'):
            self.armor_note_label.configure(text=self.tr('armor_note'))
        # Update completion label pattern if exists
        if hasattr(self, 'completion_label'):
            try: self.update_completion()
            except Exception as e:
                self._warn(e)

    def rebuild_loadout_panel_for_game(self):
        """(Re)build self.loadout_grid's per-class rows for self.current_game - needed since EDF4.1's real loadout shape (4 slots/class) differs from EDF5/6's 6-slot grid. No-ops if this game's groups table is already built, to avoid losing in-progress edits."""
        if not hasattr(self, 'loadout_grid'):
            return
        game = getattr(self, 'current_game', 'EDF6')
        groups = get_loadout_groups(game)
        if groups is getattr(self, '_loadout_groups_built', None):
            return
        self._loadout_groups_built = groups
        is_edf41 = _game_is_edf41(game)
        for child in self.loadout_grid.winfo_children():
            child.destroy()
        self.loadout_entries = []
        self.loadout_name_labels = []

        row, col = 0, 0
        for class_name, slots in groups.items():
            class_subframe = ctk.CTkFrame(self.loadout_grid)
            # Slightly reduce vertical padding between class frames
            class_subframe.grid(row=row, column=col, pady=(4,1), padx=5, sticky="nsew")
            normalized = class_name.lower().replace(' ', '_')  # ensure Air Raider uses underscores
            class_label_key = f'{normalized}_loadout_label'
            header_label = ctk.CTkLabel(class_subframe, text=self.tr(class_label_key, f"{class_name} Loadout:"), font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"))
            header_label.translation_key = class_label_key
            header_label.pack(anchor="w", padx=5)
            for slot_index, slot in enumerate(slots):
                slot_desc = slot[3]
                # EDF4.1 gets its own slot_key namespace, since its slots mean something different than EDF6/5's (4 per class, no Primary/Backpack/Support distinction).
                slot_key = f"{normalized}_loadout_edf41_slot{slot_index+1}" if is_edf41 else f"{normalized}_loadout_slot{slot_index+1}"
                slot_frame = ctk.CTkFrame(class_subframe)
                slot_frame.pack(fill="x", padx=10, pady=2)
                # Grid (not pack) so every row's entry aligns to the same right-hand edge regardless of label length.
                slot_frame.grid_columnconfigure(0, weight=0)
                slot_frame.grid_columnconfigure(1, weight=1)
                slot_frame.grid_columnconfigure(2, weight=0)
                # One size up from the app's base text (14, not 13) - these rows were reading as too small for how much room this panel has.
                slot_label = ctk.CTkLabel(slot_frame, text=self.tr(slot_key, slot_desc) + ":", font=(FONT_FAMILY, BASE_FONT_SIZE + 1))
                slot_label.translation_key = slot_key
                slot_label.grid(row=0, column=0, sticky="w", padx=5, pady=3)
                # Weapon name sits after the label (scanned at a glance); the raw ID entry is pushed to the far right (only matters when changing it).
                name_label = ctk.CTkLabel(slot_frame, text="", font=(FONT_FAMILY, BASE_FONT_SIZE + 1), anchor="w")
                name_label.grid(row=0, column=1, sticky="w", padx=6, pady=3)
                self.loadout_name_labels.append(name_label)
                entry = ctk.CTkEntry(slot_frame, width=110, font=(FONT_FAMILY, BASE_FONT_SIZE + 1), fg_color=self.colors[4], text_color=self.text_colors[4])  # Same purple as the Armor tab's editable fields
                entry.grid(row=0, column=2, sticky="e", padx=5, pady=3)
                entry.insert(0, "0")
                entry.bind("<KeyRelease>", lambda e: self.update_loadout_names())
                self.loadout_entries.append(entry)
            col += 1
            if col == 2:
                col = 0
                row += 1

    def refresh_loadout_labels(self):
        trans = self._trans_dict()
        # Iterate through subframes matching this game's own loadout groups order.
        groups = get_loadout_groups(getattr(self, 'current_game', 'EDF6'))
        subframes = self.loadout_grid.winfo_children()
        for (class_name, slots), frame in zip(groups.items(), subframes):
            # First child is header label
            children = frame.winfo_children()
            if not children:
                continue
            header = children[0]
            if hasattr(header, 'translation_key'):
                key = header.translation_key
                lookup_key = key if key in trans else key.replace(' ', '_')
                header.configure(text=trans.get(lookup_key, header.cget('text').split(':')[0]) )
            # Remaining children are slot frames
            slot_frames = children[1:]
            for sf in slot_frames:
                for w in sf.winfo_children():
                    if isinstance(w, ctk.CTkLabel) and hasattr(w, 'translation_key'):
                        key = w.translation_key
                        lookup_key = key if key in trans else key.replace(' ', '_')
                        new_text = trans.get(lookup_key, w.cget('text').rstrip(':')) + ':'
                        w.configure(text=new_text)
                        break
        unknown = self.tr('unknown_label', 'Unknown')
        for lbl in getattr(self, 'loadout_name_labels', []):
            if not lbl.cget('text') or lbl.cget('text') in ('Unknown', unknown):
                lbl.configure(text=unknown)
        # loadout_note_label is a sibling of loadout_grid, not inside it, so refreshed directly.
        if hasattr(self, 'loadout_note_label'):
            self.loadout_note_label.configure(text=self.tr('loadout_note'))

    def refresh_mission_labels(self):
        """Update mission table class labels, difficulty button texts, and unlock/reset buttons for current language."""
        if not hasattr(self, 'mission_class_labels'):
            return
        trans = self._trans_dict()
        if hasattr(self, 'mission_content'):
            for child in self.mission_content.winfo_children():
                if isinstance(child, ctk.CTkLabel) and getattr(child, 'translation_key', '') == 'mission_table_note':
                    child.configure(text=trans.get('mission_table_note', child.cget('text')))
        classes_full = [
            self.tr('mission_table_col_ranger'),
            self.tr('mission_table_col_wingdiver'),
            self.tr('mission_table_col_airraider'),
            self.tr('mission_table_col_fencer')
        ]
        diffs_full = [
            self.tr('mission_table_col_easy'),
            self.tr('mission_table_col_normal'),
            self.tr('mission_table_col_hard'),
            self.tr('mission_table_col_hardest'),
            self.tr('mission_table_col_inferno')
        ]
        # Recompute the short abbreviations (used in mission sheet column headers) here too, mirroring classes_full/diffs_full, so they update on a language switch.
        self.mission_class_short_names = [
            self.tr('mission_table_col_ranger_short'),
            self.tr('mission_table_col_wingdiver_short'),
            self.tr('mission_table_col_airraider_short'),
            self.tr('mission_table_col_fencer_short'),
        ]
        self.mission_diffs_short = [
            self.tr('mission_table_col_easy_short'),
            self.tr('mission_table_col_normal_short'),
            self.tr('mission_table_col_hard_short'),
            self.tr('mission_table_col_hardest_short'),
            self.tr('mission_table_col_inferno_short'),
        ]
        self.mission_class_names = classes_full
        self.mission_diffs = diffs_full
        # Update class labels, preserving the active-class highlight (plain reassignment would wipe the "(Active)" tag and yellow/black styling).
        self._apply_mission_class_active_styling()
        # Refresh the per-class "View" button texts.
        if hasattr(self, 'mission_view_buttons'):
            for btn in self.mission_view_buttons:
                try: btn.configure(text=self.tr('view_button'))
                except Exception as e:
                    self._warn(e)
        if hasattr(self, 'unlock_defined_btn'):
            try: self.unlock_defined_btn.configure(text=self.tr('unlock_defined_button'))
            except Exception as e:
                self._warn(e)
        # Re-translate the "Missions:" total label so it doesn't stay stuck in the startup language.
        if hasattr(self, 'mst_total_label'):
            try: self.mst_total_label.configure(text=self.tr('mst_total_label', 'Missions:'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'boring_missions_label'):
            try: self.boring_missions_label.configure(text=self.tr('boring_missions_section_label'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'boring_missions_note_label'):
            try: self.boring_missions_note_label.configure(text=self.tr('boring_missions_note'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'boring_missions_entry'):
            try: self.boring_missions_entry.configure(placeholder_text=self.tr('boring_missions_placeholder'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'boring_diff_checkboxes'):
            for i, cb in enumerate(self.boring_diff_checkboxes):
                try: cb.configure(text=self.mission_diffs_short[i])
                except Exception as e:
                    self._warn(e)
        if hasattr(self, 'boring_class_checkboxes'):
            for i, cb in enumerate(self.boring_class_checkboxes):
                try: cb.configure(text=self.mission_class_names[i])
                except Exception as e:
                    self._warn(e)
        # Shared widths (not per-button _fit_text_button_width) so every Unlock/Reset button keeps lining up after a language switch, same as at initial build.
        _unlock_w, _reset_w = self._mission_button_col_widths()
        # Update unlock/reset button texts (defensive no-op today since these lists are always all-None; kept in case that changes).
        if hasattr(self, 'mission_unlock_buttons') and hasattr(self, 'mission_reset_buttons'):
            for c in range(len(self.mission_unlock_buttons)):
                for d in range(len(self.mission_unlock_buttons[c])):
                    try:
                        ub = self.mission_unlock_buttons[c][d]
                        rb = self.mission_reset_buttons[c][d]
                        if ub:
                            ub_text = self.tr('unlock_button').format(difficulty=diffs_full[d])
                            ub.configure(text=ub_text, width=_unlock_w)
                        if rb:
                            rb_text = self.tr('reset_button').format(difficulty=diffs_full[d])
                            rb.configure(text=rb_text, width=_reset_w)
                    except Exception:
                        continue
        # Refresh the real active unlock/reset buttons (the single side-panel column for the currently-viewed class) directly, not just as a side effect of switching class view.
        if hasattr(self, 'active_mission_unlock_buttons') and hasattr(self, 'active_mission_reset_buttons'):
            for di, btn in enumerate(self.active_mission_unlock_buttons):
                try:
                    dname = diffs_full[di]
                    text = self.tr('unlock_button').format(difficulty=dname)
                    btn.configure(text=text, width=_unlock_w)
                except Exception as e:
                    self._warn(e)
            for di, btn in enumerate(self.active_mission_reset_buttons):
                try:
                    dname = diffs_full[di]
                    text = self.tr('reset_button').format(difficulty=dname)
                    btn.configure(text=text, width=_reset_w)
                except Exception as e:
                    self._warn(e)
            # Clear any stale canvas ghost left behind by the width changes above.
            self._redraw_mission_btn_scroll()
        # Update sheet headers & data via existing method
        if hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception as e:
                self._warn(e)

    def refresh_kill_labels(self):
        """Update the Kill Statistics sheet's Stat-name column + headers when language changes."""
        if not hasattr(self, 'kill_sheet'):
            return
        trans = self._trans_dict()
        if not self.kill_field_keys:
            # EDF4.1 has no kill fields today, just a single explanatory row - re-translate it too.
            try:
                self.kill_sheet.set_cell_data(0, 0, self.tr('kill_table_unavailable', "Not yet available for this game"), redraw=False)
            except Exception as e:
                self._warn(e)
        for r, key in enumerate(self.kill_field_keys):
            name = trans.get(key, key.replace('_', ' ').title())
            try:
                self.kill_sheet.set_cell_data(r, 0, name, redraw=False)
            except Exception as e:
                self._warn(e)
        try:
            self.kill_sheet.headers([self.tr('kill_table_col_stat', 'Stat'), self.tr('kill_table_col_count', 'Count')])
            self.kill_sheet.redraw(True)
        except Exception as e:
            self._warn(e)
        if hasattr(self, 'kills_box_label'):
            try: self.kills_box_label.configure(text=self.tr('kills_box_label'))
            except Exception as e:
                self._warn(e)

    def refresh_color_labels(self):
        """Update Color Customization panel labels when language changes."""
        if not hasattr(self, 'color_class_label_widget'):
            return
        trans = self._trans_dict()
        self.color_class_label_widget.configure(text=self.tr('color_class_label'))
        self.color_tier_label_widget.configure(text=self.tr('color_tier_label'))
        primary_word = self.tr('color_primary_header')
        secondary_word = self.tr('color_secondary_header')
        swatch_prefix = self.tr('color_swatch_id_label')
        for widget in self.color_swatch_id_label_widgets.values():
            widget.configure(text=swatch_prefix)
        for is_secondary, widget in self.color_column_title_widgets.items():
            widget.configure(text=secondary_word if is_secondary else primary_word)
        if hasattr(self, 'color_warning_label'):
            self.color_warning_label.configure(text=trans.get('color_panel_warning', self.color_warning_label.cget('text')))
        if hasattr(self, 'color_player_toggle_btn'):
            self.color_player_toggle_btn.configure(text=self._color_player_toggle_text(getattr(self, 'color_player_slot', 1)))
        # Refresh the 24 "Pick Color UI" buttons (12 palette rows x Primary/Secondary).
        pick_text = self.tr('color_pick_button')
        for rows in getattr(self, 'color_palette_rows', {}).values():
            for row in rows:
                btn = row.get('pick_btn')
                if btn is not None:
                    try: btn.configure(text=pick_text)
                    except Exception as e:
                        self._warn(e)

    def on_browse_weapon_limit_folder(self):
        """Browse-button handler for the WeaponLimit mod's Mods folder setting (see the
        weapon_limit_frame comment in build_weapon_farming_section/__init__ for what this is
        for). Persists to config.json immediately, same pattern as other settings fields."""
        initial = self.weapon_limit_dir_var.get().strip() if hasattr(self, 'weapon_limit_dir_var') else ''
        initial_dir = initial if os.path.isdir(initial) else None
        folder = filedialog.askdirectory(title=self.tr('weapon_limit_dir_dialog_title', "Select the EDF6 install's Mods folder"), initialdir=initial_dir)
        if folder:
            self.weapon_limit_dir_var.set(folder)
            self.on_weapon_limit_folder_changed()

    def on_weapon_limit_folder_changed(self, event=None):
        """Entry Return/FocusOut handler: persist the typed/browsed Mods folder path to
        config.json and refresh the status line. A blank or nonexistent path just clears the
        setting - editing then stays limited to whatever load_save_data found in MAIN.GST."""
        if not hasattr(self, 'weapon_limit_dir_var'):
            return
        path = self.weapon_limit_dir_var.get().strip()
        self.config_data['weapon_limit_mods_dir'] = path
        try:
            self.save_config()
        except Exception as e:
            self._warn(e)
        self.refresh_weapon_limit_status()

    def refresh_weapon_limit_status(self):
        """Update the WeaponLimit status line under the Mods-folder field: whether a folder is
        configured at all, and if so, how many slots each save slot's own edf6_weapons_slotNN.bin
        sidecar reports - scanned directly off disk via get_weapon_limit_bin_path()/
        load_weapon_limit_bin() for slots 0-3, independent of whichever save is currently loaded
        (0 for a slot with no sidecar yet)."""
        if not hasattr(self, 'weapon_limit_status_label'):
            return
        path = self.config_data.get('weapon_limit_mods_dir', '') if hasattr(self, 'config_data') else ''
        if not path or not os.path.isdir(path):
            text = self.tr('weapon_limit_status_not_set',
                           "Not set - editing is limited to the base 2048 weapon slots. Point this at your EDF6 install's Mods folder to edit WeaponLimit's extra slots.")
        else:
            counts = []
            any_found = False
            for slot in range(4):
                n = 0
                try:
                    bin_path = get_weapon_limit_bin_path(self, slot)
                    if bin_path and os.path.isfile(bin_path):
                        _declared, entries = load_weapon_limit_bin(bin_path)
                        if entries:
                            n = len(entries)
                            any_found = True
                except Exception as e:
                    self._warn(e)
                counts.append(self.tr('weapon_limit_slot_count', "{n} slots for SS{slot}").format(n=n, slot=slot))
            if any_found:
                text = self.tr('weapon_limit_status_detected', "Detected Weapon Bin Table: {counts}.").format(counts=", ".join(counts))
            else:
                text = self.tr('weapon_limit_status_no_sidecar',
                               "Mods folder is set, but no edf6_weapons_slotNN.bin was found in it yet - showing the base 2048 slots.")
        try:
            self.weapon_limit_status_label.configure(text=text)
        except Exception as e:
            self._warn(e)

    def on_weapon_limit_source_changed(self, _value=None):
        """Segmented-button handler for the BIN/GST 'Viewing:' switch."""
        try:
            self.refresh_weapon_table_view()
        except Exception as e:
            self._warn(e)

    def refresh_weapon_table_view(self):
        """Repopulate the Weapon Table's condition/stat columns from whichever source is
        currently selected - BIN (app.weapon_data, the editable/save-authoritative table, always
        shown in full - every slot WeaponLimit loaded) or GST (app.weapon_limit_gst_snapshot, a
        read-only snapshot of MAIN.GST's own values taken before the sidecar merge - see the
        weapon_limit_source_row comment in build_weapon_farming_section/__init__, naturally capped
        at whatever MAIN.GST itself held). Also flips the read-only gate on individual cell edits
        (double-click) while viewing GST - the Own All/Sudo Max/Poverty mass-edit buttons stay
        enabled either way, since they always target app.weapon_data (BIN) regardless of which
        table is currently on screen. Finishes with a diff/highlight refresh and filter_table() so
        row visibility matches the new source's cutoff. Called after every load, after Port, and
        whenever the BIN/GST switch changes."""
        if not hasattr(self, 'tree'):
            return
        source = self.weapon_limit_source_var.get() if hasattr(self, 'weapon_limit_source_var') else 'GST'
        is_gst = (source == 'GST')
        self._weapon_table_read_only = is_gst
        data = getattr(self, 'weapon_limit_gst_snapshot', []) if is_gst else getattr(self, 'weapon_data', [])
        for idx, row in enumerate(data or []):
            iid = str(idx)
            if not self.tree.exists(iid):
                continue
            try:
                self.tree.item(iid, values=row)
            except Exception as e:
                self._warn(e)
        for btn_name in ('own_all_btn', 'sudo_max_btn', 'poverty_btn'):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                try:
                    btn.configure(state='normal')
                except Exception as e:
                    self._warn(e)
        try:
            self.refresh_weapon_limit_diff_display()
        except Exception as e:
            self._warn(e)
        try:
            self.filter_table()
        except Exception as e:
            self._warn(e)

    def refresh_weapon_limit_diff_display(self):
        """Recompute which slots currently disagree between GST and BIN
        (EDFSaveEditorLogic.compute_weapon_limit_diff), tag those rows in the tree for a visible
        highlight regardless of which source is being viewed, and update the diff-count label +
        enable/disable the Port button. Called after every load/view-switch (via
        refresh_weapon_table_view) and after anything that edits weapon_data - direct cell edits,
        mass-edit, Port itself - so the highlight and count never go stale."""
        if not hasattr(self, 'tree'):
            return
        gst_snapshot = getattr(self, 'weapon_limit_gst_snapshot', []) or []
        weapon_data = getattr(self, 'weapon_data', []) or []
        diff = compute_weapon_limit_diff(weapon_data, gst_snapshot) if gst_snapshot else set()
        self.weapon_limit_diff_indices = diff
        try:
            self.tree.tag_configure('weaponlimit_diff', background='#4a3a1a')
        except Exception as e:
            self._warn(e)
        for idx in range(len(weapon_data)):
            iid = str(idx)
            if not self.tree.exists(iid):
                continue
            try:
                self.tree.item(iid, tags=('weaponlimit_diff',) if idx in diff else ())
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'weapon_limit_diff_label'):
            n = len(diff)
            text = (self.tr('weapon_limit_diff_count', "{n} slot(s) differ from GST.").format(n=n) if n
                    else self.tr('weapon_limit_diff_count_zero', "GST and BIN agree on every slot."))
            try:
                self.weapon_limit_diff_label.configure(text=text)
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'weapon_limit_port_btn'):
            try:
                self.weapon_limit_port_btn.configure(state='normal' if diff else 'disabled')
            except Exception as e:
                self._warn(e)

    def on_click_port_gst_to_bin(self):
        """'Port GST -> BIN' button: copies every currently-disagreeing slot's condition+stats
        from the read-only GST snapshot into the editable/save-authoritative table
        (app.weapon_data), via EDFSaveEditorLogic.port_weapon_limit_gst_to_bin(). This only edits
        the in-memory working table, exactly like any other weapon-table edit - it still has to go
        through the normal Save button to actually reach MAIN.GST and the sidecar .bin on disk."""
        if not hasattr(self, 'weapon_data'):
            return
        changed = port_weapon_limit_gst_to_bin(self)
        if not changed:
            return
        source = self.weapon_limit_source_var.get() if hasattr(self, 'weapon_limit_source_var') else 'GST'
        for idx in changed:
            iid = str(idx)
            if not self.tree.exists(iid):
                continue
            try:
                row = self.weapon_limit_gst_snapshot[idx] if source == 'GST' else self.weapon_data[idx]
                self.tree.item(iid, values=row)
            except Exception as e:
                self._warn(e)
        try:
            self.refresh_weapon_limit_diff_display()
        except Exception as e:
            self._warn(e)
        if hasattr(self, 'weapon_limit_status_label'):
            try:
                self.weapon_limit_status_label.configure(text=self.tr(
                    'weapon_limit_ported', "Ported {n} slot(s) from GST to BIN - click Save to write it to disk.").format(n=len(changed)))
            except Exception as e:
                self._warn(e)

    def refresh_weapon_table_controls(self):
        """Refresh the mass-edit buttons (Own All/Sudo Max/Poverty) and the instruction note above the weapon table on a language switch."""
        if hasattr(self, 'own_all_btn'):
            self.own_all_btn.configure(text=self.tr('own_all_button'))
        if hasattr(self, 'sudo_max_btn'):
            self.sudo_max_btn.configure(text=self.tr('sudo_max_button'))
        if hasattr(self, 'poverty_btn'):
            self.poverty_btn.configure(text=self.tr('poverty_button'))
        note_text = self.tr('weapon_table_note')
        if getattr(self, 'weapon_table_note_box', None) is not None:
            try:
                self.weapon_table_note_box.configure(state='normal')
                self.weapon_table_note_box.delete('1.0', 'end')
                self.weapon_table_note_box.insert('1.0', note_text)
                self.weapon_table_note_box.configure(state='disabled')
            except Exception as e:
                self._warn(e)
        elif hasattr(self, 'weapon_table_note_label'):
            self.weapon_table_note_label.configure(text=note_text)

    def refresh_placeholder_labels(self):
        """Refresh the "Not Loaded" placeholder text on the Profile/Playtime header labels on a language switch (no-ops once a save is actually loaded)."""
        if getattr(self, 'current_file', None) is not None:
            return
        placeholder = self.tr('load_save_info')
        if hasattr(self, 'profile_name_label'):
            self.profile_name_label.configure(text=placeholder)
        if hasattr(self, 'playtime_label'):
            self.playtime_label.configure(text=placeholder)

    def refresh_translation_editor_controls(self):
        """Retranslate the Translation Editor's own static controls (add_lang_btn, the tab segmented control's labels) on a language switch."""
        if hasattr(self, 'add_lang_btn'):
            try: self.add_lang_btn.configure(text=self.tr('add_language_button', 'Add Language'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'translation_segmented') and hasattr(self, 'translation_tab_display_var'):
            try:
                self.translation_segmented.configure(values=self._translation_tab_labels())
                current_canonical = self.translation_tab_var.get() if hasattr(self, 'translation_tab_var') else "UI Strings"
                self.translation_tab_display_var.set(self._translation_tab_label(current_canonical))
            except Exception as e:
                self._warn(e)
        # Re-run update_translation_tab() so the "Editing: {tab} ({lang})" label picks up the new language immediately.
        if hasattr(self, 'update_translation_tab'):
            try: self.update_translation_tab()
            except Exception as e:
                self._warn(e)

    def refresh_color_selector_controls(self):
        """Retranslate the Color Customization panel's Class/Tier dropdown display values on a language switch, keeping color_class_var/color_tier_var canonical (English) via a parallel display var, since those are used for COLOR_CLASSES/COLOR_TIERS index lookups elsewhere."""
        if not hasattr(self, 'color_class_menu'):
            return
        try:
            class_labels = [self._color_class_label(c) for c in COLOR_CLASSES]
            self.color_class_menu.configure(values=class_labels)
            self.color_class_display_var.set(self._color_class_label(self.color_class_var.get()))
        except Exception as e:
            self._warn(e)
        try:
            # EDF4.1 has no skin/tier system, only tier_idx 0 ("Soldier") is real storage, so its Tier dropdown only offers that one tier.
            game = getattr(self, 'current_game', 'EDF6')
            visible_tiers = COLOR_TIERS[:1] if _game_is_edf41(game) else COLOR_TIERS
            tier_labels = [self._color_tier_label(t) for t in visible_tiers]
            self.color_tier_menu.configure(values=tier_labels)
            if self.color_tier_var.get() not in visible_tiers:
                self.color_tier_var.set(visible_tiers[0])
                self.on_color_selector_changed()
            self.color_tier_display_var.set(self._color_tier_label(self.color_tier_var.get()))
        except Exception as e:
            self._warn(e)

    def refresh_weapon_farming_diff_dropdown(self):
        """Retranslate the Weapon Farming Helper's Difficulty: dropdown display values on a language switch, keeping farming_diff_var canonical since it's used as a dict key elsewhere."""
        if not hasattr(self, 'farming_diff_dropdown'):
            return
        try:
            labels = [self._mission_diff_label(d) for d in wf.DIFFICULTY_ORDER]
            self.farming_diff_dropdown.configure(values=labels)
            self.farming_diff_display_var.set(self._mission_diff_label(self.farming_diff_var.get()))
        except Exception as e:
            self._warn(e)

    def update_tree_style(self):
        appearance_mode = ctk.get_appearance_mode()
        style = ttk.Style()
        # Switch to the "clam" ttk theme so style.configure() overrides (header borders/relief) actually take effect, unlike the platform-native default theme.
        try:
            style.theme_use('clam')
        except Exception as e:
            self._warn(e, 'update_tree_style theme_use')
        # Set font explicitly since "clam" falls back to the platform default font instead of this app's Arial scheme.
        if (appearance_mode == "Dark"):
            style.configure("Treeview", background="#2a2d2e", foreground="white", fieldbackground="#2a2d2e", bordercolor="#4a4a4a", borderwidth=1, font=(FONT_FAMILY, TABLE_FONT_SIZE))
            style.map("Treeview", background=[('selected', "#22559b")], foreground=[('selected', "white")])
            style.configure("Treeview.Heading", background="#333333", foreground="white", relief="flat", bordercolor="#4a4a4a", borderwidth=1, font=(FONT_FAMILY, TABLE_HEADER_FONT_SIZE, "bold"))
            style.map("Treeview.Heading", background=[('active', "#2a4066")], foreground=[('active', "white")])
        else:
            style.configure("Treeview", background="white", foreground="black", fieldbackground="white", bordercolor="#b0b0b0", borderwidth=1, font=(FONT_FAMILY, TABLE_FONT_SIZE))
            style.map("Treeview", background=[('selected', "#add8e6")], foreground=[('selected', "black")])
            style.configure("Treeview.Heading", background="#cccccc", foreground="#333333", relief="flat", bordercolor="#b0b0b0", borderwidth=1, font=(FONT_FAMILY, TABLE_HEADER_FONT_SIZE, "bold"))
            style.map("Treeview.Heading", background=[('active', "#a3bffa")], foreground=[('active', "#333333")])
        self._restyle_tksheet_tables(appearance_mode)
        try:
            self._restyle_color_grid(appearance_mode)
        except Exception as e:
            self._warn(e)

    def _restyle_tksheet_tables(self, appearance_mode=None):
        """Apply the same color palette as the ttk.Treeview styling above to every tksheet.Sheet in the app (mission table, Achievements, Kill Statistics), matching the app's dark/light setting; safe to call anytime, including from toggle_theme()."""
        if appearance_mode is None:
            appearance_mode = ctk.get_appearance_mode()
        if appearance_mode == "Dark":
            options = dict(
                table_bg="#2a2d2e", table_fg="white", table_grid_fg="gray",
                table_selected_cells_bg="#22559b", table_selected_cells_fg="white",
                header_bg="#333333", header_fg="white",
                header_selected_cells_bg="#2a4066", header_selected_cells_fg="white",
                header_selected_columns_bg="#22559b", header_selected_columns_fg="white",
                index_bg="#333333", index_fg="white",
                index_selected_rows_bg="#22559b", index_selected_rows_fg="white",
                top_left_bg="#333333", top_left_fg="gray",
                outline_color="gray", resizing_line_fg="white",
                vertical_scroll_background="#2a2d2e", horizontal_scroll_background="#2a2d2e",
            )
        else:
            options = dict(
                table_bg="white", table_fg="black", table_grid_fg="gray",
                table_selected_cells_bg="#add8e6", table_selected_cells_fg="black",
                header_bg="#cccccc", header_fg="#333333",
                header_selected_cells_bg="#a3bffa", header_selected_cells_fg="#333333",
                header_selected_columns_bg="#a3bffa", header_selected_columns_fg="#333333",
                index_bg="#cccccc", index_fg="#333333",
                index_selected_rows_bg="#add8e6", index_selected_rows_fg="black",
                top_left_bg="#cccccc", top_left_fg="gray",
                outline_color="gray", resizing_line_fg="black",
                vertical_scroll_background="white", horizontal_scroll_background="white",
            )
        # tksheet ships its own default font independent of CTk's theme, so set it explicitly here - the smaller TABLE_FONT_SIZE/TABLE_HEADER_FONT_SIZE, not the app's body/header sizes.
        options["font"] = (FONT_FAMILY, TABLE_FONT_SIZE, "normal")
        options["header_font"] = (FONT_FAMILY, TABLE_HEADER_FONT_SIZE, "bold")
        options["index_font"] = (FONT_FAMILY, TABLE_FONT_SIZE, "normal")
        for attr in ("sheet", "ach_sheet", "kill_sheet"):
            sheet = getattr(self, attr, None)
            if sheet is None:
                continue
            try:
                sheet.set_options(redraw=False, **options)
                sheet.config(bg=options["table_bg"])
                sheet.redraw(True)
            except Exception as e:
                self._warn(e)

    def _pause_global_scroll(self, event=None):
        try:
            self.scrollable_frame.unbind_all("<MouseWheel>")
            self.scrollable_frame.unbind_all("<Button-4>")
            self.scrollable_frame.unbind_all("<Button-5>")
        except Exception as e:
            self._warn(e)

    def _resume_global_scroll(self, event=None):
        try:
            for seq, tcl_binding in getattr(self, '_global_scroll_bindings', {}).items():
                if tcl_binding:
                    # Restore the literal Tcl command string customtkinter originally registered, not a re-derived Python callback.
                    self.scrollable_frame.bind_all(seq, tcl_binding)
        except Exception as e:
            self._warn(e)

    def _exempt_from_global_scroll(self, widget):
        """Wire a nested scrollable widget's outer container up to _pause_global_scroll / _resume_global_scroll, binding on the container frame (not the table's own sub-widgets) so it fires once on the way in/out rather than flickering."""
        try:
            widget.bind("<Enter>", self._pause_global_scroll)
            widget.bind("<Leave>", self._resume_global_scroll)
        except Exception as e:
            self._warn(e)

    def _suppress_sheet_wheel_propagation(self, sheet):
        """Second, more direct layer of the same nested-scroll fix as _exempt_from_global_scroll: binds directly to tksheet's own MT/RI canvases with add="+" and returns "break" to stop the outer page's global scroll handler from firing, independent of Enter/Leave timing."""
        def _stop(event):
            return "break"
        for canvas in (getattr(sheet, 'MT', None), getattr(sheet, 'RI', None)):
            if canvas is None:
                continue
            try:
                canvas.bind("<MouseWheel>", _stop, add="+")
                canvas.bind("<Button-4>", _stop, add="+")
                canvas.bind("<Button-5>", _stop, add="+")
            except Exception as e:
                self._warn(e)

    def _lock_sheet_vertical_scroll(self, sheet):
        """Fully disable vertical and horizontal mouse-wheel scrolling on a tksheet.Sheet (for tables that should never scroll, e.g. the mission table), by replacing tksheet's own instance-level bindings outright rather than layering on top of them, and not returning "break" so the event still falls through to scroll the outer page instead of going nowhere."""
        def _stop(event):
            return None
        vertical_canvases = (getattr(sheet, 'MT', None), getattr(sheet, 'RI', None))
        for canvas in vertical_canvases:
            if canvas is None:
                continue
            try:
                canvas.bind("<MouseWheel>", _stop)
                canvas.bind("<Button-4>", _stop)
                canvas.bind("<Button-5>", _stop)
            except Exception as e:
                self._warn(e)
        horizontal_canvases = (getattr(sheet, 'MT', None), getattr(sheet, 'RI', None), getattr(sheet, 'CH', None))
        for canvas in horizontal_canvases:
            if canvas is None:
                continue
            try:
                canvas.bind("<Shift-MouseWheel>", _stop)
                canvas.bind("<Shift-Button-4>", _stop)
                canvas.bind("<Shift-Button-5>", _stop)
            except Exception as e:
                self._warn(e)

    def _suppress_textbox_wheel_propagation(self, textbox):
        """Same nested-scroll problem as _suppress_sheet_wheel_propagation, but for CTkTextbox: manually replicates Tk's default MouseWheel scroll as an instance-level binding (since class-level bindings can't be preempted directly) then returns "break". Must be re-called every time update_translation_tab() rebuilds the textbox."""
        text_widget = getattr(textbox, '_textbox', textbox)

        def _scroll(event):
            delta = getattr(event, 'delta', 0)
            if delta:
                text_widget.yview_scroll(int(-1 * (delta / 120)), "units")
            elif getattr(event, 'num', None) == 4:
                text_widget.yview_scroll(-1, "units")
            elif getattr(event, 'num', None) == 5:
                text_widget.yview_scroll(1, "units")
            return "break"
        try:
            text_widget.bind("<MouseWheel>", _scroll)
            text_widget.bind("<Button-4>", _scroll)
            text_widget.bind("<Button-5>", _scroll)
        except Exception as e:
            self._warn(e)

    def on_save_share_platform_change(self, _display_value=None):
        """Handler for the PC/PS4 segmented switch - just reconfigures self.save_share_action_btn
        for whichever platform is now selected, no stored-save-data implications (this is a UI
        preference, not save data, same category as toggle_theme/on_controller_type_display_change)."""
        self._refresh_save_share_button()

    def _refresh_save_share_button(self):
        """(Re)configure self.save_share_action_btn's text/state for the currently selected platform. PC is unconditionally enabled since the generation-ID repair needs no external sample, unlike PS4."""
        platform = self.save_share_platform_var.get() if hasattr(self, 'save_share_platform_var') else "PC"
        if platform == "PC":
            self.save_share_action_btn.configure(
                text=self.tr('save_share_pc_button', "PC Save Sharing"),
                state="normal",
            )
        else:
            self._refresh_ps_samples_status()

    def on_save_share_action_clicked(self):
        """Dispatch to the PC repair flow or the existing PS4 sample-check flow depending on
        self.save_share_platform_var."""
        platform = self.save_share_platform_var.get() if hasattr(self, 'save_share_platform_var') else "PC"
        if platform == "PC":
            self._do_pc_save_share_repair()
        else:
            self.on_ps_samples_clicked()

    def _collect_save_slot_files(self, folder):
        """MAIN.GST/TROPHY.DAT/COMMON.CFG (whichever exist) plus every *.MST in folder - one save slot's worth of files. Shared by the manual PC Save Sharing repair and the automatic mismatch check on Load Save."""
        file_paths = [os.path.join(folder, name) for name in ("MAIN.GST", "TROPHY.DAT", "COMMON.CFG")
                      if os.path.exists(os.path.join(folder, name))]
        try:
            for entry in os.listdir(folder):
                full = os.path.join(folder, entry)
                if entry.upper().endswith(".MST") and os.path.isfile(full):
                    file_paths.append(full)
        except Exception as e:
            self._warn(e)
        return file_paths

    def _run_generation_id_fix(self, file_paths, game, reference_id=None, reference_session_stamp=None):
        """Run SaveGenerationID_ForgeryShenanigan over file_paths and report the result. Shared by the manual PC Save Sharing button and the automatic mismatch check on Load Save. reference_id/reference_session_stamp, when given (the foreign-owner case), force every file to the local account's real owner field instead of just matching whichever file sorts first - which field actually carries the owner id differs by game, see find_foreign_owner_mismatch()'s docstring."""
        # SaveGenerationID_ForgeryShenanigan lives in EDFSaveEditorSave_Handler.py and writes via
        # save_save()/save_save_edf41() directly, not through Logic.py's _save_game_file - so unlike
        # every other write path in the app it never gets an automatic backup. This repair runs on
        # saves already flagged as mismatched/corrupted (including automatically, right after Load
        # Save), which is exactly the situation where getting the fix wrong is most likely and most
        # costly - so back up every file about to be touched here, before the fix runs.
        for fp in file_paths:
            _backup_before_overwrite(fp)
        try:
            result = SaveGenerationID_ForgeryShenanigan(file_paths, game=game, reference_id=reference_id, reference_session_stamp=reference_session_stamp)
        except Exception as e:
            self._warn(e)
            messagebox.showerror(self.tr('save_share_error_title', "Save Sharing Failed"), str(e))
            return
        patched = [os.path.basename(p) for p in result.get("patched_files", [])]
        matching = [os.path.basename(p) for p in result.get("already_matching", [])]
        lines = [f"Reference generation ID: {result.get('reference_id')}", ""]
        if patched:
            lines.append("Patched:")
            lines.extend(f"  {n}" for n in patched)
        if matching:
            lines.append("Already matching (untouched):")
            lines.extend(f"  {n}" for n in matching)
        messagebox.showinfo(self.tr('save_share_done_title', "PC Save Sharing"), "\n".join(lines))

    def check_and_offer_generation_id_fix(self, folder, game):
        """Called from load_save_data() right after a save folder is picked, BEFORE the GST data is
        actually parsed into the UI. Two distinct failure modes, both shown by the game as a
        generic "Slot Corrupted": (1) files in the folder disagree with EACH OTHER (mixed from
        different sources into one existing slot) - find_generation_id_mismatch(); (2) every file
        agrees with every other file but not with the account actually running the game (a whole
        slot copied in from someone else, e.g. a friend's save) - find_foreign_owner_mismatch(),
        EDF4.1-confirmed via Ghidra RE, see get_save_generation_id()'s docstring for what this field
        really is. Checked in that order since (1) is cheap and (2) needs a derivable local Steam
        ID."""
        file_paths = self._collect_save_slot_files(folder)
        if len(file_paths) < 2:
            return
        try:
            mismatch = find_generation_id_mismatch(file_paths, game=game)
        except Exception as e:
            self._warn(e)
            return
        if mismatch:
            mismatched_names = "\n".join(os.path.basename(p) for p in mismatch["mismatched_files"])
            proceed = messagebox.askyesno(
                self.tr('gen_id_mismatch_title', "Save Files Don't Match"),
                self.tr('gen_id_mismatch_body',
                        "These save files don't share the same owner ID, usually from combining "
                        "files from different sources into one slot. The game may call this "
                        "slot corrupted.\n\nMismatched:\n") + mismatched_names +
                "\n\n" + self.tr('gen_id_mismatch_confirm', "Fix now so this slot loads cleanly?"),
            )
            if proceed:
                self._run_generation_id_fix(file_paths, game)
            return

        local_steamid64 = derive_local_steamid64(folder)
        if local_steamid64 is None:
            return
        try:
            owner_mismatch = find_foreign_owner_mismatch(file_paths, game, local_steamid64)
        except Exception as e:
            self._warn(e)
            return
        if not owner_mismatch:
            return
        proceed = messagebox.askyesno(
            self.tr('foreign_owner_title', "Save Belongs to a Different Account"),
            self.tr('foreign_owner_body',
                    "Every file in this slot agrees with the others, but none of them belong to "
                    "this Steam account - likely a whole save copied in from someone else (e.g. a "
                    "friend's save). The game will call this slot corrupted on load.\n\n") +
            self.tr('foreign_owner_confirm', "Rewrite the owner ID to this account so it loads?"),
        )
        if proceed:
            expected_bytes = bytes.fromhex(owner_mismatch["expected_owner_id"])
            if str(game).upper().startswith("EDF5"):
                self._run_generation_id_fix(file_paths, game, reference_session_stamp=expected_bytes)
            else:
                self._run_generation_id_fix(file_paths, game, reference_id=expected_bytes)

    def _do_pc_save_share_repair(self):
        """PC Save Sharing: for when the user has manually copied a friend's save files into their own save folder and the game now reports the slot corrupted. PC saves use one fixed AES key, so mixing files only trips the 4-byte save-generation-ID check; SaveGenerationID_ForgeryShenanigan normalizes every file in the folder to match. Meant to be run AFTER copying files in - see check_and_offer_generation_id_fix() for the automatic version that runs on Load Save."""
        if not getattr(self, 'current_file', None):
            messagebox.showwarning(
                self.tr('save_share_no_save_title', "No Save Loaded"),
                self.tr('save_share_no_save_body', "Load a save first - PC Save Sharing repairs the files sitting in that save's own folder."),
            )
            return
        folder = os.path.dirname(self.current_file)
        game = getattr(self, 'current_game', 'EDF6')
        file_paths = self._collect_save_slot_files(folder)
        if len(file_paths) < 2:
            messagebox.showwarning(
                self.tr('save_share_too_few_title', "Nothing to Fix"),
                self.tr('save_share_too_few_body', "Found fewer than 2 save files in this folder - there's nothing to normalize against."),
            )
            return
        file_list_text = "\n".join(os.path.basename(p) for p in file_paths)
        proceed = messagebox.askyesno(
            self.tr('save_share_confirm_title', "PC Save Sharing"),
            self.tr('save_share_confirm_body',
                    "This normalizes the 4-byte save-generation-ID across every file below so "
                    "they all match each other again - use this AFTER manually copying a "
                    "friend's save files into this folder, if the game now calls the slot "
                    "corrupted.\n\nFiles found:\n") + file_list_text +
            "\n\n" + self.tr('save_share_confirm_continue', "Continue?"),
        )
        if not proceed:
            return
        self._run_generation_id_fix(file_paths, game)

    def _refresh_ps_samples_status(self):
        """Re-run ps_saves.find_ps_samples() and update self.save_share_action_btn to reflect what it finds; only enabled once a real sce_sys/keystone + param.sfo pair exists in DUMP/ps_samples/."""
        try:
            self.ps_samples_info = ps_saves.find_ps_samples()
        except Exception as e:
            self._warn(e)
            self.ps_samples_info = []

        if self.ps_samples_info:
            self.save_share_action_btn.configure(
                text=f"PS4 Save Sharing: {len(self.ps_samples_info)} sample(s) ready",
                state="normal",
            )
        else:
            self.save_share_action_btn.configure(
                text="PS4 Save Sharing: no sample yet",
                state="disabled",
            )

    def on_ps_samples_clicked(self):
        """Only reachable once a real sample is found; re-checks and reports what's there. The full packaging via assemble_share_package() isn't wired up yet."""
        self._refresh_ps_samples_status()
        if not self.ps_samples_info:
            return
        lines = [f"{s['label']}  (sce_sys found)" for s in self.ps_samples_info]
        messagebox.showinfo(
            "PS4 Save Sharing",
            "Found sample(s) in DUMP/ps_samples/:\n\n" + "\n".join(lines) +
            "\n\nNext step: pair one of these with your own decrypted EDF4.1 save files and "
            "call EDFSaveEditorPS_SaveHandler.py's assemble_share_package()."
        )

    def toggle_theme(self):
        if self.theme_switch.get():
            ctk.set_appearance_mode("dark")
            self.current_theme = 'dark'
            self.theme_switch.configure(text=self.tr('theme_switch'))
        else:
            ctk.set_appearance_mode("light")
            self.current_theme = 'light'
            self.theme_switch.configure(text=self.tr('theme_switch_light'))
        self.update_tree_style()
        # Save updated theme preference
        try:
            self.save_config()
        except Exception as e:
            self._warn(e)

    # --- Generic collapsible-section framework ---
    def create_collapsible_section(self, parent, title_key, height=None):
        outer_frame = ctk.CTkFrame(parent)
        # Reduce vertical padding so sections don't take up extra space
        outer_frame.pack(pady=(6,2), fill="x")
        trans = self._trans_dict()
        btn = ctk.CTkButton(
            outer_frame,
            text=trans.get(title_key, title_key) + " ▶",
            font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"),
            command=lambda: self.toggle_collapsible(outer_frame, btn, title_key)
        )
        # Slightly reduce the button padding so it occupies less vertical space
        btn.pack(fill="x", padx=2, pady=(1,1))
        # Tag button with translation key so generic refresh can find it
        btn.translation_key = title_key
        self.__setattr__(f"{title_key.lower()}_button", btn)
        content_frame = ctk.CTkFrame(outer_frame)
        if height is not None:
            content_frame.configure(height=height)
            content_frame.pack_propagate(False)
        self.__setattr__(f"{title_key.lower()}_content", content_frame)
        self._collapsible_registry.append((content_frame, btn, title_key))
        return content_frame

    def _close_other_sections(self, keep_content_frame):
        # Accordion enforcement: collapse every registered section except the one about to be opened, so at most one section's widgets stay mapped at a time.
        trans = self._trans_dict()
        for content_frame, button, title_key in self._collapsible_registry:
            if content_frame is keep_content_frame:
                continue
            if content_frame.winfo_ismapped():
                content_frame.pack_forget()
                button.configure(text=trans.get(title_key, title_key) + " ▶")

    def toggle_collapsible(self, outer_frame, button, title_key):
        # Always use the current translation for the label
        trans = self._trans_dict()
        label = trans.get(title_key, title_key)
        content_frame = outer_frame.winfo_children()[1]  # Assuming button is first, content second
        if (content_frame.winfo_ismapped()):
            content_frame.pack_forget()
            button.configure(text=label + " ▶")
        else:
            self._close_other_sections(content_frame)
            # No expand=True: would let auto-sizing sections grab all leftover vertical space instead of just fitting their content.
            content_frame.pack(fill="both", pady=(2,2), padx=5)
            button.configure(text=label + " ▼")
            if (title_key == "mission_table_section"):  # Target only the mission section
                self.sheet.refresh(redraw_header=True, redraw_row_index=True)
                self.update_mission_table()
                self.update_completion()
                self.sheet.redraw(True)

    # --- Dual-purpose collapsible header bar: one header row split into two independently-toggleable halves, each showing/hiding its own content frame below. ---
    def create_dual_collapsible_section(self, parent, left_key, right_key, left_height=None, right_height=None):
        outer_frame = ctk.CTkFrame(parent)
        outer_frame.pack(pady=(6,2), fill="x")
        trans = self._trans_dict()

        header_row = ctk.CTkFrame(outer_frame, fg_color="transparent")
        header_row.pack(fill="x")
        header_row.grid_columnconfigure(0, weight=1, uniform="dualhdr")
        header_row.grid_columnconfigure(1, weight=1, uniform="dualhdr")

        left_content = ctk.CTkFrame(outer_frame)
        right_content = ctk.CTkFrame(outer_frame)
        if left_height is not None:
            left_content.configure(height=left_height)
            left_content.pack_propagate(False)
        if right_height is not None:
            right_content.configure(height=right_height)
            right_content.pack_propagate(False)
        # Fixed top-to-bottom stacking order regardless of which half gets toggled open first.
        reorder_group = [left_content, right_content]

        left_btn = ctk.CTkButton(
            header_row,
            text=trans.get(left_key, left_key) + " ▶",
            font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"),
            command=lambda: self.toggle_collapsible_frame(left_content, left_btn, left_key, reorder_group)
        )
        left_btn.grid(row=0, column=0, sticky="ew", padx=(2,1), pady=(1,1))
        left_btn.translation_key = left_key

        right_btn = ctk.CTkButton(
            header_row,
            text=trans.get(right_key, right_key) + " ▶",
            font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"),
            command=lambda: self.toggle_collapsible_frame(right_content, right_btn, right_key, reorder_group)
        )
        right_btn.grid(row=0, column=1, sticky="ew", padx=(1,2), pady=(1,1))
        right_btn.translation_key = right_key

        # Tag with the same "<key>_button" / "<key>_content" attribute convention as the single-section helper, so update_ui_text's generic refresh loop picks these up.
        self.__setattr__(f"{left_key.lower()}_button", left_btn)
        self.__setattr__(f"{left_key.lower()}_content", left_content)
        self.__setattr__(f"{right_key.lower()}_button", right_btn)
        self.__setattr__(f"{right_key.lower()}_content", right_content)
        self._collapsible_registry.append((left_content, left_btn, left_key))
        self._collapsible_registry.append((right_content, right_btn, right_key))
        return left_content, right_content

    def toggle_collapsible_frame(self, content_frame, button, title_key, reorder_group=None):
        # Like toggle_collapsible, but takes the content frame directly instead of locating it positionally, since that breaks once two content frames share one outer_frame (the dual-header-bar case).
        trans = self._trans_dict()
        label = trans.get(title_key, title_key)
        if content_frame.winfo_ismapped():
            content_frame.pack_forget()
            button.configure(text=label + " ▶")
        else:
            self._close_other_sections(content_frame)
            content_frame.pack(fill="both", pady=(2,2), padx=5)
            button.configure(text=label + " ▼")
            if (title_key == "mission_table_section"):
                # Perf: call only update_mission_table() (which already ends with the one redraw that matters), not extra sheet.refresh()/redraw() calls before/after it.
                self.update_mission_table()
                self.update_completion()
            elif (title_key == "color_section"):
                # Lazy-build the swatch grid on first expand instead of during __init__ - see
                # _build_color_grid()'s docstring. No-ops on every expand after the first.
                self._build_color_grid()
        # Re-pack every currently-open sibling frame in the fixed group order so stacking stays deterministic no matter which half was clicked first.
        if reorder_group:
            for frame in reorder_group:
                if frame.winfo_ismapped():
                    frame.pack_forget()
                    frame.pack(fill="both", pady=(2,2), padx=5)

    # --- Game selection / save-path detection ---
    def on_game_change(self, new_game):
        print(f"[DEBUG] on_game_change: {new_game}")
        if new_game == getattr(self, 'previous_game', None):
            return
        meta = self.games_metadata.get(new_game, {})
        if meta.get('coming_soon', False):
            messagebox.showinfo("Coming Soon", f"{new_game} support is coming soon.")
            self.game_var.set(self.previous_game)
            return
        self.previous_game = new_game
        self._apply_game_switch(new_game)
        # After updating current_game etc., recompute default save dir
        try: self.update_default_save_dir()
        except Exception as e:
            self._warn(e)

    def _refresh_armor_modded_rate_defaults(self, old_game, new_game):
        """Modded Growth Rate's vanilla pre-fill differs drastically per game (EDF6 ~0.56, EDF5
        ~0.64-0.8, EDF4.1 ~2.1-5.3) - unlike Modded Start's, which happens to be the same
        200/150/200/250 across all 3 games in this codebase's model and so never needs this. Called
        on every game switch: only replaces an entry that still shows the OLD game's vanilla
        default - a value the user actually typed (e.g. EDF 6.9's real rate) is left alone so
        hopping between games/DLC to compare mission tables doesn't silently wipe it."""
        entries = getattr(self, 'armor_modded_rate_entries', None)
        if not entries:
            return
        for i, class_name in enumerate(PLAYER_CLASS_MAP.values()):
            if i >= len(entries):
                break
            label = f"{class_name} Armor"
            old_default = round(get_vanilla_armor_rate(old_game, label), 4)
            new_default = round(get_vanilla_armor_rate(new_game, label), 4)
            try:
                current_val = round(float(entries[i].get()), 4)
            except (ValueError, TypeError):
                current_val = None
            if current_val is None or current_val == old_default:
                entries[i].delete(0, "end")
                entries[i].insert(0, str(new_default))

    def _apply_game_switch(self, new_game):
        """The actual "switch active game" side effects (mission counts/table, labels, translation tab), shared by on_game_change (gated on coming_soon) and sync_game_selector_to_folder (not gated, since a folder of real save data proves the game is supported)."""
        meta = self.games_metadata.get(new_game, {})
        old_game = getattr(self, 'current_game', None)
        slot = getattr(self, 'mission_player_slot', 1)
        cache = getattr(self, 'mission_table_cache', None)
        try:
            self._refresh_armor_modded_rate_defaults(old_game, new_game)
        except Exception as e:
            self._warn(e)
        # Flush any in-UI mission-table edits for the game/DLC being left into its own cache slot before swapping away, so hopping between games before a final Save doesn't drop them.
        if cache and old_game and old_game in cache and hasattr(self, 'mission_arrays'):
            cache[old_game].setdefault('slots', {})[slot] = [bytearray(a) for a in self.mission_arrays]

        self.current_game = new_game
        self.missionlist_key = meta.get('missionlist') or new_game.replace(" ", "").replace("Offline", "").replace("Online", "")
        self.total_missions = meta.get('total_missions', self.total_missions)
        self.total_pages = self._recompute_total_pages()
        self.current_page = 1

        # Hot-swap this game/DLC's mission table from the in-memory cache built at Load Save time, instead of leaving the previous game's bytes on screen relabeled.
        if cache and new_game in cache:
            entry = cache[new_game]
            self.current_mst_file = entry.get('mst_file')
            slot_arrays = entry.get('slots', {}).get(slot)
            if slot_arrays is None:
                try:
                    mst_data = _load_game_file(self, entry['mst_file'])
                    slot_arrays = _extract_mission_arrays(mst_data, slot, game=new_game)
                    if slot_arrays is not None:
                        entry.setdefault('slots', {})[slot] = slot_arrays
                except Exception as e:
                    self._warn(e)
                    slot_arrays = None
            self.mission_arrays = [bytearray(a) for a in slot_arrays] if slot_arrays is not None else [bytearray(0x200) for _ in range(4)]
        elif cache is not None:
            # A save has been loaded, but this game/DLC's .MST wasn't found in that folder - show an empty table rather than a stale one carried over.
            self.current_mst_file = None
            self.mission_arrays = [bytearray(0x200) for _ in range(4)]
        # else: no save loaded yet at all - leave the placeholder arrays from __init__ as-is.

        for i in range(4):
            if len(self.mission_arrays[i]) < self.total_missions:
                self.mission_arrays[i].extend(bytearray(self.total_missions - len(self.mission_arrays[i])))
        # Reload mission names for the new game before refreshing table
        self.reload_mission_names()
        if hasattr(self, 'page_label'):
            self.page_label.configure(text=self.tr('page_label').format(current=self.current_page, total=self.total_pages))
        self.update_completion()
        try:
            self.rebuild_weapon_table_columns_for_game()
        except Exception as e:
            self._warn(e)
        self.update_weapon_table_names()
        self.update_loadout_names()
        self.update_ui_text()
        # If translation tab is showing weapon or mission names, refresh it to reflect new game/mission key
        if hasattr(self, 'translation_tab_var') and self.translation_tab_var.get() in ("Weapon Names", "Mission Names"):
            self.update_translation_tab()
        # Keep the Mission Table panel's own MST dropdown in sync whenever the game/DLC switches via the top selector.
        try:
            self.update_mst_dropdown()
        except Exception as e:
            self._warn(e)
        # Swap in this game/DLC's own Boring Missions list instead of leaving the previous game's text field contents showing.
        try:
            self.refresh_boring_missions_field()
        except Exception as e:
            self._warn(e)
        # Resize/relabel the Kill Statistics sheet for this game so switching via the dropdown alone already shows the right stat names before any save is loaded.
        try:
            self.rebuild_kill_sheet_for_game()
        except Exception as e:
            self._warn(e)
        # Rebuild the Loadouts panel's rows for this game's own per-class slot count, same "needed here, not just after Load Save" reasoning as the kill sheet rebuild above.
        try:
            self.rebuild_loadout_panel_for_game()
            self.update_loadout_names()
        except Exception as e:
            self._warn(e)
        # Relabel the Color Customization Tier dropdown for this game's real tier count, same reasoning as the kill sheet rebuild above.
        try:
            self.refresh_color_selector_controls()
        except Exception as e:
            self._warn(e)
        # Sync the Key Config panel's Category dropdown to this game (values list + displayed text), THEN rebuild its rows - rebuild_keyconfig_rows() alone only redraws rows for whichever category was already selected.
        try:
            if hasattr(self, 'keyconfig_category_menu'):
                categories = self._keyconfig_categories_for_mode()
                self.keyconfig_category_menu.configure(values=[self._keyconfig_category_label(c) for c in categories])
                if self.keyconfig_category_var.get() not in categories:
                    self.keyconfig_category_var.set(categories[0])
                self.keyconfig_category_display_var.set(self._keyconfig_category_label(self.keyconfig_category_var.get()))
            self.rebuild_keyconfig_rows()
        except Exception as e:
            self._warn(e)
        # Keep the Weapon Farming Helper's own "Mode:" dropdown in sync with the top game selector; current_game uses the same display-string namespace as FARMING_MODE_INFO's keys, so this is a direct set. Skipped if current_game has no Farming Mode equivalent.
        try:
            if hasattr(self, 'farming_mode_var'):
                farming_values = (list(self.farming_mode_dropdown.cget('values'))
                                   if hasattr(self, 'farming_mode_dropdown') else self.FARMING_MODES)
                if new_game in farming_values and self.farming_mode_var.get() != new_game:
                    self.farming_mode_var.set(new_game)
                    self.on_farming_mode_change()
        except Exception as e:
            self._warn(e)

    def on_mst_dropdown_change(self, value):
        """Handler for the Mission Table panel's MST dropdown. Delegates to on_game_change so both selectors and every other game-dependent bit of UI stay in sync."""
        try:
            if hasattr(self, 'game_var'):
                self.game_var.set(value)
            self.on_game_change(value)
        except Exception as e:
            self._warn(e)

    # Prefixes _register_modded_mission_tables() uses for a runtime-discovered .MST not in games_metadata's known filenames; both need the "unknown total missions, let the user tell us" treatment.
    _SYNTHETIC_PACK_PREFIXES = ('Modded: ', 'EDF5 Official Pack (unidentified, ')

    def _is_synthetic_pack_key(self, key):
        key = str(key or '')
        return any(key.startswith(p) for p in self._SYNTHETIC_PACK_PREFIXES)

    # Per-series background/text color for the game_selector dropdown, requested by FevGrave
    # 2026-09-07 so a long, growing list (currently 17 entries across 4 series, more once modded
    # packs register) doesn't overwhelm new users - a color block per game family lets someone
    # find "the EDF5 ones" or "the EDF4.1 ones" at a glance instead of reading every row. Matched
    # by key PREFIX, most-specific first (EDF6.2 must be checked before EDF6, EDF4.1 before EDF4),
    # so this also automatically colors any future EDF6.2 DLC or EDF4.1 DLC entry correctly
    # without needing an update here. Colors are plain hex (tkinter Menu per-item background, not
    # a CTk color pair), chosen dark/saturated enough to read against either light or dark theme.
    _GAME_SERIES_COLORS = [
        ('EDF6.2', '#4B3B6B', '#E8DFFF'),  # violet - announced/unreleased
        ('EDF6',   '#1E4620', '#D7FFDA'),  # green - current main game
        ('EDF5',   '#1E3A5F', '#D6EBFF'),  # blue
        ('EDF4',   '#5A3B1E', '#FFE8CC'),  # amber - covers "EDF4.1 ..." keys
    ]

    def _colorize_game_selector_dropdown(self):
        """Recolor each entry in the game_selector's dropdown menu by which game series it
        belongs to (see _GAME_SERIES_COLORS). Must be called again after ANY
        `self.game_selector.configure(values=...)` - CTkOptionMenu/DropdownMenu rebuilds every
        menu entry from scratch on a values update, wiping any per-entry colors set here. No-op
        (not an error) for entries that don't match a known series prefix, e.g. a synthetic
        "Modded: ..." pack - those just keep the theme's default dropdown colors."""
        if not hasattr(self, 'game_selector'):
            return
        menu = getattr(self.game_selector, '_dropdown_menu', None)
        if menu is None:
            return
        keys = list(self.games_metadata.keys())
        for i, key in enumerate(keys):
            for prefix, bg, fg in self._GAME_SERIES_COLORS:
                if key.startswith(prefix):
                    try:
                        menu.entryconfigure(i, background=bg, foreground=fg, activebackground=bg, activeforeground=fg)
                    except Exception as e:
                        self._warn(e)
                    break

    def update_mst_dropdown(self):
        """Refresh the Mission Table panel's MST dropdown to only list games/DLCs whose .MST was actually found in the loaded save folder, rather than the full games_metadata list. Safe to call before any save is loaded. Also refreshes the top game_selector so runtime-registered modded packs become selectable there too."""
        if not hasattr(self, 'mst_dropdown'):
            return
        cache = getattr(self, 'mission_table_cache', {}) or {}
        found = [k for k, v in cache.items() if v.get('mst_file')]
        if not found:
            found = [self.current_game]
        try:
            self.mst_dropdown.configure(values=found)
        except Exception as e:
            self._warn(e)
        if hasattr(self, 'game_selector'):
            try:
                self.game_selector.configure(values=list(self.games_metadata.keys()))
                self._colorize_game_selector_dropdown()
            except Exception as e:
                self._warn(e)
        current = self.current_game if self.current_game in found else found[0]
        try:
            self.mst_dropdown_var.set(current)
        except Exception as e:
            self._warn(e)
        # Reflect + gate the "Missions:" field: editable only for modded packs, disabled/read-only for vanilla or known DLC entries since their counts are already hardcoded.
        if hasattr(self, 'mst_total_var'):
            try:
                self.mst_total_var.set(str(self.total_missions))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'mst_total_entry'):
            try:
                is_modded = self._is_synthetic_pack_key(current)
                self.mst_total_entry.configure(state="normal" if is_modded else "disabled")
            except Exception as e:
                self._warn(e)
        # Any modded pack just discovered above also needs to become selectable in the Weapon Farming Helper's Mode dropdown.
        try:
            self._refresh_farming_mode_dropdown()
        except Exception as e:
            self._warn(e)

    def on_mst_total_changed(self, event=None):
        """Handler for the "Missions:" entry: lets the user tell the editor how many of a modded pack's up-to-512 raw byte-slots are real missions, persisted to config.json's modded_mission_totals. No-op for vanilla/known DLC entries (field is disabled for those)."""
        game = getattr(self, 'current_game', None)
        if not game or not self._is_synthetic_pack_key(game):
            try:
                self.mst_total_var.set(str(self.total_missions))
            except Exception as e:
                self._warn(e)
            return
        try:
            new_count = int(self.mst_total_var.get())
        except (TypeError, ValueError):
            self.mst_total_var.set(str(self.total_missions))
            return
        new_count = max(1, min(512, new_count))
        self.mst_total_var.set(str(new_count))
        if new_count == self.total_missions:
            return  # unchanged - skip the table/config rewrite
        meta = self.games_metadata.get(game)
        if not meta:
            return
        meta['total_missions'] = new_count
        self.total_missions = new_count
        self.total_pages = self._recompute_total_pages()
        self.current_page = 1
        mst_filename = meta.get('missiontable')
        if mst_filename:
            self.config_data.setdefault('modded_mission_totals', {})[mst_filename] = new_count
            try:
                self.save_config()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'page_label'):
            try:
                self.page_label.configure(text=self.tr('page_label').format(current=self.current_page, total=self.total_pages))
            except Exception as e:
                self._warn(e)
        for i in range(4):
            if len(self.mission_arrays[i]) < self.total_missions:
                self.mission_arrays[i].extend(bytearray(self.total_missions - len(self.mission_arrays[i])))
        try:
            self.update_mission_table()
            self.update_completion()
        except Exception as e:
            self._warn(e)
        # If the Weapon Farming Helper is showing this same modded pack, resync its mission slider's range to the new count too.
        if hasattr(self, 'farming_mode_var') and self.farming_mode_var.get() == game:
            try:
                self.on_farming_mode_change()
            except Exception as e:
                self._warn(e)

    def detect_game_from_path(self, folder):
        """Best-effort detection of which EDF game a save folder belongs to, based on known vanilla/modded folder names appearing as a path component. Returns a game_key or None."""
        try:
            parts = {p.upper() for p in os.path.normpath(folder).split(os.sep)}
        except Exception:
            return None
        for game_key, names in EDF_SAVE_FOLDER_NAMES.items():
            for name in names:
                if name.upper() in parts:
                    return game_key
        return None

    def _prompt_online_offline(self, game_label):
        """EDF5/EDF4.1 keep Online and Offline progress as genuinely separate data, and the save folder name can't tell them apart. Always defaults to 'Offline'; switching to Online afterward via the top selector is an instant, lossless hot-swap, so no modal prompt is needed here."""
        return 'Offline'

    def sync_game_selector_to_folder(self, folder):
        """Called right after the user picks a folder in the Load Save dialog. If that folder belongs to a different EDF game than what's currently selected, switch the dropdown (and everything that depends on it) to match instead of misinterpreting the data."""
        detected_key = self.detect_game_from_path(folder)
        if not detected_key:
            return
        if detected_key == 'EDF6':
            # EDF6 DLC saves live in the same folder as the base game, so preserve an already-selected DLC choice rather than snapping back to plain 'EDF6'.
            current = getattr(self, 'current_game', None)
            target = current if current and current.startswith('EDF6') else 'EDF6'
        else:
            target = f"{detected_key} {self._prompt_online_offline(detected_key)}"
        if not target or target == getattr(self, 'current_game', None) or target not in self.games_metadata:
            return
        self.game_var.set(target)
        self.previous_game = target
        self._apply_game_switch(target)

    def get_edf_save_dir_candidates(self, game_key):
        """Return every plausible save-directory path for game_key, in priority order. Does not filter by existence - callers decide whether to require os.path.isdir()."""
        local = os.getenv('LOCALAPPDATA', '')
        user_home = os.path.expanduser('~')
        onedrive = os.getenv('OneDrive')
        docs_roots = []
        if onedrive:
            docs_roots.append(os.path.join(onedrive, 'Documents'))
        docs_roots.append(os.path.join(user_home, 'Documents'))

        names = EDF_SAVE_FOLDER_NAMES.get(game_key, [])
        candidates = []
        if game_key == 'EDF6':
            candidates += [os.path.join(local, n, 'SAVE_DATA') for n in names]
            for docs_root in docs_roots:
                candidates += [os.path.join(docs_root, 'My Games', n, 'SAVE_DATA') for n in names]
        else:
            for docs_root in docs_roots:
                candidates += [os.path.join(docs_root, 'My Games', n, 'SAVE_DATA') for n in names]
            candidates += [os.path.join(local, n, 'SAVE_DATA') for n in names]  # e.g. EDF5_MODSAVES, which - unlike EDF6 - sits directly under LOCALAPPDATA rather than Documents/My Games
        return candidates

    def get_edf_save_dirs(self):
        """Return {game_key: [existing_path, ...]} for paths that actually exist on this machine; a game with no install found is simply absent from the dict."""
        dirs = {}
        for game_key in EDF_SAVE_FOLDER_NAMES:
            found = [p for p in self.get_edf_save_dir_candidates(game_key) if os.path.isdir(p)]
            if found:
                dirs[game_key] = found
        return dirs

    def init_save_paths_section(self):  # type: ignore[override]
        trans = self._trans_dict()
        info_label = ctk.CTkLabel(self.save_paths_section_content, text=self.tr('save_paths_info'), font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"))
        info_label.pack(anchor="w", padx=8, pady=(6, 2))
        # Active dir placeholder will be added after computing default
        self.save_paths_entries = {}

        steam_id = self.detect_steam_id()
        dirs = self.get_edf_save_dirs()
        for game, paths in dirs.items():
            for path in paths:
                folder_name = os.path.basename(os.path.dirname(path)) if path.upper().endswith('SAVE_DATA') else os.path.basename(path)
                display_path = path
                if steam_id and os.path.isdir(os.path.join(path, steam_id)):
                    display_path = os.path.join(path, steam_id)
                row = ctk.CTkFrame(self.save_paths_section_content)
                row.pack(fill="x", padx=8, pady=2)
                # width must fit the longest label text, otherwise CTkLabel grows past it and every row's entry/copy column shifts out of alignment.
                lbl = ctk.CTkLabel(row, text=f"{game} ({folder_name}):", width=SAVE_PATHS_LABEL_WIDTH, anchor="w")
                lbl.pack(side="left")
                entry = ctk.CTkEntry(row)
                entry.pack(side="left", fill="x", expand=True, padx=5)
                entry.insert(0, display_path)
                entry.configure(state="readonly")
                self.save_paths_entries[f"{game}:{folder_name}"] = entry
                btn = ctk.CTkButton(row, text=self.tr('copy_button'), width=60, command=lambda p=display_path: self.copy_to_clipboard(p))
                btn.pack(side="left", padx=2)


        try: self.update_default_save_dir()
        except Exception as e:
            self._warn(e)

        # Thin divider setting the WeaponLimit setup block apart from the auto-detected save
        # paths above it.
        weapon_limit_divider = ctk.CTkFrame(self.save_paths_section_content, height=2, fg_color=("gray70", "gray30"))
        weapon_limit_divider.pack(fill="x", padx=8, pady=(10, 0))

        # WeaponLimit mod sidecar (.bin) support: this is a one-time, stable setting (the mod's
        # own Mods folder doesn't move around once you've told the editor where it is), so it
        # lives here with the other one-time setup rather than cluttering the Weapon Table panel
        # you're in every time you edit weapons. Lets the editor find
        # <Mods folder>\SaveData\edf6_weapons_slotNN.bin (see EDFSaveEditorLogic.py's
        # get_weapon_limit_bin_path() for the full story) so slots 2048+ - and, once the mod is
        # active, ALL weapon ownership data - can be read/edited/written back.
        weapon_limit_header_label = ctk.CTkLabel(self.save_paths_section_content, text=self.tr('weapon_limit_header', "WeaponLimit Mod"), font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"), anchor="w")
        weapon_limit_header_label.translation_key = 'weapon_limit_header'
        weapon_limit_header_label.pack(anchor="w", fill="x", padx=8, pady=(8, 2))
        weapon_limit_frame = ctk.CTkFrame(self.save_paths_section_content)
        weapon_limit_frame.pack(fill='x', padx=8, pady=(0, 4))
        self.weapon_limit_dir_label = ctk.CTkLabel(weapon_limit_frame, text=self.tr('weapon_limit_dir_label', "WeaponLimit mod's Mods folder:"))
        self.weapon_limit_dir_label.pack(side='left', padx=(6, 6))
        self.weapon_limit_dir_var = ctk.StringVar(value=self.config_data.get('weapon_limit_mods_dir', ''))
        self.weapon_limit_dir_entry = ctk.CTkEntry(weapon_limit_frame, textvariable=self.weapon_limit_dir_var, width=260,
                                                    placeholder_text=self.tr('weapon_limit_dir_placeholder', "<GameDir>\\Mods"))
        self.weapon_limit_dir_entry.pack(side='left', fill='x', expand=True, padx=(0, 6))
        self.weapon_limit_dir_entry.bind('<Return>', self.on_weapon_limit_folder_changed)
        self.weapon_limit_dir_entry.bind('<FocusOut>', self.on_weapon_limit_folder_changed)
        self.weapon_limit_browse_btn = ctk.CTkButton(weapon_limit_frame, text=self.tr('browse_button', "Browse..."), width=90,
                                                      command=self.on_browse_weapon_limit_folder)
        self.weapon_limit_browse_btn.pack(side='left', padx=(0, 6))
        self.weapon_limit_status_label = ctk.CTkLabel(self.save_paths_section_content, text='', font=(FONT_FAMILY, BASE_FONT_SIZE - 1),
                                                       anchor='w', justify='left', wraplength=1250)
        self.weapon_limit_status_label.pack(fill='x', padx=8, pady=(0, 6))
        try: self.refresh_weapon_limit_status()
        except Exception as e:
            self._warn(e)

        # Thin divider so the howto block reads as a distinct section from the path rows
        # above it, instead of blending into one undifferentiated list.
        divider = ctk.CTkFrame(self.save_paths_section_content, height=2, fg_color=("gray70", "gray30"))
        divider.pack(fill="x", padx=8, pady=(10, 0))

        self.save_paths_howto_header_label = ctk.CTkLabel(self.save_paths_section_content, text=self.tr('save_paths_howto_header'), font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"), anchor="w")
        self.save_paths_howto_header_label.translation_key = 'save_paths_howto_header'
        self.save_paths_howto_header_label.pack(anchor="w", fill="x", padx=8, pady=(8, 2))

        howto_lines = [
            'save_paths_howto_1', 'save_paths_howto_2', 'save_paths_howto_3',
            'save_paths_howto_4', 'save_paths_howto_5', 'save_paths_howto_6',
            'save_paths_howto_7',
        ]
        howto_defaults = {
            'save_paths_howto_1': '1. "Load Save" opens straight to your most likely save folder - it auto-detects vanilla vs. modded folder names, checks OneDrive-redirected installs, and jumps into whichever SAVESLOT0X profile you touched most recently.',
            'save_paths_howto_2': '2. Browse into a different EDF game\'s folder than what\'s selected above and the Game dropdown switches to match automatically (EDF5/EDF4.1 will ask Online or Offline first, since that can\'t be told from the folder name alone).',
            'save_paths_howto_3': '3. The rows above are reference paths for browsing manually or backing up your saves - "Copy" puts a path on your clipboard to paste into File Explorer\'s address bar.',
            'save_paths_howto_4': '4. After loading, edit values in the sections below (Armor, Loadouts, Color Customization, Weapon Table, Mission Table, Achievements) and click "Save" at the top to write changes back to the loaded file.',
            'save_paths_howto_5': '5. Always keep a backup of your save before experimenting - edits here are byte-level and unforgiving of mistakes.',
            'save_paths_howto_6': '6. Don\'t be shy about the Translation Editor right below this - add a new language, or fix up any text in this tool that looks wrong for UI Strings, Weapon Names, or Mission Names.',
            'save_paths_howto_7': '7. Wanted: PlayStation save samples. This tool currently only supports PC/Steam saves - if you can pull a PS4/PS5 EDF save file (e.g. via Save Wizard or a similar export tool), sharing a copy would let us add PlayStation support.',
        }
        self.save_paths_howto_labels = {}
        for key in howto_lines:
            # anchor="w" required here too: CTkLabel defaults to center, and fill="x" stretching the label to full width would otherwise center every wrapped line.
            line_lbl = ctk.CTkLabel(
                self.save_paths_section_content,
                text=trans.get(key, howto_defaults[key]),
                font=(FONT_FAMILY, BASE_FONT_SIZE), wraplength=1250, justify="left", anchor="w",
            )
            line_lbl.translation_key = key
            line_lbl.pack(anchor="w", padx=8, pady=(0, 4), fill="x")
            self.save_paths_howto_labels[key] = line_lbl

    def copy_to_clipboard(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()  # keep on some platforms
        except Exception as e:
            self._warn(e)

    def _find_best_save_slot(self, base_dir):
        """If base_dir contains SAVESLOT0X profile subfolders, return whichever has the most recently modified .GST file, so Load Save opens on the most recently played slot. Returns (best_dir, best_mtime); best_mtime is -1 when no real save data was found."""
        try:
            slot_dirs = sorted(
                d for d in os.listdir(base_dir)
                if d.upper().startswith('SAVESLOT') and os.path.isdir(os.path.join(base_dir, d))
            )
        except Exception:
            return base_dir, -1
        if not slot_dirs:
            return base_dir, -1
        best_dir, best_mtime = None, -1
        for d in slot_dirs:
            slot_path = os.path.join(base_dir, d)
            try:
                gst_files = [f for f in os.listdir(slot_path) if f.upper().endswith('.GST')]
            except Exception:
                continue
            for f in gst_files:
                try:
                    mtime = os.path.getmtime(os.path.join(slot_path, f))
                except Exception:
                    continue
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_dir = slot_path
        return (best_dir, best_mtime) if best_dir else (os.path.join(base_dir, slot_dirs[0]), -1)

    def update_default_save_dir(self):
        """Determine and store the default save directory for current game selection, using the same candidate list as the Save Paths panel via get_edf_save_dir_candidates() so the two stay in sync."""
        game = getattr(self, 'current_game', 'EDF6')
        if game.startswith('EDF6'):
            game_key = 'EDF6'
        elif game.startswith('EDF5'):
            game_key = 'EDF5'
        elif game.startswith('EDF4'):
            game_key = 'EDF4.1'
        else:
            game_key = None

        steam_id = self.detect_steam_id()
        save_dir_full = ''
        if game_key:
            candidates = self.get_edf_save_dir_candidates(game_key)
            # Check every candidate with this Steam ID's folder and keep whichever has the most recently modified save, rather than just the first candidate that exists (list order alone would wrongly prefer vanilla over modded or vice versa).
            best_mtime = -1
            for c in candidates:
                if not (steam_id and os.path.isdir(os.path.join(c, steam_id))):
                    continue
                slot_dir, mtime = self._find_best_save_slot(os.path.join(c, steam_id))
                if mtime > best_mtime:
                    best_mtime = mtime
                    save_dir_full = slot_dir
            if not save_dir_full:
                # No candidate had real save data yet - fall back to the first candidate that merely exists.
                base = next((c for c in candidates if os.path.isdir(c)), candidates[0] if candidates else '')
                if steam_id and os.path.isdir(os.path.join(base, steam_id)):
                    base = os.path.join(base, steam_id)
                save_dir_full = base
        if not save_dir_full:
            save_dir_full = os.getcwd()
        # Descend into the most likely SAVESLOT0X profile folder so "Load Save" opens right where the files are (no-op if already resolved above).
        self.default_save_dir, _ = self._find_best_save_slot(save_dir_full)
        # Reflect in debug tab if present
        try: self.update_save_paths_debug()
        except Exception as e:
            self._warn(e)

    def detect_steam_id(self):
        """Attempt to detect a Steam64ID folder, checking the same candidate paths as get_edf_save_dir_candidates() so this stays in sync with the Save Paths panel."""
        # Look for 17-digit directory names inside common bases
        candidates = []
        for game_key in EDF_SAVE_FOLDER_NAMES:
            candidates += self.get_edf_save_dir_candidates(game_key)
        for base in candidates:
            try:
                if not os.path.isdir(base):
                    continue
                for name in os.listdir(base):
                    if len(name) in (16,17) and name.isdigit():
                        return name
            except Exception:
                continue
        return ''

    def update_save_paths_debug(self):
        """Update / create the "Last Touched Save" row (internal attr/translation-key names
        kept as active_save_dir_* - only the user-facing label text changed)."""
        if not hasattr(self, 'save_paths_section_content'):
            return
        existing = getattr(self, 'active_save_dir_entry', None)
        label_text = self.tr('active_save_dir_label')
        if existing and existing.winfo_exists():
            existing.configure(state='normal')
            existing.delete(0, 'end')
            existing.insert(0, getattr(self, 'default_save_dir', ''))
            existing.configure(state='readonly')
            # Also update label text
            try:
                parent = existing.master
                for w in parent.winfo_children():
                    if isinstance(w, ctk.CTkLabel): w.configure(text=label_text)
            except Exception as e:
                self._warn(e)
        else:
            # Insert at top after info label (index 1)
            try:
                row = ctk.CTkFrame(self.save_paths_section_content)
                # Pack below info label (use before other game rows by repacking) – simplest just pack now
                row.pack(fill='x', padx=8, pady=(4,2))
                # Same fixed width as the game rows above so this row's entry/Copy column
                # lines up with theirs instead of starting further left.
                lbl = ctk.CTkLabel(row, text=label_text, width=SAVE_PATHS_LABEL_WIDTH, anchor='w')
                lbl.pack(side='left')
                entry = ctk.CTkEntry(row)
                entry.pack(side='left', fill='x', expand=True, padx=5)
                entry.insert(0, getattr(self, 'default_save_dir', ''))
                entry.configure(state='readonly')
                btn = ctk.CTkButton(row, text=self.tr('copy_button'), width=60, command=lambda: self.copy_to_clipboard(getattr(self, 'default_save_dir', '')))
                btn.pack(side='left', padx=2)
                self.active_save_dir_entry = entry
            except Exception as e:
                self._warn(e)

    # --- Save / Load actions ---
    def on_save_clicked(self):
        if self.current_file is None:
            self.save_status_label.configure(text="No save loaded", text_color="red")
            self.after(3000, lambda: self.save_status_label.configure(text=""))
            return
        # Safety net: confirm before overwriting the real save file the game reads. A timestamped
        # backup is also taken automatically inside _save_game_file regardless of this dialog, so
        # declining here just skips the write - it isn't the only protection.
        proceed = messagebox.askyesno(
            self.tr('save_confirm_title', "Overwrite Save File?"),
            self.tr('save_confirm_body',
                    "This writes your changes directly into the save file the game reads. "
                    "A timestamped backup of the current file(s) is kept automatically in an "
                    "EDFSaveEditor_Backups folder alongside them, in case anything looks wrong "
                    "afterward.\n\nContinue?"),
        )
        if not proceed:
            return
        prev_cwd = os.getcwd()
        try:
            if hasattr(self, 'default_save_dir') and os.path.isdir(self.default_save_dir):
                os.chdir(self.default_save_dir)
            save_save_data(self)
            self.save_status_label.configure(text="Saved successfully", text_color="green")
            self.after(3000, lambda: self.save_status_label.configure(text=""))
        except Exception as e:
            # Log the real error rather than just showing a vague red label, since a failed save needs to be debuggable.
            print(f"[ERROR] Save failed: {e}")
            self.save_status_label.configure(text="Save failed", text_color="red")
            self.after(3000, lambda: self.save_status_label.configure(text=""))
        finally:
            try: os.chdir(prev_cwd)
            except Exception as e:
                self._warn(e)
            self.after_save_load_refresh()

    def on_load_clicked(self):
        prev_cwd = os.getcwd()
        try:
            if hasattr(self, 'default_save_dir') and os.path.isdir(self.default_save_dir):
                os.chdir(self.default_save_dir)
            load_save_data(self)
        finally:
            try: os.chdir(prev_cwd)
            except Exception as e:
                self._warn(e)
            self.after_save_load_refresh()

    def after_save_load_refresh(self):
        """Reapply localized armor/stat labels after external save/load handlers modify values."""
        try:
            self.update_armor_display()  # preserves translated prefixes
        except Exception as e:
            self._warn(e)
        try:
            self.refresh_loadout_labels()
        except Exception as e:
            self._warn(e)
        try:
            self.update_weapon_table_names()
        except Exception as e:
            self._warn(e)
        # Reset the GST/BIN view switch back to GST (the default view) on every fresh load, so a
        # save loaded after browsing another save's BIN edits doesn't stay stuck on BIN; then
        # (re)compute the GST/BIN diff and refresh the table view/highlighting for this save.
        if hasattr(self, 'weapon_limit_source_var'):
            try: self.weapon_limit_source_var.set('GST')
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'refresh_weapon_table_view'):
            try: self.refresh_weapon_table_view()
            except Exception as e:
                self._warn(e)
        # Re-run mission/achievement refresh if arrays changed; also reset the active class back to Ranger on every load, so a save loaded after browsing another class doesn't stay on it (set_active_mission_class already re-runs update_mission_table internally).
        if hasattr(self, 'set_active_mission_class'):
            try: self.set_active_mission_class(0)
            except Exception as e:
                self._warn(e)
        elif hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'update_completion'):
            try: self.update_completion()
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'update_achievement_table'):
            try: self.update_achievement_table()
            except Exception as e:
                self._warn(e)
        # Refresh the Mission Table panel's MST dropdown now that mission_table_cache has been repopulated.
        if hasattr(self, 'update_mst_dropdown'):
            try: self.update_mst_dropdown()
            except Exception as e:
                self._warn(e)

    # --- Armor ---
    def adjust_armor(self, idx, delta):
        """Increment/decrement armor value for class index idx by delta and refresh derived labels."""
        if 0 <= idx < len(self.armor_entries):
            entry = self.armor_entries[idx]
            # EDF4.1's real armor values are floats, not EDF6/5's clean ints - parse/format as float for EDF4.1, same int path otherwise.
            is_edf41 = _game_is_edf41(getattr(self, 'current_game', 'EDF6'))
            try:
                val = (float(entry.get()) if is_edf41 else int(entry.get() or 0))
            except ValueError:
                val = 0.0 if is_edf41 else 0
            val = max(0, val + delta)
            entry.delete(0, "end")
            entry.insert(0, (f"{val:.3f}".rstrip('0').rstrip('.') if val != int(val) else str(int(val))) if is_edf41 else str(val))
            self.update_armor_display()

    def update_armor_display(self):
        """Wrapper around update_displays to keep translated prefixes for armor labels."""
        try:
            update_displays(self)  # external logic updates numeric values
        except Exception as e:
            self._warn(e)
        # Re-apply translated templates while preserving numeric values
        for lbl in self.base_gain_labels:
            try:
                # Extract numeric (everything after last ':')
                value_part = lbl.cget('text').split(':')[-1].strip()
                # If value_part may contain spaces (e.g., numbers), keep as-is
                template = self.tr('base_gain_label')
                # Remove trailing localized prefix before substitution
                lbl.configure(text=template.format(value=value_part))
            except Exception:
                continue
        for lbl in self.modded_gain_labels:
            try:
                value_part = lbl.cget('text').split(':')[-1].strip()
                template = self.tr('modded_gain_label')
                lbl.configure(text=template.format(value=value_part))
            except Exception:
                continue
        # Also refresh armor label (Air Raider fix) if needed
        self.refresh_armor_labels()

    # --- Loadout ---
    def update_loadout_names(self):
        unknown = self.tr('unknown_label', 'Unknown')
        for i, entry in enumerate(self.loadout_entries):
            try:
                id_val = int(entry.get())
                name = self.get_weapon_name(id_val)
                self.loadout_name_labels[i].configure(text=name if name else unknown)
            except ValueError:
                self.loadout_name_labels[i].configure(text=unknown)

    # --- Weapon Table ---
    def get_weapon_data_key(self):
        # Map UI game selections to canonical weapon data keys
        g = self.current_game
        if g.startswith('EDF6'):
            return 'EDF6'
        if g.startswith('EDF5'):
            return 'EDF5'
        if g.startswith('EDF4.1') or g.startswith('EDF4'):
            return 'EDF4.1'
        return g

    def get_weapon_name(self, weapon_id):
        lang = self.current_language
        base_game = self.get_weapon_data_key()
        wid = str(weapon_id)
        unknown = self.tr('unknown_label', 'Unknown')
        try:
            game_block = self.weapon_names_lang.get(base_game, {})
            if 'languages' in game_block:
                langs = game_block.get('languages', {})
            else:
                langs = game_block
            if lang in langs and wid in langs[lang]:
                return langs[lang][wid]
            if 'en' in langs and wid in langs['en']:
                return langs['en'][wid]
        except Exception as e:
            self._warn(e)
        return unknown

    # --- Weapon Farming Helper: given a mission+difficulty (or target weapon), shows the real weapon-level drop band using the RE-verified formula. Curve/weapon data lives in WeaponNamesLang.json. ---
    # FARMING_MODE_INFO maps each display mode string to (game_key, json_submode_key); modes without confirmed data stay unlisted so the UI shows an honest "not available" banner instead of a wrong count.
    FARMING_MODE_INFO = {
        "EDF6": ("EDF6", "EDF6"),
        "EDF6 DLC1": ("EDF6", "EDF6 DLC1"),
        "EDF6 DLC2": ("EDF6", "EDF6 DLC2"),
        "EDF5 Offline": ("EDF5", "EDF5"),
        "EDF5 Online": ("EDF5", "EDF5ON"),
        "EDF5 Offline DLC1": ("EDF5", "EDF5DLC1"),
        "EDF5 Online DLC1": ("EDF5", "EDF5ONDLC1"),
        "EDF5 Offline DLC2": ("EDF5", "EDF5DLC2"),
        "EDF5 Online DLC2": ("EDF5", "EDF5ONDLC2"),
        "EDF4.1 Offline": ("EDF4.1", "EDF4.1"),
        "EDF4.1 Offline DLC1": ("EDF4.1", "EDF4.1DLC1"),
        "EDF4.1 Offline DLC2": ("EDF4.1", "EDF4.1DLC2"),
        # 2026-09-07 (3-game audit): EDFWeaponFarming.py's EDF41_FARMING_SUBMODES already carries
        # "EDF4.1ONDLC1"/"EDF4.1ONDLC2" curve data (loaded into self.weapon_drop_curves at startup),
        # but these 2 modes were never added here - meaning the dropdown had no way to select them
        # and their curves sat unreachable. No plain "EDF4.1 Online" (base, no DLC) entry exists on
        # purpose - EDFWeaponFarming.py's own comment explains there's no "EDF4.1ON" submode key
        # since EDF4.1's online mission tables are separate files per DLC pack, not a shared mode.
        "EDF4.1 Online DLC1": ("EDF4.1", "EDF4.1ONDLC1"),
        "EDF4.1 Online DLC2": ("EDF4.1", "EDF4.1ONDLC2"),
    }
    FARMING_MODES = list(FARMING_MODE_INFO)
    FARMING_PACK_IDS = {
        "EDF6": 0, "EDF6 DLC1": 1, "EDF6 DLC2": 2,
        "EDF5 Offline": 0, "EDF5 Online": 0,
        "EDF5 Offline DLC1": 1, "EDF5 Online DLC1": 1,
        "EDF5 Offline DLC2": 2, "EDF5 Online DLC2": 2,
        # 0 for the same reason weapon_meta's own `pack` field is uniformly 0 for EDF4.1 (see
        # EDFWeaponFarming.py) - no mission-pack-exclusive weapons found to gate on.
        "EDF4.1 Offline": 0,
        "EDF4.1 Offline DLC1": 0,
        "EDF4.1 Offline DLC2": 0,
        "EDF4.1 Online DLC1": 0,
        "EDF4.1 Online DLC2": 0,
    }

    def _farming_mode_game_key(self, mode=None):
        """The WeaponNamesLang.json top-level block ('EDF6' or 'EDF5') that `mode` (defaults to
        the currently-selected Farming panel Mode) should pull weapon_meta/category_names
        from."""
        mode = mode if mode is not None else self.farming_mode_var.get()
        return self.FARMING_MODE_INFO.get(mode, ("EDF6", mode))[0]

    def _refresh_farming_mode_dropdown(self):
        """(Re)builds the Farming panel's Mode dropdown to also list any modded mission pack currently registered in games_metadata. Runs at panel-build time and again whenever update_mst_dropdown() runs. Does NOT provide any actual weapon data for a modded pack - selecting one shows the same honest "curve data not available" banner as any other null curve cell."""
        if not hasattr(self, 'farming_mode_dropdown'):
            return
        modded = sorted(k for k in self.games_metadata.keys() if self._is_synthetic_pack_key(k))
        values = list(self.FARMING_MODES) + [m for m in modded if m not in self.FARMING_MODES]
        try:
            self.farming_mode_dropdown.configure(values=values)
        except Exception as e:
            self._warn(e)
        if values and self.farming_mode_var.get() not in values:
            self.farming_mode_var.set(values[0])
            self.on_farming_mode_change()

    def refresh_weapon_farming_labels(self):
        """Retranslate the Weapon Farming Helper's static labels/placeholders on a language switch, mirroring refresh_armor_labels/refresh_loadout_labels/refresh_mission_labels for this panel's sections. farming_direction_seg/farming_diff_dropdown's display text is handled separately in refresh_weapon_farming_diff_dropdown(). farming_mode_dropdown's values (literal game/DLC identifiers) are deliberately left untranslated."""
        if hasattr(self, 'farming_mode_label'):
            try: self.farming_mode_label.configure(text=self.tr('weapon_farming_mode_label', 'Mode:'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'farming_difficulty_label'):
            try: self.farming_difficulty_label.configure(text=self.tr('weapon_farming_difficulty_label', 'Difficulty:'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'farming_weapon_search'):
            try: self.farming_weapon_search.configure(placeholder_text=self.tr('weapon_farming_search_placeholder', 'Search target weapon by name...'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'farming_curve_note_label'):
            try:
                self.farming_curve_note_label.configure(text=self.tr(
                    'weapon_farming_curve_note',
                    'Curve endpoints (advanced) — fill in once extracted from config.sgo, then Save Curve:'
                ))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'farming_curve_min_label'):
            try: self.farming_curve_min_label.configure(text=self.tr('weapon_farming_min_label', 'Min:'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'farming_curve_max_label'):
            try: self.farming_curve_max_label.configure(text=self.tr('weapon_farming_max_label', 'Max:'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'farming_curve_band_label'):
            try: self.farming_curve_band_label.configure(text=self.tr('weapon_farming_band_label', 'Band:'))
            except Exception as e:
                self._warn(e)
        if hasattr(self, 'farming_curve_save_btn'):
            try: self.farming_curve_save_btn.configure(text=self.tr('weapon_farming_curve_save', 'Save Curve'))
            except Exception as e:
                self._warn(e)
        # Re-translate the "By Mission" / "By Target Weapon" segmented button's labels and keep the visible selection in sync with the canonical farming_direction_var.
        if hasattr(self, 'farming_direction_seg'):
            try:
                self.farming_direction_seg.configure(values=self._farming_direction_labels())
                current_canonical = self.farming_direction_var.get() if hasattr(self, 'farming_direction_var') else "By Mission"
                self.farming_direction_display_var.set(self._farming_direction_label(current_canonical))
            except Exception as e:
                self._warn(e)
        # Re-translate the farming results table's column headers; the column ids stay fixed English strings, only the displayed heading text changes.
        if hasattr(self, 'farming_results_tree'):
            try: self._configure_farming_results_columns()
            except Exception as e:
                self._warn(e)
        # Re-run on_farming_mission_slide with the current position so the "Mission X of Y" label picks up the new language immediately.
        if hasattr(self, 'farming_mission_slider'):
            try: self.on_farming_mission_slide(self.farming_mission_slider.get())
            except Exception as e:
                self._warn(e)

    def build_weapon_farming_section(self):
        if not hasattr(self, 'weapon_farming_content'):
            return
        farming_frame = ctk.CTkFrame(self.weapon_farming_content)
        farming_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        # Status banner: never packed with empty text (an empty CTkLabel doesn't reliably collapse after wrapping to 2+ lines) - _set_farming_status() packs it in only when there's a real warning, pack_forget()s it otherwise.
        self.farming_status_label = ctk.CTkLabel(
            farming_frame, text="", font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"), fg_color="transparent",
            text_color="#d9a441", wraplength=820, justify="left"
        )
        # Not packed here on purpose - see _set_farming_status().

        controls_row = ctk.CTkFrame(farming_frame)
        controls_row.pack(fill="x", padx=8, pady=4)
        self.farming_controls_row = controls_row  # anchor point for _set_farming_status' before=

        # Kept as self.farming_mode_label so refresh_weapon_farming_labels() can retranslate it on a language switch.
        self.farming_mode_label = ctk.CTkLabel(controls_row, text=self.tr('weapon_farming_mode_label', 'Mode:'))
        self.farming_mode_label.pack(side="left", padx=(4, 2))
        self.farming_mode_var = ctk.StringVar(value=self.FARMING_MODES[0])
        self.farming_mode_dropdown = ctk.CTkOptionMenu(
            controls_row, values=self.FARMING_MODES, variable=self.farming_mode_var,
            command=lambda v: self.on_farming_mode_change()
        )
        self.farming_mode_dropdown.pack(side="left", padx=(0, 10))
        self._refresh_farming_mode_dropdown()

        self.farming_difficulty_label = ctk.CTkLabel(controls_row, text=self.tr('weapon_farming_difficulty_label', 'Difficulty:'))
        self.farming_difficulty_label.pack(side="left", padx=(4, 2))
        # farming_diff_var stays canonical English since it's used as a dict key elsewhere; farming_diff_display_var is what's bound to the dropdown, mapped back to canonical on selection.
        self.farming_diff_var = ctk.StringVar(value="Inferno")
        self.farming_diff_display_var = ctk.StringVar(value=self._mission_diff_label("Inferno"))
        self.farming_diff_dropdown = ctk.CTkOptionMenu(
            controls_row, values=[self._mission_diff_label(d) for d in wf.DIFFICULTY_ORDER],
            variable=self.farming_diff_display_var,
            command=self.on_farming_diff_display_change
        )
        self.farming_diff_dropdown.pack(side="left", padx=(0, 10))

        # farming_direction_var stays canonical English (compared against elsewhere in the app); farming_direction_display_var is bound to the widget and mapped back to canonical on selection.
        self.farming_direction_var = ctk.StringVar(value="By Mission")
        self.farming_direction_display_var = ctk.StringVar(value=self._farming_direction_label("By Mission"))
        self.farming_direction_seg = ctk.CTkSegmentedButton(
            controls_row, values=self._farming_direction_labels(),
            variable=self.farming_direction_display_var,
            command=lambda v: self.on_farming_direction_display_change(v)
        )
        self.farming_direction_seg.pack(side="left", padx=(0, 10))

        # --- "By Mission" sub-panel: a slider, like the earlier mission-context demo ---
        self.farming_mission_frame = ctk.CTkFrame(farming_frame)
        self.farming_mission_frame.pack(fill="x", padx=8, pady=4)
        self.farming_mission_label = ctk.CTkLabel(self.farming_mission_frame, text="Mission 1", width=110, anchor="w")
        self.farming_mission_label.pack(side="left", padx=(4, 8))
        self.farming_mission_slider = ctk.CTkSlider(
            self.farming_mission_frame, from_=0, to=1, number_of_steps=1,
            command=lambda v: self.on_farming_mission_slide(v)
        )
        self.farming_mission_slider.pack(side="left", fill="x", expand=True, padx=4)
        # CTkSlider hardcodes its internal value to 0.5 on construction; force it to 0 here so the handle starts at Mission 1 as its label claims.
        self.farming_mission_slider.set(0)
        self._farming_mission_slider_initialized = False

        # --- "By Target Weapon" sub-panel: search box, hidden until that mode is selected ---
        self.farming_weapon_frame = ctk.CTkFrame(farming_frame)
        self.farming_weapon_search = ctk.CTkEntry(
            self.farming_weapon_frame,
            placeholder_text=self.tr('weapon_farming_search_placeholder', 'Search target weapon by name...')
        )
        self.farming_weapon_search.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self.farming_weapon_search.bind("<KeyRelease>", lambda e: self.refresh_weapon_farming_results())

        # Summary line above the table (band range, count, or search-empty hint), since the table itself only holds rows.
        self.farming_summary_label = ctk.CTkLabel(farming_frame, text="", font=(FONT_FAMILY, BASE_FONT_SIZE), anchor="w")
        self.farming_summary_label.pack(anchor="w", padx=8, pady=(0, 2), fill="x")

        # Results table - same ttk.Treeview + scrollbar pattern as the weapon table above, including the same _exempt_from_global_scroll fix. Columns reconfigured per direction by _configure_farming_results_columns().
        self.farming_results_frame = tk.Frame(farming_frame)
        self.farming_results_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._exempt_from_global_scroll(self.farming_results_frame)

        self.farming_results_tree = ttk.Treeview(
            master=self.farming_results_frame, show="headings", height=10
        )
        self.farming_results_vsb = ttk.Scrollbar(
            master=self.farming_results_frame, orient="vertical",
            command=self.farming_results_tree.yview
        )
        # Vertical-scrollbar-only, matching self.tree's pattern above; stretch=False on columns stays a real fix for widths not being authoritative across window sizes.
        self.farming_results_tree.configure(
            yscrollcommand=self.farming_results_vsb.set,
        )
        self.farming_results_vsb.pack(side="right", fill="y")
        self.farming_results_tree.pack(side="left", expand=True, fill="both")
        self._configure_farming_results_columns()

        # --- Manual curve entry: how real config.sgo values get plugged in once known ---
        curve_edit_frame = ctk.CTkFrame(farming_frame)
        curve_edit_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.farming_curve_note_label = ctk.CTkLabel(
            curve_edit_frame,
            text=self.tr('weapon_farming_curve_note',
                          'Curve endpoints (advanced) — fill in once extracted from config.sgo, then Save Curve:'),
            font=(FONT_FAMILY, BASE_FONT_SIZE, "bold"),
            wraplength=820, justify="left"
        )
        self.farming_curve_note_label.pack(anchor="w", padx=4)
        curve_row = ctk.CTkFrame(curve_edit_frame)
        curve_row.pack(fill="x", padx=4, pady=2)
        # Same purple as the Armor/Loadout editable fields (self.colors[4]) - same "type a value, it gets written" meaning, just targeting WeaponNamesLang.json instead of the save.
        self.farming_curve_min_label = ctk.CTkLabel(curve_row, text=self.tr('weapon_farming_min_label', 'Min:'))
        self.farming_curve_min_label.pack(side="left")
        self.farming_curve_min_entry = ctk.CTkEntry(curve_row, width=80, fg_color=self.colors[4], text_color=self.text_colors[4])
        self.farming_curve_min_entry.pack(side="left", padx=(2, 10))
        self.farming_curve_max_label = ctk.CTkLabel(curve_row, text=self.tr('weapon_farming_max_label', 'Max:'))
        self.farming_curve_max_label.pack(side="left")
        self.farming_curve_max_entry = ctk.CTkEntry(curve_row, width=80, fg_color=self.colors[4], text_color=self.text_colors[4])
        self.farming_curve_max_entry.pack(side="left", padx=(2, 10))
        self.farming_curve_band_label = ctk.CTkLabel(curve_row, text=self.tr('weapon_farming_band_label', 'Band:'))
        self.farming_curve_band_label.pack(side="left")
        self.farming_curve_band_entry = ctk.CTkEntry(curve_row, width=80, fg_color=self.colors[4], text_color=self.text_colors[4])
        self.farming_curve_band_entry.pack(side="left", padx=(2, 10))
        self.farming_curve_save_btn = ctk.CTkButton(
            curve_row, text=self.tr('weapon_farming_curve_save', 'Save Curve'), width=100,
            command=self.on_farming_curve_save
        )
        self.farming_curve_save_btn.pack(side="left", padx=(10, 0))

        self.on_farming_mode_change()
        self.on_farming_direction_change()

    def _farming_active_curve(self):
        mode = self.farming_mode_var.get()
        diff = self.farming_diff_var.get()
        return (self.weapon_drop_curves or {}).get(mode, {}).get(diff, {})

    def _farming_mission_count(self):
        mode = self.farming_mode_var.get()
        meta = self.games_metadata.get(mode, {})
        return max(2, int(meta.get('total_missions', 2)))

    def on_farming_diff_display_change(self, display_value):
        """Command callback for farming_diff_dropdown: maps the clicked label back to canonical, updates farming_diff_var, then delegates to on_farming_mode_change() for the real refresh."""
        canonical_map = {self._mission_diff_label(d): d for d in wf.DIFFICULTY_ORDER}
        self.farming_diff_var.set(canonical_map.get(display_value, display_value))
        self.on_farming_mode_change()

    def on_farming_mode_change(self):
        """Mode or difficulty dropdown changed: resync the mission slider's range to the
        selected mode's real mission count (games_metadata), and reload the curve-entry
        fields with whatever's currently saved for this mode/difficulty (blank if null)."""
        if not hasattr(self, 'farming_mission_slider'):
            return
        count = self._farming_mission_count()
        try:
            self.farming_mission_slider.configure(from_=0, to=count - 1, number_of_steps=count - 1)
            # Force-reset to 0 only the first time this runs (real first-load); keep the overflow guard for later mode swaps so an already-chosen mission survives a same-range difficulty change.
            if not getattr(self, '_farming_mission_slider_initialized', False):
                self.farming_mission_slider.set(0)
                self._farming_mission_slider_initialized = True
            elif self.farming_mission_slider.get() > count - 1:
                self.farming_mission_slider.set(0)
        except Exception as e:
            self._warn(e)
        try:
            self.on_farming_mission_slide(self.farming_mission_slider.get())
        except Exception as e:
            self._warn(e)
        curve = self._farming_active_curve()
        for entry, key in (
            (self.farming_curve_min_entry, 'min_endpoint'),
            (self.farming_curve_max_entry, 'max_endpoint'),
            (self.farming_curve_band_entry, 'band_width'),
        ):
            entry.delete(0, 'end')
            val = curve.get(key)
            if val is not None:
                entry.insert(0, str(val))
        # No extra refresh_weapon_farming_results() call needed here - the
        # on_farming_mission_slide() call above already triggers one.

    def _farming_direction_label(self, canonical):
        """Translated display text for the farming_direction_seg's two options; `canonical` is always the internal English key, never the currently-displayed language."""
        if canonical == "By Target Weapon":
            return self.tr('weapon_farming_by_target_weapon', 'By Target Weapon')
        return self.tr('weapon_farming_by_mission', 'By Mission')

    def _farming_direction_labels(self):
        return [self._farming_direction_label("By Mission"), self._farming_direction_label("By Target Weapon")]

    def on_farming_direction_display_change(self, display_value):
        """Command callback for farming_direction_seg: maps the clicked label back to canonical, updates farming_direction_var, and delegates to on_farming_direction_change() for the real show/hide logic."""
        canonical = "By Target Weapon" if display_value == self._farming_direction_label("By Target Weapon") else "By Mission"
        self.farming_direction_var.set(canonical)
        self.on_farming_direction_change()

    def on_farming_direction_change(self):
        # before=self.farming_summary_label pins the re-shown frame back to its original slot every time, instead of pack() appending it to the end of the packing order.
        direction = self.farming_direction_var.get()
        if direction == "By Mission":
            self.farming_weapon_frame.pack_forget()
            self.farming_mission_frame.pack(fill="x", padx=8, pady=4, before=self.farming_summary_label)
        else:
            self.farming_mission_frame.pack_forget()
            self.farming_weapon_frame.pack(fill="x", padx=8, pady=4, before=self.farming_summary_label)
        self._configure_farming_results_columns()
        self.refresh_weapon_farming_results()

    # Column id -> translation key/default, reusing keys that exist elsewhere for the same concept instead of duplicating them under new weapon_farming_* keys.
    _FARMING_RESULTS_COL_KEYS = {
        "ID": ('weapon_table_col_id', 'ID'),
        "Name": ('weapon_table_col_name', 'Name'),
        "Float Level": ('weapon_farming_col_float_level', 'Float Level'),
        "X25 Real Level": ('weapon_farming_col_x25', 'X25 Real Level'),
        "In Range": ('weapon_farming_col_in_range', 'In Range'),
        "Category": ('weapon_farming_col_category', 'Category'),
        "Pack": ('weapon_farming_col_pack', 'Pack'),
        "Weight": ('weapon_farming_col_weight', 'Weight'),
        "Easy": ('mission_table_col_easy', 'Easy'),
        "Normal": ('mission_table_col_normal', 'Normal'),
        "Hard": ('mission_table_col_hard', 'Hard'),
        "Hardest": ('mission_table_col_hardest', 'Hardest'),
        "Inferno": ('mission_table_col_inferno', 'Inferno'),
    }

    def _farming_results_col_label(self, col_id):
        """Translated heading text for a farming-results Treeview column id, falling back to the raw id itself for anything unrecognized."""
        key, default = self._FARMING_RESULTS_COL_KEYS.get(col_id, (None, col_id))
        return self.tr(key, default) if key else default

    def _configure_farming_results_columns(self):
        """(Re)builds the results Treeview's column set for the current direction. 'By Mission' lists eligible weapons; 'By Target Weapon' lists search matches with one column per difficulty."""
        if not hasattr(self, 'farming_results_tree'):
            return
        tree = self.farming_results_tree
        # Widened from the original cramped set (which clipped "X25 Real Level" and "Weight" headers at the table's font size) to actually use the tab's available width. NAME_COL_WIDTH/CATEGORY_COL_WIDTH kept identical across both directions so they don't visibly jump when toggling direction.
        ID_COL_WIDTH = 55
        NAME_COL_WIDTH = 320
        FLOAT_LEVEL_COL_WIDTH = 150
        X25_COL_WIDTH = 130
        CATEGORY_COL_WIDTH = 190
        PACK_COL_WIDTH = 65
        if self.farming_direction_var.get() == "By Mission":
            columns = ["ID", "Name", "Float Level", "X25 Real Level", "In Range", "Category", "Pack", "Weight"]
            widths = [ID_COL_WIDTH, NAME_COL_WIDTH, FLOAT_LEVEL_COL_WIDTH, X25_COL_WIDTH, 120, CATEGORY_COL_WIDTH, PACK_COL_WIDTH, 90]
            anchors = ["c", "w", "w", "c", "c", "w", "c", "c"]
        else:
            columns = ["ID", "Name", "Float Level", "X25 Real Level", "Category", "Pack"] + wf.DIFFICULTY_ORDER
            widths = [ID_COL_WIDTH, NAME_COL_WIDTH, FLOAT_LEVEL_COL_WIDTH, X25_COL_WIDTH, CATEGORY_COL_WIDTH, PACK_COL_WIDTH] + [90] * len(wf.DIFFICULTY_ORDER)
            anchors = ["c", "w", "w", "c", "w", "c"] + ["c"] * len(wf.DIFFICULTY_ORDER)
        tree.configure(columns=columns)
        for i, (col, width, anchor) in enumerate(zip(columns, widths, anchors)):
            # Column ids stay fixed English strings (ttk.Treeview identifies columns by id); only the displayed heading label is translated here.
            tree.heading(col, text=self._farming_results_col_label(col))
            # stretch=False makes width= authoritative and fixed regardless of window size, instead of ttk's default stretch=True silently redistributing extra pixels per column - EXCEPT the
            # last column, which stretches on purpose so the table fills the panel's real width
            # (was leaving a wide dead strip past "Weight"/the last difficulty column whenever the
            # window was wider than the fixed columns' sum) without reintroducing the original
            # "every column's width drifts with the window" problem the all-stretch=False change fixed.
            tree.column(col, width=width, anchor=anchor, stretch=(i == len(columns) - 1))

    def on_farming_mission_slide(self, value):
        idx = int(round(float(value)))
        count = self._farming_mission_count()
        self.farming_mission_label.configure(
            text=self.tr('weapon_farming_mission_of', 'Mission {current} of {total}').format(current=idx + 1, total=count)
        )
        self.refresh_weapon_farming_results()

    def on_farming_curve_save(self):
        """Persists the 3 curve-entry fields into WeaponNamesLang.json's mode/difficulty slot via wf.save_drop_curve_cell (preserves every other cell). Blank fields save as null. Reads via resolved_translation_path but always writes via translation_data_path - same exe-adjacent persist fix as the Translation Editor, needed so a packaged build's first edit doesn't overwrite the bundled file with a doc missing every other weapon name."""
        mode = self.farming_mode_var.get()
        diff = self.farming_diff_var.get()

        def parse(entry):
            txt = entry.get().strip()
            if txt == '':
                return None
            try:
                return float(txt)
            except ValueError:
                return None

        new_vals = {
            'min_endpoint': parse(self.farming_curve_min_entry),
            'max_endpoint': parse(self.farming_curve_max_entry),
            'band_width': parse(self.farming_curve_band_entry),
        }
        try:
            game_key, submode_key = self.FARMING_MODE_INFO.get(mode, ('EDF6', mode))
            wf.save_drop_curve_cell(
                submode_key, diff, new_vals,
                path=translation_data_path('WeaponNamesLang.json'),
                load_path=resolved_translation_path('WeaponNamesLang.json'),
                game_key=game_key,
            )
            self.weapon_drop_curves.setdefault(mode, {})[diff] = new_vals
        except Exception as e:
            self._warn(e, 'on_farming_curve_save')
        self.refresh_weapon_farming_results()

    def _set_farming_status(self, text):
        """Shows/hides the farming panel's warning banner. Empty text -> pack_forget() so the banner takes zero layout space, rather than leaving an empty-but-still-packed label."""
        label = self.farming_status_label
        if text:
            label.configure(text=text)
            if not label.winfo_ismapped():
                label.pack(anchor="w", padx=8, pady=(0, 6), fill="x", before=self.farming_controls_row)
        else:
            if label.winfo_ismapped():
                label.pack_forget()
            label.configure(text="")

    # Weapon levels are stored/compared internally as small raw floats; x25 is display-only, matching the community wiki's "Weapon Level *25" convention, not used in the actual drop-filter math.
    FARMING_DISPLAY_SCALE = 25.0

    def _farming_x25(self, level_req):
        """raw level_req -> the wiki's "Weapon Level" display number, always rounded up (ceiling), not round-to-nearest. Rounds to 4 decimals first to collapse float32-conversion noise before ceiling, so an exact x25 integer doesn't get bumped a whole level too high."""
        return math.ceil(round(level_req * self.FARMING_DISPLAY_SCALE, 4))

    def _farming_category_label(self, category_id, game_key=None):
        """category id (P2) -> a readable label for the Category column: strips the "Weapon_" prefix and turns underscores into spaces, falling back to the raw numeric id if unknown. `game_key` defaults to the Farming panel's currently-selected mode's game family."""
        game_key = game_key or self._farming_mode_game_key()
        table = getattr(self, 'weapon_category_names_by_game', {}).get(game_key) or self.weapon_category_names
        raw = (table or {}).get(str(category_id))
        if not raw:
            return str(category_id)
        label = raw[len("Weapon_"):] if raw.startswith("Weapon_") else raw
        return label.replace("_", " ")

    def refresh_weapon_farming_results(self):
        if not hasattr(self, 'farming_results_tree'):
            return
        tree = self.farming_results_tree
        tree.delete(*tree.get_children())

        mode = self.farming_mode_var.get()
        diff = self.farming_diff_var.get()
        active_pack = self.FARMING_PACK_IDS.get(mode, 0)
        curve = self._farming_active_curve()
        mission_count = self._farming_mission_count()
        # Pick the weapon list matching the selected mode's game family - EDF5/EDF6 have completely different weapon rosters, so mismatching them would show nonsense results.
        game_key = self._farming_mode_game_key(mode)
        weapons = getattr(self, 'weapon_drop_data_by_game', {}).get(game_key, [])
        pack_tags = {0: 'base', 1: 'DLC1', 2: 'DLC2'}

        if not wf.curve_data_available(curve):
            self._set_farming_status(self.tr(
                'weapon_farming_curve_missing',
                "⚠ Curve data for {mode} / {diff} hasn't been extracted from config.sgo yet — "
                "the exact mission-by-mission level range can't be computed. Fill in Min/Max/Band "
                "below once you have real values (see SessionHistory\\SESSION_45_WEAPON_DROP_"
                "LEVEL_BAND.md for how), or use 'By Target Weapon' to see a weapon's own verified "
                "progress value (P4) and DLC pack in the meantime."
            ).format(mode=mode, diff=diff))
        else:
            self._set_farming_status("")

        if not weapons:
            self.farming_summary_label.configure(text=self.tr(
                'weapon_farming_data_unavailable',
                "Weapon drop data unavailable (WeaponNamesLang.json's weapon_meta/level float failed to load)."
            ))
            return

        if self.farming_direction_var.get() == "By Mission":
            idx = int(round(self.farming_mission_slider.get()))
            band = wf.compute_level_band(curve, wf.mission_progress_fraction(idx, mission_count))
            if band is None:
                self.farming_summary_label.configure(text=self.tr(
                    'weapon_farming_no_match_mission',
                    "Mission {current}/{total} ({diff}): no matching weapons shown — curve data not yet available."
                ).format(current=idx + 1, total=mission_count, diff=diff))
                return
            level_min, level_max, tolerance = band
            self.farming_summary_label.configure(text=self.tr(
                'weapon_farming_level_band',
                "Level band at Mission {current}/{total} ({diff}): {level_min} - {level_max}  "
                "(tolerance ±{tolerance})   |  x25: {x25_min} - {x25_max}"
            ).format(
                current=idx + 1, total=mission_count, diff=diff,
                level_min=f"{level_min:.3f}", level_max=f"{level_max:.3f}",
                tolerance=f"{tolerance:.3f}",
                x25_min=self._farming_x25(level_min), x25_max=self._farming_x25(level_max),
            ))
            matches = wf.weapons_droppable_at_mission(weapons, curve, idx, mission_count, active_pack)
            for w_ in sorted(matches, key=lambda w: w.level_req):
                # Rows here already passed weapon_matches_band (which allows squeaking in within +tolerance), so surface that distinction explicitly rather than treating all matches as strictly in-range.
                tol = tolerance if w_.tag_count != 0 else 0.0
                if level_min <= w_.level_req <= level_max:
                    in_range = self.tr('weapon_farming_in_range', '✓ In Range')
                elif level_min <= w_.level_req <= level_max + tol:
                    in_range = self.tr('weapon_farming_in_tolerance', '≈ Tolerance')
                else:
                    in_range = self.tr('weapon_farming_out_of_range', '✗')
                tree.insert("", "end", values=(
                    w_.id, self.get_weapon_name(w_.id), repr(w_.level_req),
                    self._farming_x25(w_.level_req), in_range,
                    self._farming_category_label(w_.category),
                    pack_tags.get(w_.pack, str(w_.pack)), f"x{w_.drop_weight:g}",
                ))
        else:
            query = self.farming_weapon_search.get().strip().lower()
            if not query:
                self.farming_summary_label.configure(text=self.tr(
                    'weapon_farming_search_hint', "Type part of a weapon's name above to look it up."
                ))
                return
            found = [
                w_ for w_ in weapons
                if query in w_.name.lower() or query in self.get_weapon_name(w_.id).lower()
            ][:25]
            if not found:
                self.farming_summary_label.configure(text=self.tr(
                    'weapon_farming_no_match_search', "No weapons matching '{query}'."
                ).format(query=query))
            else:
                self.farming_summary_label.configure(text=self.tr(
                    'weapon_farming_match_count', "{count} weapon(s) matching '{query}' (showing up to 25):"
                ).format(count=len(found), query=query))
            no_data_text = self.tr('weapon_farming_no_data', 'no data')
            never_text = self.tr('weapon_farming_never', 'never')
            # availability==3 (SINGLE DLC) never passes weapon_matches_band's eligibility gate at
            # any difficulty - confirmed both by that gate's own logic and, independently, by
            # invadersfromplanet.space's own drop tables (which show a literal "DLC" tag instead of
            # a weight% for these weapons, in every mode - ON, DLC1, DLC2 alike). Short-circuit
            # straight to a "DLC only" tag instead of computing 5 identical "never"s per weapon -
            # cheaper, and tells the player why (owned via the DLC / Own All, not farmable) rather
            # than looking like a data gap.
            dlc_only_text = self.tr('weapon_farming_dlc_only', 'DLC only')
            for w_ in found:
                row = [w_.id, self.get_weapon_name(w_.id), repr(w_.level_req),
                       self._farming_x25(w_.level_req),
                       self._farming_category_label(w_.category),
                       pack_tags.get(w_.pack, str(w_.pack))]
                if w_.availability == 3:
                    row.extend([dlc_only_text] * len(wf.DIFFICULTY_ORDER))
                else:
                    for d in wf.DIFFICULTY_ORDER:
                        c = (self.weapon_drop_curves or {}).get(mode, {}).get(d, {})
                        if not wf.curve_data_available(c):
                            row.append(no_data_text)
                        else:
                            earliest = wf.earliest_mission_for_weapon(w_, c, mission_count, active_pack)
                            row.append(f"#{earliest + 1}" if earliest is not None else never_text)
                tree.insert("", "end", values=tuple(row))

    def update_weapon_table_headers(self):
        # Update the weapon table (Treeview) column headers to match the current language
        stat_label = self.tr('weapon_table_col_stat')
        columns = [
            self.tr('weapon_table_col_id'),
            self.tr('weapon_table_col_name'),
            self.tr('weapon_table_col_condition'),
        ] + [f"{stat_label}{i+1}" for i in range(8)]
        # Update headings
        for i, col in enumerate(columns):
            self.tree.heading(f"#{i+1}", text=col)

    def rebuild_weapon_table_columns_for_game(self):
        """Show only ID/Name/Ownership for EDF4.1 and disable Sudo Max; restore the full 11-column EDF6/5 view otherwise. Stat1-8 are EDF6/5-specific with no EDF4.1 equivalent, so they're hidden via ttk.Treeview's `displaycolumns` (no data lost switching back). Own All/Poverty stay enabled since they only touch the Ownership column."""
        if not hasattr(self, 'tree'):
            return
        game = getattr(self, 'current_game', 'EDF6')
        all_cols = list(self.tree['columns'])
        is_edf41 = _game_is_edf41(game)
        if is_edf41 and len(all_cols) >= 3:
            try: self.tree['displaycolumns'] = all_cols[:3]
            except Exception as e: self._warn(e)
        else:
            try: self.tree['displaycolumns'] = all_cols
            except Exception as e: self._warn(e)
        if hasattr(self, 'sudo_max_btn'):
            try: self.sudo_max_btn.configure(state=("disabled" if is_edf41 else "normal"))
            except Exception as e: self._warn(e)
        # Relabel the 3rd column "Ownership" for EDF4.1, since it's the only per-weapon state that game exposes.
        try:
            self.tree.heading("#3", text=("Ownership" if is_edf41 else self.tr('weapon_table_col_condition')))
        except Exception as e:
            self._warn(e)

    def update_weapon_table_names(self):
        # Use fixed column index (second column) regardless of language
        if not hasattr(self, 'tree'):
            return
        name_column_id = self.tree['columns'][1]  # stable by index
        unknown = self.tr('unknown_label', 'Unknown')
        gst_snapshot = getattr(self, 'weapon_limit_gst_snapshot', None)
        source = self.weapon_limit_source_var.get() if hasattr(self, 'weapon_limit_source_var') else 'GST'
        for idx, row in enumerate(self.weapon_data):
            try:
                weapon_id = str(row[0])
                name = self.get_weapon_name(weapon_id)
                if not name:
                    name = unknown
                self.weapon_data[idx][1] = name
                # Keep the GST snapshot's Name column in sync too - it shares the same weapon ids
                # for the slots it has, so the resolved name is identical. Without this, switching
                # to "Viewing: GST" would show "Unknown" placeholders instead of real names.
                if gst_snapshot is not None and idx < len(gst_snapshot):
                    gst_snapshot[idx][1] = name
                if self.tree.exists(str(idx)):
                    display_row = gst_snapshot[idx] if (source == 'GST' and gst_snapshot is not None and idx < len(gst_snapshot)) else row
                    self.tree.set(str(idx), column=name_column_id, value=display_row[1])
            except Exception:
                continue
        # After names updated, re-apply filter to reflect any search in progress
        try:
            self.filter_table()
        except Exception as e:
            self._warn(e)

    def _weapon_table_view_cutoff(self):
        """How many leading weapon rows should ever be attached to the tree, given the current
        GST/BIN source. Viewing GST is always capped at however many rows
        app.weapon_limit_gst_snapshot actually has (MAIN.GST never holds more than 2048 to begin
        with); viewing BIN always shows every slot WeaponLimit loaded - the max available, no
        separate toggle."""
        source = self.weapon_limit_source_var.get() if hasattr(self, 'weapon_limit_source_var') else 'GST'
        if source == 'GST':
            return len(getattr(self, 'weapon_limit_gst_snapshot', []) or [])
        return len(getattr(self, 'weapon_data', []) or [])

    def filter_table(self, event=None):
        if not hasattr(self, 'tree'):
            return
        query = self.search_entry.get().strip() if hasattr(self, 'search_entry') else ''
        is_blank_query = (query == '' or query == self.search_placeholder_value)
        qlower = query.lower()
        # The GST/BIN source switch narrows which rows are even eligible to be attached - see
        # _weapon_table_view_cutoff() (GST is capped at whatever MAIN.GST held; BIN always shows
        # the max, every slot WeaponLimit loaded). This is purely a view filter on top of the
        # search box, same detach/reattach mechanism as before - app.weapon_data (and Save) is
        # never touched by any of it.
        cutoff = self._weapon_table_view_cutoff()
        all_iids = [str(i) for i in range(len(getattr(self, 'weapon_data', [])))]
        for iid in all_iids:
            if not self.tree.exists(iid):
                continue
            if int(iid) >= cutoff:
                self.tree.detach(iid)
                continue
            if is_blank_query:
                self.tree.reattach(iid, '', 'end')
                continue
            values = self.tree.item(iid, 'values')
            # ID + Name columns (0,1)
            id_text = str(values[0]).lower() if values else ''
            name_text = str(values[1]).lower() if len(values) > 1 else ''
            if qlower in id_text or qlower in name_text:
                self.tree.reattach(iid, '', 'end')
            else:
                self.tree.detach(iid)

    def update_search_placeholder(self):
        trans = self._trans_dict()
        new_placeholder = trans.get(self.search_placeholder_key, 'Search by weapon name...')
        old_placeholder = getattr(self, 'search_placeholder_value', '')
        self.search_placeholder_value = new_placeholder
        if hasattr(self, 'search_entry'):
            try:
                self.search_entry.configure(placeholder_text=new_placeholder)
            except Exception as e:
                self._warn(e)
            current_text = self.search_entry.get().strip()
            if current_text in ('', old_placeholder, new_placeholder):
                self.search_entry.delete(0, 'end')
        try:
            self.filter_table()
        except Exception as e:
            self._warn(e)

    def edit_cell(self, event):
        # Improved editor: Name column accepts free text; Condition (ownership/state, see
        # WEAPON_OWNED_CONDITION note) is a plain byte 0-255; stats limited to 0-65535
        if not hasattr(self, 'tree'):
            return
        if getattr(self, '_weapon_table_read_only', False):
            # Viewing GST: that's a read-only snapshot of MAIN.GST's own values, never editable
            # directly - switch to "Viewing: BIN" (or use Port GST -> BIN) to make changes.
            if hasattr(self, 'weapon_limit_status_label'):
                try:
                    self.weapon_limit_status_label.configure(text=self.tr(
                        'weapon_limit_gst_readonly', "GST view is read-only - switch to BIN to edit, or use Port GST -> BIN."))
                except Exception as e:
                    self._warn(e)
            return
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item or not column:
            return
        col_idx = int(column.replace('#', '')) - 1
        if col_idx == 0:
            return  # ID column read-only
        bbox = self.tree.bbox(item, column)
        if not bbox:
            return
        x, y, w, h = bbox
        x += self.tree.winfo_x()
        y += self.tree.winfo_y()
        current_value = self.tree.item(item, 'values')[col_idx]
        # Create CTkEntry with width/height in constructor to satisfy customtkinter requirements
        try:
            edit_entry = ctk.CTkEntry(self.tree_frame, width=w, height=h)
        except Exception:
            # Fallback to width-only if height not supported
            try:
                edit_entry = ctk.CTkEntry(self.tree_frame, width=w)
            except Exception:
                edit_entry = ctk.CTkEntry(self.tree_frame)
        # Place without passing width/height (must be in constructor)
        edit_entry.place(x=x, y=y)
        edit_entry.insert(0, current_value)
        edit_entry.focus()
        def save_edit(event=None):
            new_value = edit_entry.get().strip()
            if new_value == '':
                edit_entry.destroy(); return
            values = list(self.tree.item(item, 'values'))
            row_idx = None
            try:
                row_idx = int(item)
            except Exception as e:
                self._warn(e)
            # Name column (index 1) accepts any text
            if col_idx == 1:
                values[col_idx] = new_value
                try:
                    if row_idx is not None:
                        self.weapon_data[row_idx][col_idx] = new_value
                except Exception as e:
                    self._warn(e)
                self.tree.item(item, values=values)
                edit_entry.destroy()
                return
            # Numeric columns: validate according to column
            try:
                val = int(new_value)
                if col_idx == 2:
                    # Ownership/condition value: real low-byte condition (0=unowned, 3=owned/normal); the UI only ever needs a plain byte here.
                    if val < 0 or val > 0xFF:
                        raise ValueError
                else:
                    # Stat columns: allow 0..65535
                    if not 0 <= val <= 65535:
                        raise ValueError
                values[col_idx] = val
                self.tree.item(item, values=values)
                if row_idx is not None:
                    try: self.weapon_data[row_idx][col_idx] = val
                    except Exception as e:
                        self._warn(e)
            except ValueError:
                # invalid numeric input - ignore change
                pass
            finally:
                edit_entry.destroy()
                try:
                    self.refresh_weapon_limit_diff_display()
                except Exception as e:
                    self._warn(e)
        edit_entry.bind('<Return>', save_edit)
        edit_entry.bind('<FocusOut>', save_edit)

    def mass_edit_weapon_stats(self, mode):
        """Mass-edit weapon stat columns according to mode: 'own_all'/'sudo_max' mark owned; 'poverty' unowns. Skip protected IDs for 'own_all'; for 'poverty', protected IDs keep owned/normal condition with stats set to 4."""
        if not hasattr(self, 'weapon_data') or not hasattr(self, 'tree'):
            return
        # Protected IDs are per-game; EDF4.1/EDF5 start with no protection until real starter/DLC-locked ids are supplied.
        current_game = getattr(self, 'current_game', 'EDF6')
        if _game_is_edf41(current_game):
            protected_ids, protected_ranges = EDF41_PROTECTED_IDS, EDF41_PROTECTED_RANGES
        elif _game_is_edf5(current_game):
            protected_ids, protected_ranges = EDF5_PROTECTED_IDS, EDF5_PROTECTED_RANGES
        else:
            protected_ids, protected_ranges = EDF6_PROTECTED_IDS, EDF6_PROTECTED_RANGES
        def is_protected(wid):
            if wid in protected_ids:
                return True
            for a,b in protected_ranges:
                if a <= wid <= b:
                    return True
            # modded range 1564+ considered editable
            return False
        if mode == 'own_all':
            target = WEAPON_OWNED_CONDITION  # condition/ownership column
            stat_target = 1
        elif mode == 'sudo_max':
            target = WEAPON_OWNED_CONDITION  # condition/ownership column
            stat_target = 8
        elif mode == 'poverty':
            target = 0
            stat_target = 0
            protected_stat = 4  # protected IDs get this stat value under poverty
            protected_avg = WEAPON_OWNED_CONDITION   # protected IDs stay owned/normal under poverty
        else:
            return
        # Apply to weapon_data and update tree rows (skip ID and Name columns)
        for idx, row in enumerate(self.weapon_data):
            try:
                wid = int(row[0])
            except Exception:
                continue
            # For 'own_all' we still skip protected IDs entirely
            if mode == 'own_all' and is_protected(wid):
                continue
            # Prepare working values: prefer tree-display values if available
            values = list(self.tree.item(str(idx), 'values')) if self.tree.exists(str(idx)) else list(row)
            # Ownership/condition handling (column 2 - see WEAPON_OWNED_CONDITION note above)
            try:
                if mode == 'sudo_max':
                    values[2] = WEAPON_OWNED_CONDITION
                elif mode == 'poverty':
                    if is_protected(wid):
                        # Protected IDs stay owned/normal under poverty
                        values[2] = protected_avg
                    else:
                        values[2] = target
                else:
                    # own_all and other modes use the generic target
                    values[2] = target
            except Exception as e:
                self._warn(e)
            # Stats columns (3..10). For poverty protected IDs set to protected_stat; otherwise use stat_target
            for c in range(3, 11):
                try:
                    if mode == 'poverty' and is_protected(wid):
                        values[c] = protected_stat
                    else:
                        values[c] = stat_target
                except Exception as e:
                    self._warn(e)
            # Write back to tree and internal weapon_data
            if self.tree.exists(str(idx)):
                try:
                    self.tree.item(str(idx), values=values)
                except Exception as e:
                    self._warn(e)
            # Update internal weapon_data for persistence
            for c in range(min(len(self.weapon_data[idx]), len(values))):
                self.weapon_data[idx][c] = values[c]
        try:
            self.refresh_weapon_limit_diff_display()
        except Exception as e:
            self._warn(e)
        # Provide a small UI hint
        try:
            self.save_status_label.configure(text=self.tr('mass_edit_done'), text_color='green')
            self.after(2500, lambda: self.save_status_label.configure(text=''))
        except Exception as e:
            self._warn(e)

    # --- Mission Table ---
    def reload_mission_names(self):
        """Reload mission names from disk (exe-adjacent copy if one exists, else the bundled
        resource copy - see resolved_translation_path()) and refresh mission table."""
        try:
            # Preserve existing data as fallback
            current = getattr(self, 'mission_names_data', {})
            self.mission_names_data = load_json_safe(resolved_translation_path('MissionNames.json'), current)
            # Validate current missionlist_key; fallback if missing
            if self.missionlist_key not in self.mission_names_data:
                fallback = self.games_metadata.get(self.current_game, {}).get('missionlist')
                if fallback and fallback in self.mission_names_data:
                    self.missionlist_key = fallback
        except Exception as e:
            self._warn(e)
        # Refresh table if available
        if hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception as e:
                self._warn(e)

    def _apply_mission_class_active_styling(self):
        """(Re)apply the active-class highlight (yellow bg, black text, '(Active)' suffix) to mission_class_labels, reverting every other label to its captured default style. Shared by set_active_mission_class() and refresh_mission_labels() (which resets label text on every language switch and would otherwise wipe the highlight)."""
        defaults = getattr(self, 'mission_class_label_defaults', [])
        for i, lbl in enumerate(getattr(self, 'mission_class_labels', [])):
            try:
                base = self.mission_class_names[i]
                if i == getattr(self, 'active_mission_class', 0):
                    active_text = self.tr('mission_active_suffix', 'Active')
                    lbl.configure(text=f"{base} ({active_text})", fg_color=ACTIVE_HIGHLIGHT_BG, text_color=ACTIVE_HIGHLIGHT_FG)
                else:
                    default_fg, default_text = defaults[i] if i < len(defaults) else ("transparent", None)
                    lbl.configure(text=base, fg_color=default_fg, text_color=default_text)
            except Exception as e:
                self._warn(e)

    def set_active_mission_class(self, idx):
        """Set the active class for the mission sheet and rebuild visible columns."""
        try:
            if not hasattr(self, 'mission_class_names'):
                return
            self.active_mission_class = int(idx) if idx is not None else 0
            self._apply_mission_class_active_styling()
            # Rebuild the sheet headers/columns
            try:
                self.update_mission_sheet_for_class()
            except Exception as e:
                self._warn(e)
        except Exception as e:
            self._warn(e)

    def update_mission_sheet_for_class(self):
        """Rebuild the sheet headers/column metadata to show only the active class."""
        try:
            headers = ["Mission"]
            active_short = self.mission_class_short_names[self.active_mission_class]
            for d in self.mission_diffs_short:
                headers.append(f"{active_short} {d}")
            # Update the sheet headers
            try:
                self.sheet.headers(headers)
            except Exception as e:
                self._warn(e)
            # Recompute columns
            self.sep_cols = []
            self.data_cols = list(range(1, len(self.mission_diffs_short) + 1))
            # Perf: only call readonly_columns() here, not reset_sheet_formatting() too - it already runs once inside update_mission_table() below, so calling it twice was redundant.
            try:
                self.sheet.readonly_columns(columns=[0] + self.sep_cols)
            except Exception as e:
                self._warn(e)

            # Re-read and rewrite every row via update_mission_table() so the grid's actual cell values reflect the newly active class, not just its relabeled headers.
            try:
                self.update_mission_table()
            except Exception as e:
                self._warn(e)

            # Update side Unlock/Reset buttons to reflect active class (label updates); shared widths so the column stays lined up.
            try:
                _unlock_w, _reset_w = self._mission_button_col_widths()
                for di, btn in enumerate(getattr(self, 'active_mission_unlock_buttons', [])):
                    try:
                        dname = self.mission_diffs[di]
                        text = self.tr('unlock_button').format(difficulty=dname)
                        btn.configure(text=text, width=_unlock_w)
                    except Exception as e:
                        self._warn(e)
                for di, btn in enumerate(getattr(self, 'active_mission_reset_buttons', [])):
                    try:
                        dname = self.mission_diffs[di]
                        text = self.tr('reset_button').format(difficulty=dname)
                        btn.configure(text=text, width=_reset_w)
                    except Exception as e:
                        self._warn(e)
                # Clear any stale canvas ghost left behind by the button width changes above.
                self._redraw_mission_btn_scroll()
            except Exception as e:
                self._warn(e)
        except Exception as e:
            self._warn(e)

    def _on_root_configure_resize_sheet(self, event=None):
        """Debounced <Configure> handler bound to the root window: re-run reset_sheet_formatting()
        after a resize/maximize settles, so the Mission Table's Mission column keeps filling the
        real available width instead of only ever being sized for whatever the window measured at
        launch. <Configure> fires on every pixel of a drag (and on child-widget geometry changes
        too, since those bubble as separate events on their own widgets - filtering to `event.widget
        is self` keeps this to genuine root-window resizes/moves only), so this waits for a short
        quiet period rather than reformatting on every single event."""
        if event is not None and event.widget is not self:
            return
        if not hasattr(self, 'sheet'):
            return  # fires during __init__ too, before the Mission Table sheet exists yet
        try:
            if getattr(self, '_sheet_resize_after_id', None) is not None:
                self.after_cancel(self._sheet_resize_after_id)
        except Exception:
            pass
        try:
            self._sheet_resize_after_id = self.after(150, self.reset_sheet_formatting)
        except Exception as e:
            self._warn(e)

    def reset_sheet_formatting(self):
        # Column 0's width is measured from the actual text (rather than a flat 540) to fix both too-wide and too-narrow cases; runs after every set_sheet_data() so it stays correct across page turns, class switches, and language switches.
        name_width = self._fit_mission_name_col_width()
        try:
            row_index_w = self.sheet.ops.default_row_index_width
        except Exception:
            row_index_w = 70
        fixed_width = row_index_w + 66 * len(self.data_cols) + 6 * len(self.sep_cols)
        # Grow the Mission column to fill any leftover width in sheet_container, so the Inferno column's right edge lines up with the container's own right edge instead of leaving a dead grey strip. winfo_width() returns 1 before the window's first real draw - harmless no-op then, self-corrects on the next call (page turn/class switch, or the deferred after() call at the end of __init__).
        try:
            self.sheet_container.update_idletasks()
            avail = self.sheet_container.winfo_width()
            if avail > fixed_width + name_width:
                name_width = avail - fixed_width
        except Exception as e:
            self._warn(e)
        self.sheet.column_width(0, name_width)
        for col in self.data_cols:
            self.sheet.column_width(col, 66)
        # Narrow separators remain small but slightly larger to be visible
        for col in self.sep_cols:
            self.sheet.column_width(col, 6)
        # Highlight columns with class-based colors
        for idx, col in enumerate(self.data_cols):
            d_idx = idx % 5
            self.sheet.highlight_columns(columns=[col], bg=self.colors[d_idx], fg=self.text_colors[d_idx], redraw=False)

        # Alignments
        self.sheet.span(columns=self.data_cols).align("center", redraw=False)
        self.sheet.span(columns=[0]).align("w", redraw=False)
        self.sheet.span(header=True).align("center", redraw=True)

        # Size the Sheet widget itself to exactly match the summed column widths, which is what actually eliminates the dead gap rather than just shrinking columns inside a still-too-wide widget.
        total_width = fixed_width + name_width
        try:
            self.sheet.configure(width=total_width)
        except Exception as e:
            self._warn(e)

    def toggle_mission_cell(self, event=None):
        selected = self.sheet.get_currently_selected()
        if not selected or selected.column == 0:
            return
        r, c = selected.row, selected.column  # 0-based
        if c in self.sep_cols:
            return
        logical_idx = self.data_cols.index(c)
        cl_idx = self.active_mission_class
        d_idx = logical_idx
        miss_idx = (self.current_page - 1) * self.missions_per_page + r
        arr = self.mission_arrays[cl_idx]
        bit = DIFFICULTY_BITS[d_idx]
        current = "Y" if (arr[miss_idx] & bit) else "N"
        new = "N" if current == "Y" else "Y"
        self.sheet.set_cell_data(r, c, new, redraw=True)  # Update sheet
        if new == "Y":
            arr[miss_idx] |= bit
        else:
            arr[miss_idx] &= ~bit
        self.update_completion()

    def on_cell_edit(self, event=None):
        selected = self.sheet.get_currently_selected()
        if not selected or selected.column == 0:
            return
        r, c = selected.row, selected.column  # 0-based
        if c in self.sep_cols:
            return
        logical_idx = self.data_cols.index(c)
        cl_idx = self.active_mission_class
        d_idx = logical_idx
        miss_idx = (self.current_page - 1) * self.missions_per_page + r
        arr = self.mission_arrays[cl_idx]
        bit = DIFFICULTY_BITS[d_idx]
        new_value = self.sheet.get_cell_data(r, c)
        if new_value.upper() == "Y":
            arr[miss_idx] |= bit
        elif new_value.upper() == "N":
            arr[miss_idx] &= ~bit
        self.update_completion()

    def _recompute_total_pages(self):
        """Ceiling-divide total_missions by missions_per_page, factored out of the 3 call sites that change total_missions so the pagination math lives in one place."""
        if self.total_missions <= 0:
            return 1
        return (self.total_missions + self.missions_per_page - 1) // self.missions_per_page

    def _punch_mission_bits(self, cl_idx, mission_indices, mask, set_bits=True):
        """Apply (set_bits=True) or clear (set_bits=False) exactly the difficulty bits in `mask` for the given 0-based mission indices, generalizing the punch-hole pattern toggle_mission_cell uses so unlock_mission/reset_mission/unlock_defined_missions share one implementation."""
        arr = self.mission_arrays[cl_idx]
        for idx in mission_indices:
            if 0 <= idx < len(arr):
                if set_bits:
                    arr[idx] |= mask
                else:
                    arr[idx] &= ~mask

    def unlock_mission(self, cl_idx, d_idx):
        self._punch_mission_bits(cl_idx, range(self.total_missions), DIFFICULTY_BITS[d_idx], set_bits=True)
        self.update_mission_table()
        self.update_completion()

    def reset_mission(self, cl_idx, d_idx):
        self._punch_mission_bits(cl_idx, range(self.total_missions), DIFFICULTY_BITS[d_idx], set_bits=False)
        self.update_mission_table()
        self.update_completion()

    def _parse_mission_list_text(self, text):
        """Parse a user-typed mission list ("1, 5, 10-15") into a sorted list of unique 0-based mission indices, clamped to total_missions. Whitespace is ignored, ';' treated as ',', reversed ranges normalized, and unparseable chunks silently skipped so a typo doesn't nuke the whole list."""
        indices = set()
        if not text:
            return []
        for chunk in text.replace(';', ',').split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            if '-' in chunk:
                start_s, _, end_s = chunk.partition('-')
                try:
                    start, end = int(start_s.strip()), int(end_s.strip())
                except ValueError:
                    continue
                if start > end:
                    start, end = end, start
                mission_ids = range(start, end + 1)
            else:
                try:
                    mission_ids = [int(chunk)]
                except ValueError:
                    continue
            for mid in mission_ids:
                idx = mid - 1
                if 0 <= idx < self.total_missions:
                    indices.add(idx)
        return sorted(indices)

    def _boring_missions_mask_from_ui(self):
        """Bitmask built from the Boring Missions difficulty checkboxes - falls back to "all
        five difficulties" (the old hardcoded behavior) if the checkboxes don't exist yet."""
        if not getattr(self, 'boring_diff_vars', None):
            return sum(DIFFICULTY_BITS)
        mask = 0
        for var, bit in zip(self.boring_diff_vars, DIFFICULTY_BITS):
            if var.get():
                mask |= bit
        return mask

    def on_boring_missions_changed(self):
        """Called when the Boring Missions text field is committed (Enter/focus-out) or a
        checkbox is toggled - just persists the new state, it doesn't unlock anything by
        itself (that still only happens on the button click, same as before)."""
        try:
            game_key = self.game_var.get() if hasattr(self, 'game_var') else self.current_game
            text = self.boring_missions_var.get().strip() if hasattr(self, 'boring_missions_var') else ''
            self.save_boring_missions_config(game_key, text)
        except Exception as e:
            self._warn(e)

    def save_boring_missions_config(self, game_key, text):
        """Persist the current Boring Missions text/checkbox state for `game_key` into
        config.json, so it survives a restart the same way modded_mission_totals does."""
        entry = self.config_data.setdefault('boring_missions', {})
        entry[game_key] = {
            'missions': text or '',
            'diffs': [bool(v.get()) for v in getattr(self, 'boring_diff_vars', [])],
            'classes': [bool(v.get()) for v in getattr(self, 'boring_class_vars', [])],
        }
        self.save_config()

    def refresh_boring_missions_field(self):
        """Repopulate the Boring Missions text field/checkboxes for the currently selected game: the user's saved list if customized, otherwise games_metadata's auto_unlock_missions rendered as editable text."""
        if not hasattr(self, 'boring_missions_var'):
            return
        game_key = self.game_var.get() if hasattr(self, 'game_var') else self.current_game
        saved = self.config_data.get('boring_missions', {}).get(game_key)
        if saved:
            self.boring_missions_var.set(saved.get('missions', ''))
            diffs = saved.get('diffs') or []
            for i, var in enumerate(getattr(self, 'boring_diff_vars', [])):
                var.set(diffs[i] if i < len(diffs) else True)
            # 'classes' is the current per-class format; 'all_classes' is a one-time migration from the earlier single-checkbox version.
            classes = saved.get('classes')
            if classes is not None:
                for i, var in enumerate(getattr(self, 'boring_class_vars', [])):
                    var.set(classes[i] if i < len(classes) else True)
            elif not saved.get('all_classes', True):
                for var in getattr(self, 'boring_class_vars', []):
                    var.set(True)
        else:
            meta = self.games_metadata.get(game_key, {})
            default_list = meta.get('auto_unlock_missions', [])
            self.boring_missions_var.set(", ".join(str(m) for m in default_list))
            for var in getattr(self, 'boring_diff_vars', []):
                var.set(True)
            for var in getattr(self, 'boring_class_vars', []):
                var.set(True)

    def unlock_defined_missions(self, cl_idx=None, game_key=None):
        """Unlock the current "Boring Missions" list for `game_key`, restricted to the checked difficulty bits and applied to the checked classes (falls back to `cl_idx` if every class checkbox is unchecked). Mission numbers are 1-based."""
        try:
            if game_key is None:
                game_key = self.game_var.get() if hasattr(self, 'game_var') else self.current_game
            text = self.boring_missions_var.get().strip() if hasattr(self, 'boring_missions_var') else ''
            if text:
                mission_indices = self._parse_mission_list_text(text)
            else:
                meta = self.games_metadata.get(game_key, {})
                mission_indices = [idx for idx in (int(mid) - 1 for mid in meta.get('auto_unlock_missions', []))
                                    if 0 <= idx < self.total_missions]
            if not mission_indices:
                return False
            class_vars = getattr(self, 'boring_class_vars', [])
            classes_to_apply = [i for i, var in enumerate(class_vars) if var.get()]
            if not classes_to_apply:
                classes_to_apply = [int(cl_idx)] if cl_idx is not None else list(range(4))
            mask = self._boring_missions_mask_from_ui()
            for c in classes_to_apply:
                self._punch_mission_bits(c, mission_indices, mask, set_bits=True)
            # Refresh UI
            try: self.update_mission_table()
            except Exception as e:
                self._warn(e)
            try: self.update_completion()
            except Exception as e:
                self._warn(e)
            # Persist whatever's currently in the field/checkboxes, same as an explicit Enter/focus-out would.
            try: self.save_boring_missions_config(game_key, text)
            except Exception as e:
                self._warn(e)
            return True
        except Exception as e:
            self._warn(e)
            return False

    def on_unlock_defined_click(self):
        """UI handler for the "Unlock Boring Missions" button: unlocks the custom Boring Missions list for the checked classes (falling back to the active class if none are checked)."""
        try:
            self.unlock_defined_missions(cl_idx=self.active_mission_class, game_key=self.game_var.get() if hasattr(self, 'game_var') else None)
        except Exception as e:
            self._warn(e)

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            if hasattr(self, 'page_label'):
                self.page_label.configure(text=self.tr('page_label').format(current=self.current_page, total=self.total_pages))
            self.update_mission_table()

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            if hasattr(self, 'page_label'):
                self.page_label.configure(text=self.tr('page_label').format(current=self.current_page, total=self.total_pages))
            self.update_mission_table()

    def update_mission_table(self):
        start = (self.current_page - 1) * self.missions_per_page
        end = min(start + self.missions_per_page, self.total_missions)
        data = []
        # Replaced file read with in-memory mission_names_data to keep data synchronized
        mission_key = self.missionlist_key
        lang = self.current_language
        mission_langs = self.mission_names_data.get(mission_key, {})
        if lang in mission_langs:
            self.mission_names = mission_langs[lang]
        elif 'en' in mission_langs:
            self.mission_names = mission_langs['en']
        else:
            self.mission_names = {}
        # Use translated header for "Mission" column and for class/difficulty short names
        active_short = self.mission_class_short_names[self.active_mission_class]
        diffs_short = self.mission_diffs_short
        headers = [self.tr('mission_table_col_mission')]
        for d in diffs_short:
            headers.append(f"{active_short} {d}")
        self.sheet.headers(headers)
        for m in range(start, end):
            name = self.mission_names.get(str(m+1), f"Mission {m+1}")
            row = [f"{m+1}: {name}"]
            cl_idx = self.active_mission_class
            for d_idx in range(5):
                bit = DIFFICULTY_BITS[d_idx]
                yn_yes = self.tr('mission_table_cell_yes')
                yn_no = self.tr('mission_table_cell_no')
                row.append(yn_yes if (self.mission_arrays[cl_idx][m] & bit) else yn_no)
            data.append(row)
        # Perf: redraw=False here since reset_sheet_formatting() and the explicit redraw(True) below still need to run after the data is set anyway, avoiding a wasted repaint of the pre-formatting state.
        self.sheet.set_sheet_data(data, redraw=False, reset_row_positions=True)
        self.reset_sheet_formatting()
        self.sheet.redraw(True)

    def update_completion(self):
        """Recalculate and display overall mission completion and auto-sync conquest achievements."""
        self.total_possible = self.total_missions * 20
        total = 0
        for arr in self.mission_arrays:
            for byte in arr[:self.total_missions]:
                total += bin(byte & 0x1F).count('1')
        percent = (total / self.total_possible) * 100 if self.total_possible else 0.0
        # completion_label uses the '{max}' placeholder so the denominator is correct for any game/DLC's mission count, not a hardcoded literal.
        pattern = self.tr('completion_label')
        try:
            text = pattern.format(percent=percent, total=total, max=self.total_possible)
        except Exception:
            text = f"Completion: {percent:.2f}% ({total}/{self.total_possible})"
        if hasattr(self, 'completion_label'):
            self.completion_label.configure(text=text)
        # Update conquest achievements - EDF6/EDF5 only. EDF4.1's achievement_data holds
        # compute_edf41_achievement_status()'s real, counter-derived rows (51 of them, no Conquest%
        # concept at all) - indexing into it with this percentages/32-row model would silently
        # corrupt those rows' unlocked flags, so skip entirely for that game.
        updated = False
        if not _game_is_edf41(getattr(self, 'current_game', 'EDF6')):
            percentages = list(range(5, 65, 5)) + list(range(62, 102, 2))
            for i, perc in enumerate(percentages):
                achieved = percent >= perc
                if achieved and self.achievement_data[i][2] == 0:
                    self.achievement_data[i][2] = 1
                    updated = True
                elif (not achieved) and self.achievement_data[i][2] == 1:
                    self.achievement_data[i][2] = 0
                    updated = True
        if updated and hasattr(self, 'update_achievement_table'):
            try:
                self.update_achievement_table()
            except Exception as e:
                self._warn(e)

    # --- Achievements ---
    def on_achievement_cell_double_click(self, event=None):
        """Toggle the Unlocked column (index 1; Name is 0, ID was dropped) between Yes/No on double-click, same interaction as the mission table's Y/N cells. EDF4.1 skips this entirely - its achievement_data holds status DERIVED from the real counters (compute_edf41_achievement_status), not a separate stored flag, so there's nothing to toggle; the table is read-only for that game."""
        if _game_is_edf41(getattr(self, 'current_game', 'EDF6')):
            return
        if not hasattr(self, 'ach_sheet'):
            return
        selected = self.ach_sheet.get_currently_selected()
        if not selected or selected.column != 1:
            return
        r = selected.row
        if r < 0 or r >= len(self.achievement_data):
            return
        yn_yes = self.tr('mission_table_cell_yes')
        yn_no = self.tr('mission_table_cell_no')
        old_value = self.ach_sheet.get_cell_data(r, 1)
        new_value = yn_no if old_value == yn_yes else yn_yes
        self.ach_sheet.set_cell_data(r, 1, new_value, redraw=True)
        self.achievement_data[r][2] = 1 if new_value == yn_yes else 0  # [2] = achievement_data's own unlocked field, not a sheet column index

    def _format_edf41_achievement_progress(self, current, threshold, vtype):
        """'150/500' for int counters, '0.75/1.00' (2dp) for float ratios/armor - matches how each field naturally reads rather than a one-size-fits-all format."""
        if vtype == 'float':
            return f"{float(current):.2f}/{float(threshold):.2f}"
        try:
            return f"{int(current)}/{int(threshold)}"
        except (TypeError, ValueError):
            return f"{current}/{threshold}"

    def update_achievement_table(self):
        is_edf41 = _game_is_edf41(getattr(self, 'current_game', 'EDF6'))
        yn_yes = self.tr('mission_table_cell_yes')
        yn_no = self.tr('mission_table_cell_no')
        if not is_edf41:
            # Use translated achievement names for both progress and other achievements
            trans = self._trans_dict()
            percentages = list(range(5, 65, 5)) + list(range(62, 102, 2))
            # Progress achievements
            for i in range(32):
                perc = percentages[i]
                # Use the template key for progress achievements
                template = self.tr("achievement_conquest_x")
                name = template.replace("{perc}", str(perc))
                self.achievement_data[i][1] = name
            # Other achievements
            other_keys = [
                "achievement_rescue_5",
                "achievement_rescue_50",
                "achievement_medic",
                "achievement_master_ranger",
                "achievement_master_diver",
                "achievement_master_airraider",
                "achievement_master_fencer"
            ]
            for i, key in enumerate(other_keys):
                idx = 32 + i
                name = trans.get(key, self.achievement_data[idx][1])
                self.achievement_data[idx][1] = name
        # Update table
        if hasattr(self, 'ach_sheet'):
            if is_edf41:
                # EDF4.1 rows carry extra progress fields (compute_edf41_achievement_status):
                # [id, name, unlocked, current, threshold, vtype]. Show real progress instead of a
                # bare No, since these are real EDF4.1 Steam achievement names (typos included -
                # "RangerNromalClear" is the game's own data), not the EDF6 Conquest% model.
                # Defensive len(row)>=6 check: if the game selector switched to EDF4.1 before any
                # save was loaded, self.achievement_data is still __init__'s EDF6-shaped 3-field
                # placeholder rows - fall back to a plain Yes/No rather than an IndexError.
                rows = []
                for row in self.achievement_data:
                    if row[2]:
                        status = yn_yes
                    elif len(row) >= 6:
                        progress = self._format_edf41_achievement_progress(row[3], row[4], row[5])
                        status = f"{yn_no} ({progress})"
                    else:
                        status = yn_no
                    rows.append([row[1], status])
            else:
                # row[0] (ID) intentionally dropped - it always equals the row's list index, duplicating tksheet's built-in row-index gutter.
                rows = [[row[1], yn_yes if row[2] else yn_no] for row in self.achievement_data]
            self.ach_sheet.set_sheet_data(rows, redraw=False)
            self.ach_sheet.headers([
                self.tr('achievement_table_col_name'),
                self.tr('achievement_table_col_unlocked'),
            ])
            # Re-applied here since set_sheet_data() above is what makes these stick (the columns had 0 rows the first time column_width() ran at init). Name gets the lion's share of the width since achievement names run long; EDF4.1's Unlocked column is widened to fit "No (150/500)"-style progress text (floats capped to 2 decimals by _format_edf41_achievement_progress, so it never needs more than this). Non-EDF4.1 Unlocked only ever holds "Yes"/"No".
            self.ach_sheet.column_width(0, 430 if is_edf41 else 515, redraw=False)
            self.ach_sheet.column_width(1, 150 if is_edf41 else 65, redraw=False)
            self.ach_sheet.redraw(True)
        self.update_kill_fields()
        # Update achievement tab title and box label
        if hasattr(self, 'achievements_section_button'):
            self.achievements_section_button.configure(text=self.tr('achievements_section') + (" ▼" if self.achievement_content.winfo_ismapped() else " ▶"))
        if hasattr(self, 'achievements_box_label'):
            try: self.achievements_box_label.configure(text=self.tr('achievements_box_label'))
            except Exception as e:
                self._warn(e)

    def rebuild_kill_sheet_for_game(self):
        """(Re)build self.kill_field_keys and the Kill Statistics sheet's rows (not just their text) for self.current_game, since each game has its own real field list/count, unlike a plain language-switch relabel. No-ops if the table is already identical, so safe to call liberally."""
        if not hasattr(self, 'kill_sheet'):
            return
        game = getattr(self, 'current_game', 'EDF6')
        table = get_kill_fields_table(game)
        new_keys = [entry[2] for entry in table]
        if new_keys == getattr(self, 'kill_field_keys', None):
            return
        self.kill_field_keys = new_keys
        trans = self._trans_dict()
        # trans carries each game's real, shipped Battle-History labels under a GAME-PREFIXED key
        # (EDF6_.../EDF41_..., see kill_stat_lang_prefix()) - added to languages.json 2026-09-08 for
        # all 5 app languages (EDF6) and en/ja (EDF4.1, the only 2 languages with genuine distinct
        # source data - EDF4.1's own "CN" TEXTTABLE turned out to be a byte-identical copy of its
        # JP one, not real Chinese text, so excluded). Deliberately NOT a shared flat key: EDF6 and
        # EDF4.1 reuse the same internal Achievement.sgo field name for DIFFERENT real things for 13
        # different fields (e.g. 'DragonKillCount' is "Tadpoles Defeated" in EDF6 but "Dragons
        # Defeated" in EDF4.1) - a flat namespace would silently show the wrong game's label. EDF5
        # has no real-name source of its own yet, so it currently always falls through to
        # real_field_display_name()'s humanize_field_key() guess (not EDF6's data - a shared-name
        # field could just as easily diverge for EDF5 the same way it did for EDF4.1).
        if new_keys:
            prefix = kill_stat_lang_prefix(game)
            data = [[trans.get(f'{prefix}{key}', real_field_display_name(key, game)), "0"] for key in new_keys]
        else:
            # EDF4.1 has no kill fields RE'd yet - show one explanatory row rather than an empty table or silently mislabeled EDF6/EDF5 offsets.
            data = [[self.tr('kill_table_unavailable', "Not yet available for this game"), ""]]
        self.kill_sheet.set_sheet_data(data, redraw=False)
        # Re-applied here since set_sheet_data() above is what makes these stick (same tksheet
        # quirk as ach_sheet's widths below) - Stat gets most of the width, Count only ever holds a
        # short int or "NN.NN%" string.
        self.kill_sheet.column_width(0, 400, redraw=False)
        self.kill_sheet.column_width(1, 70, redraw=False)
        self.kill_sheet.redraw(True)

    def update_kill_fields(self):
        # Refresh every row from self.kill_fields, defaulting to 0 so the panel renders before a save is loaded; rebuilds the sheet's rows for the current game first (no-op if unchanged).
        if not hasattr(self, 'kill_sheet'):
            return
        self.rebuild_kill_sheet_for_game()
        if not self.kill_field_keys:
            return
        kill_fields = getattr(self, 'kill_fields', {})
        game = getattr(self, 'current_game', 'EDF6')
        # *ClearRatio fields are always computed live from the Mission Table, never read as raw
        # TROPHY.DAT bytes - see compute_clear_ratios()'s module comment in EDFSaveEditorLogic.py.
        clear_ratios = compute_clear_ratios(getattr(self, 'mission_arrays', None), getattr(self, 'total_missions', 0), game)
        for r, key in enumerate(self.kill_field_keys):
            if key in clear_ratios:
                # Shown as a percentage ("58.50%"), never the bare scaled int/float - a raw "10000"
                # reads as ten thousand kills to a user, not 100.00% (see format_clear_ratio_display()).
                cell_text = format_clear_ratio_display(key, clear_ratios[key], game)
            else:
                cell_text = str(kill_fields.get(key, 0))
            self.kill_sheet.set_cell_data(r, 1, cell_text, redraw=False)
        self.kill_sheet.redraw(True)

    def on_kill_cell_edit(self, event=None):
        """Commit an edited Count cell into self.kill_fields (written to TROPHY.DAT on Save). Values are signed 32-bit little-endian, confirmed against a real save with a negative/overflowed counter, so both the clamp range and invalid-input fallback allow negative values."""
        if not hasattr(self, 'kill_sheet'):
            return
        selected = self.kill_sheet.get_currently_selected()
        if not selected or selected.column != 1:
            return
        r = selected.row
        if r < 0 or r >= len(self.kill_field_keys):
            return
        key = self.kill_field_keys[r]
        if is_clear_ratio_key(key):
            # *ClearRatio cells are always computed from the Mission Table, never a stored counter
            # (see compute_clear_ratios()'s module comment in EDFSaveEditorLogic.py) - revert any
            # typed edit rather than let it write into a byte offset that doesn't mean what it says.
            self.update_kill_fields()
            return
        raw = self.kill_sheet.get_cell_data(r, 1)
        try:
            val = int(str(raw).strip())
            val = max(-2147483648, min(2147483647, val))
        except (TypeError, ValueError):
            val = getattr(self, 'kill_fields', {}).get(key, 0)
        self.kill_sheet.set_cell_data(r, 1, str(val), redraw=True)
        if not hasattr(self, 'kill_fields'):
            self.kill_fields = {}
        self.kill_fields[key] = val

    # --- Color Customization ---
    def _sample_ctk_default_colors(self, parent):
        """Builds one throwaway CTkFrame/CTkLabel/CTkEntry/CTkButton, reads back their resolved
        default colors for the CURRENT appearance mode (Light/Dark), then destroys them. Used to
        style the plain-tk parts of the swatch grid (see _build_color_grid) so they match this
        install's actual dark-blue theme instead of a hardcoded guess - re-called on every theme
        toggle (see _restyle_color_grid) since Light/Dark resolve to different colors.
        Measured ~50x cheaper than the ~260 real grid widgets would cost since only 4 throwaway
        widgets are built here, not 260."""
        mode_is_dark = (ctk.get_appearance_mode() == "Dark")

        def resolve(value):
            if isinstance(value, (list, tuple)) and len(value) == 2:
                return value[1] if mode_is_dark else value[0]
            return value

        probe = ctk.CTkFrame(parent)
        lbl = ctk.CTkLabel(probe, text="")
        entry = ctk.CTkEntry(probe)
        btn = ctk.CTkButton(probe, text="")
        optmenu = ctk.CTkOptionMenu(probe, values=[""])
        colors = {
            'row_bg': resolve(probe.cget("fg_color")),
            'label_fg': resolve(lbl.cget("text_color")),
            'entry_bg': resolve(entry.cget("fg_color")),
            'entry_fg': resolve(entry.cget("text_color")),
            'entry_border': resolve(entry.cget("border_color")),
            # Added for the Key Config controller-mode dropdown (see rebuild_keyconfig_rows) -
            # its plain tk.OptionMenu wants a flat bg/hover/text triple rather than CTk's separate
            # fg_color/button_color split, so CTkOptionMenu's own fg_color stands in for both.
            'optionmenu_bg': resolve(optmenu.cget("fg_color")),
            'optionmenu_hover': resolve(optmenu.cget("button_hover_color")),
            'optionmenu_text': resolve(optmenu.cget("text_color")),
        }
        probe.destroy()
        return colors

    def _build_color_grid(self):
        """Lazily builds the Color Customization swatch grid the first time the section is
        expanded - see the self._color_grid_built comment in __init__ for why this isn't built
        during app startup. Safe to call more than once; only the first call does anything.

        PERF: measured on real hardware, the original all-CTk grid took ~2074ms to construct
        (each CTkFrame/CTkLabel/CTkEntry draws itself via an internal canvas - rounded corners,
        per-widget appearance-mode tracking - which is inherently expensive at ~260 widgets; this
        is a known customtkinter limitation at high widget counts, not something a code-level
        micro-fix can patch away). The row frames, index/R-G-B-A labels, the preview swatch, and
        the entries are now plain tk widgets instead (~783ms - the CTkButton "Pick" buttons are
        kept as CTk deliberately, to keep their rounded/blue look consistent with the rest of the
        app, at the cost of some of the possible speedup - see the conversation this was decided
        in for the other options considered: plain-tk-only measured ~427ms, ttk ~645ms).
        Colors for the plain-tk parts are sampled live from the real theme (_sample_ctk_default_colors)
        rather than hardcoded, and kept in sync across Light/Dark toggles by _restyle_color_grid()."""
        if self._color_grid_built:
            return
        palette = self._sample_ctk_default_colors(self.color_content)
        self._color_grid_palette = palette

        columns_frame = ctk.CTkFrame(self.color_content, fg_color="transparent")
        columns_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        columns_frame.grid_columnconfigure((0, 1), weight=1)

        column_titles = {
            False: self.tr('color_primary_header'),
            True: self.tr('color_secondary_header'),
        }
        for col, is_secondary in enumerate((False, True)):
            column = ctk.CTkFrame(columns_frame)
            column.grid(row=0, column=col, padx=(0 if col == 0 else 6, 6 if col == 0 else 0), sticky="nsew")

            col_title_lbl = ctk.CTkLabel(column, text=column_titles[is_secondary], font=(FONT_FAMILY, HEADER_FONT_SIZE, "bold"))
            col_title_lbl.translation_key = 'color_secondary_header' if is_secondary else 'color_primary_header'
            col_title_lbl.pack(anchor="w", padx=6, pady=(4, 2))
            self.color_column_title_widgets[is_secondary] = col_title_lbl

            swatch_row = ctk.CTkFrame(column)
            swatch_row.pack(fill="x", padx=6, pady=(0, 4))
            swatch_lbl = ctk.CTkLabel(swatch_row, text=self.tr('color_swatch_id_label'), font=(FONT_FAMILY, BASE_FONT_SIZE))
            swatch_lbl.translation_key = 'color_swatch_id_label'
            swatch_lbl.pack(side="left", padx=(0, 6))
            self.color_swatch_id_label_widgets[is_secondary] = swatch_lbl
            swatch_selector = ctk.CTkSegmentedButton(
                swatch_row, values=[str(i) for i in range(12)], width=400,
                command=lambda v, sec=is_secondary: self._highlight_active_swatch_row(sec),
            )
            swatch_selector.set("0")
            swatch_selector.pack(side="left", fill="x", expand=True)
            self.color_swatch_id_entries[is_secondary] = swatch_selector

            for i in range(12):
                # Plain tk.Frame, not CTkFrame - see this method's docstring. highlightthickness=0
                # everywhere non-interactive so no stray keyboard-focus ring can ever show (CTk
                # widgets suppress this by default; plain tk doesn't unless told to).
                row = tk.Frame(column, bg=palette['row_bg'], highlightthickness=0)
                row.pack(fill="x", pady=1, padx=4)
                index_lbl = tk.Label(row, text=f"{i}:", width=3, font=(FONT_FAMILY, BASE_FONT_SIZE),
                                      bg=palette['row_bg'], fg=palette['label_fg'], highlightthickness=0)
                index_lbl.pack(side="left", padx=(2, 1))
                # Frame (not Label) for the preview swatch so width/height are real pixels, matching
                # the original CTkLabel's fixed 20x18px look. Its color is always the actual R/G/B
                # value (see update_color_preview), never the theme palette - untouched by restyle.
                preview = tk.Frame(row, width=20, height=18, bg="#000000", highlightthickness=0)
                preview.pack(side="left", padx=2)
                entries = {}
                comp_labels = []
                for comp in ("R", "G", "B", "A"):
                    comp_lbl = tk.Label(row, text=comp, font=(FONT_FAMILY, BASE_FONT_SIZE),
                                         bg=palette['row_bg'], fg=palette['label_fg'], highlightthickness=0)
                    comp_lbl.pack(side="left", padx=(4, 1))
                    comp_labels.append(comp_lbl)
                    e = tk.Entry(row, width=10, font=(FONT_FAMILY, BASE_FONT_SIZE),
                                 bg=palette['entry_bg'], fg=palette['entry_fg'], insertbackground=palette['entry_fg'],
                                 relief="flat", highlightthickness=1,
                                 highlightbackground=palette['entry_border'], highlightcolor=palette['entry_border'])
                    e.insert(0, "0.0")
                    # fill/expand: was a fixed 96px each, leaving a wide dead strip past the Pick
                    # button whenever the column was wider than the row's fixed-width content (the
                    # R/G/B/A boxes are the only elements here that make sense to grow - the index
                    # label/color preview/Pick button all stay their natural fixed size). Now the
                    # four entries share whatever width is actually left in the row.
                    e.pack(side="left", padx=(0, 2), fill="x", expand=True)
                    e.bind("<KeyRelease>", lambda ev, idx=i, sec=is_secondary: self.update_color_preview(sec, idx))
                    entries[comp] = e
                # Pick stays a CTkButton deliberately - see this method's docstring.
                pick_btn = ctk.CTkButton(row, text=self.tr('color_pick_button'), width=110, command=lambda idx=i, sec=is_secondary: self.pick_color(sec, idx))
                pick_btn.pack(side="left", padx=(4, 2))
                # index_lbl/comp_labels kept so _highlight_active_swatch_row() can also flip their
                # bg+text color to the active-row highlight - a bright yellow row background with
                # the theme's normal (light) label text on top would be low-contrast/hard to read
                # otherwise. Plain tk.Label needs BOTH bg and fg set explicitly here (unlike the
                # CTkLabel this replaced, which defaulted to a transparent fg_color and let
                # whatever was drawn behind it show through) - see _set_swatch_row_style.
                self.color_palette_rows[is_secondary].append({"entries": entries, "preview": preview, "pick_btn": pick_btn, "row": row, "index_lbl": index_lbl, "comp_labels": comp_labels})  # pick_btn kept so refresh_color_labels() can retranslate it

        self.color_palette_row_default_fg = palette['row_bg']
        self.color_palette_row_default_text = palette['label_fg']

        # Swatch 0 is selected by default in both columns (swatch_selector.set("0") above) - reflect that in the row highlight from the start rather than leaving every row unhighlighted until the user first clicks a swatch ID.
        for is_secondary in (False, True):
            try: self._highlight_active_swatch_row(is_secondary)
            except Exception as e:
                self._warn(e)

        self._color_grid_built = True
        # A save may already have been loaded (populating app.color_data) before this section was
        # ever expanded - refresh_color_panel() no-ops while _color_grid_built is False (see its
        # guard), so it never got a chance to populate these widgets with the real data. Do that
        # now instead of leaving the freshly-built grid showing construction-time 0.0 defaults.
        if hasattr(self, 'color_data'):
            self.load_color_group_into_ui(self.color_current_key)

    def _restyle_color_grid(self, appearance_mode=None):
        """Re-applies the Light/Dark theme's colors to the plain-tk parts of the swatch grid
        (row frames, index/R-G-B-A labels, entries) on a theme toggle - plain tk widgets don't
        auto-restyle on ctk.set_appearance_mode() the way CTk widgets do, same reasoning as the
        existing _restyle_tksheet_tables() for the Mission/Achievements/Kill tables. No-ops if the
        grid hasn't been built yet (nothing to restyle) - it'll pick up the current mode's colors
        whenever _build_color_grid() does eventually run. The preview swatches are left alone -
        their color is always the actual R/G/B value, not theme styling."""
        # getattr, not a direct attribute access: this runs from update_tree_style(), which is
        # also called once during __init__ (to apply the initial theme) BEFORE self._color_grid_built
        # is even declared - a direct self._color_grid_built access there raises AttributeError
        # ('_tkinter.tkapp' object has no attribute '_color_grid_built'), caught by the caller's
        # try/except and printed as a harmless-but-noisy startup [WARN]. Same reasoning as the
        # existing getattr guards in flush_color_ui_to_cache()/refresh_color_panel().
        if not getattr(self, '_color_grid_built', False):
            return
        palette = self._sample_ctk_default_colors(self.color_content)
        self._color_grid_palette = palette
        self.color_palette_row_default_fg = palette['row_bg']
        self.color_palette_row_default_text = palette['label_fg']
        for is_secondary in (False, True):
            active_idx = self._color_active_row_idx.get(is_secondary) if hasattr(self, '_color_active_row_idx') else None
            for i, row in enumerate(self.color_palette_rows.get(is_secondary, [])):
                try:
                    is_active = (i == active_idx)
                    self._set_swatch_row_style(row, is_active, palette['row_bg'], palette['label_fg'])
                    for e in row["entries"].values():
                        e.configure(bg=palette['entry_bg'], fg=palette['entry_fg'], insertbackground=palette['entry_fg'],
                                    highlightbackground=palette['entry_border'], highlightcolor=palette['entry_border'])
                except Exception as e:
                    self._warn(e)

    def _color_key_from_selectors(self):
        """Returns (class_idx, tier_idx); Primary and Secondary are both shown at once, so the selector only picks the class/tier pair."""
        class_idx = COLOR_CLASSES.index(self.color_class_var.get())
        tier_idx = COLOR_TIERS.index(self.color_tier_var.get())
        return (class_idx, tier_idx)

    def flush_color_ui_to_cache(self):
        """Read both columns' 12 palette rows + swatch ID fields and write them into app.color_data for both slots. Called before switching groups and before saving, so in-progress edits are never lost."""
        if not hasattr(self, 'color_data') or not getattr(self, '_color_grid_built', False):
            return
        class_idx, tier_idx = self.color_current_key
        for is_secondary in (False, True):
            rows = self.color_palette_rows.get(is_secondary, [])
            palettes = []
            for row in rows:
                vals = []
                for comp in ("R", "G", "B", "A"):
                    try:
                        vals.append(float(row["entries"][comp].get()))
                    except ValueError:
                        vals.append(0.0)
                palettes.append(tuple(vals))
            swatch_selector = self.color_swatch_id_entries.get(is_secondary)
            try:
                swatch_id = int(swatch_selector.get()) if swatch_selector else 0
            except ValueError:
                swatch_id = 0
            self.color_data[(class_idx, tier_idx, is_secondary)] = (palettes, swatch_id)

    def load_color_group_into_ui(self, key):
        """Populate both columns' 12 palette rows + swatch ID selector from app.color_data for key = (class_idx, tier_idx). Primary and Secondary can point at different swatches, so each is read/written independently."""
        if not hasattr(self, 'color_data'):
            return
        class_idx, tier_idx = key
        for is_secondary in (False, True):
            full_key = (class_idx, tier_idx, is_secondary)
            if full_key not in self.color_data:
                continue
            palettes, swatch_id = self.color_data[full_key]
            rows = self.color_palette_rows.get(is_secondary, [])
            for i, row in enumerate(rows):
                rgba = palettes[i] if i < len(palettes) else (0.0, 0.0, 0.0, 1.0)
                for comp, v in zip(("R", "G", "B", "A"), rgba):
                    entry = row["entries"][comp]
                    entry.delete(0, "end")
                    entry.insert(0, f"{v:.4f}")
                self.update_color_preview(is_secondary, i)
            swatch_selector = self.color_swatch_id_entries.get(is_secondary)
            if swatch_selector:
                clamped = max(0, min(11, int(swatch_id)))
                try:
                    swatch_selector.set(str(clamped))
                except Exception:
                    pass  # value outside 0-11 (unexpected on real saves) - leave selector as-is
            # swatch_selector.set() above is a programmatic value change, which CTkSegmentedButton
            # does NOT run its `command` callback for (only a real click does) - so the row
            # highlight has to be refreshed explicitly here too, not just left to the callback.
            try: self._highlight_active_swatch_row(is_secondary)
            except Exception as e:
                self._warn(e)

    def _set_swatch_row_style(self, row, is_active, default_fg, default_text):
        """Apply (or revert) the active-row highlight to a single palette row. Split out of
        _highlight_active_swatch_row so that function can touch only the 1-2 rows that actually
        changed instead of all 12 every time - see that function's docstring for why.

        row/index_lbl/comp_labels are plain tk widgets (see _build_color_grid), which paint an
        opaque background rather than the CTkLabel default of a transparent one - so both bg AND
        fg have to be set together here for the labels, not just their text color like the
        original CTk version needed."""
        frame = row.get("row")
        if frame is None:
            return
        try:
            bg = ACTIVE_HIGHLIGHT_BG if is_active else default_fg
            label_color = ACTIVE_HIGHLIGHT_FG if is_active else default_text
            frame.configure(bg=bg)
            index_lbl = row.get("index_lbl")
            if index_lbl is not None and label_color is not None:
                index_lbl.configure(bg=bg, fg=label_color)
            for comp_lbl in row.get("comp_labels", []):
                if label_color is not None:
                    comp_lbl.configure(bg=bg, fg=label_color)
        except Exception as e:
            self._warn(e)

    def _highlight_active_swatch_row(self, is_secondary):
        """Give the palette row matching the current Swatch ID selection the same yellow/black
        'active' highlight used elsewhere in the app (mission class tabs, etc. - ACTIVE_HIGHLIGHT_BG/
        FG), so it's obvious at a glance which of the 12 rows is the one actually equipped/in use,
        not just a small selected-segment highlight up in the ID picker. Reverts every other row to
        its real captured default color (not a hardcoded guess) so this is safe to call repeatedly -
        on init, on every manual swatch-ID click, and after every programmatic load_color_group_into_ui()
        swatch_selector.set() call, since that one doesn't fire the command callback on its own.

        PERF: only the row losing the highlight and the row gaining it are ever touched - this used
        to unconditionally .configure() all 12 rows (6 widgets each) on every Class/Tier switch,
        player toggle, and swatch-ID click (144 .configure() calls across both columns per call,
        every one of them a customtkinter canvas redraw) which is what made this the most sluggish
        tab in the app. self._color_active_row_idx tracks what's currently highlighted per column
        so a call where nothing actually changed (e.g. reloading a group that happens to have the
        same swatch ID selected) does zero widget work instead of 72."""
        selector = self.color_swatch_id_entries.get(is_secondary)
        rows = self.color_palette_rows.get(is_secondary, [])
        if not selector or not rows:
            return
        try:
            active_idx = int(selector.get())
        except (TypeError, ValueError):
            active_idx = 0
        if not hasattr(self, '_color_active_row_idx'):
            self._color_active_row_idx = {}
        previous_idx = self._color_active_row_idx.get(is_secondary)
        if previous_idx == active_idx:
            return  # already correctly highlighted - nothing to redraw
        default_fg = getattr(self, 'color_palette_row_default_fg', 'transparent')
        default_text = getattr(self, 'color_palette_row_default_text', None)
        if previous_idx is not None and 0 <= previous_idx < len(rows):
            self._set_swatch_row_style(rows[previous_idx], False, default_fg, default_text)
        if 0 <= active_idx < len(rows):
            self._set_swatch_row_style(rows[active_idx], True, default_fg, default_text)
        self._color_active_row_idx[is_secondary] = active_idx

    def on_color_selector_display_change(self, which, display_value):
        """Command callback for color_class_menu/color_tier_menu: maps the clicked label back to canonical, updates color_class_var/color_tier_var, then delegates to on_color_selector_changed() for the real class/tier switch."""
        if which == 'class':
            canonical_map = {self._color_class_label(c): c for c in COLOR_CLASSES}
            self.color_class_var.set(canonical_map.get(display_value, display_value))
        else:
            canonical_map = {self._color_tier_label(t): t for t in COLOR_TIERS}
            self.color_tier_var.set(canonical_map.get(display_value, display_value))
        self.on_color_selector_changed()

    def on_color_selector_changed(self):
        """Class/Tier selector changed - flush the outgoing group's edits (both slots) into
        the cache, then load the newly-selected group (both slots) into the UI."""
        if not hasattr(self, 'color_data'):
            return
        self.flush_color_ui_to_cache()
        self.color_current_key = self._color_key_from_selectors()
        self.load_color_group_into_ui(self.color_current_key)

    def toggle_color_player_slot(self):
        """Switch Color Customization between Player 1 and Player 2 (local co-op guest). Both players' full group sets are already loaded eagerly, so this is just a cache swap: flush the outgoing player's edits, swap self.color_data, and reload the currently selected Class/Tier."""
        if not hasattr(self, 'color_data') or not hasattr(self, 'color_data_cache'):
            return
        self.flush_color_ui_to_cache()
        old_slot = getattr(self, 'color_player_slot', 1)
        self.color_data_cache[old_slot] = self.color_data
        new_slot = 2 if old_slot == 1 else 1
        self.color_player_slot = new_slot
        self.color_data = self.color_data_cache.setdefault(new_slot, {})
        self.load_color_group_into_ui(self._color_key_from_selectors())
        if hasattr(self, 'color_player_toggle_btn'):
            self.color_player_toggle_btn.configure(text=self._color_player_toggle_text(new_slot))

    def _color_player_toggle_text(self, slot):
        """Build the 'Editing: Player N (Local Co-op)' toggle button label from translation keys, shared by the initial widget construction and the dynamic relabel in toggle_color_player_slot()."""
        label = self.tr('color_player_editing', 'Editing: Player {slot}').format(slot=slot)
        if slot == 2:
            label += self.tr('color_player_local_coop', ' (Local Co-op)')
        return label

    def refresh_color_panel(self):
        """Called from EDFSaveEditorLogic.load_save_data after app.color_data is populated,
        to show the currently-selected group (defaults to Ranger/Civilian on first load, or
        whatever was selected if a save is reloaded). Both Primary and Secondary are shown."""
        if not getattr(self, '_color_grid_built', False):
            return
        self.color_current_key = self._color_key_from_selectors()
        self.load_color_group_into_ui(self.color_current_key)

    # --- Key Config: Tkinter keysym -> EDF5_KEY_TABLE name, for entries that aren't just the single character itself (single-char keysyms need no entry - see _keyconfig_keysym_to_edf5_name). Anything else has no mapping; start_keyconfig_rebind refuses those rather than guessing. ---
    _TK_KEYSYM_TO_EDF5_NAME = {
        'KP_0': 'Num0', 'KP_1': 'Num1', 'KP_2': 'Num2', 'KP_3': 'Num3', 'KP_4': 'Num4',
        'KP_5': 'Num5', 'KP_6': 'Num6', 'KP_7': 'Num7', 'KP_8': 'Num8', 'KP_9': 'Num9',
        'F1': 'F1', 'F2': 'F2', 'F3': 'F3', 'F4': 'F4', 'F5': 'F5', 'F6': 'F6',
        'F7': 'F7', 'F8': 'F8', 'F9': 'F9', 'F10': 'F10', 'F11': 'F11', 'F12': 'F12',
        'minus': 'Hyphen', 'asciicircum': 'Caret', 'at': 'At',
        'semicolon': 'Semicolon', 'colon': 'Colon',
        'bracketleft': 'BracketsL', 'bracketright': 'BracketsR',
        'comma': 'Comma', 'period': 'Period',
        'Shift_L': 'ShiftL', 'Shift_R': 'ShiftR',
        'Control_L': 'ControlL', 'Control_R': 'ControlR',
        'Alt_L': 'AltL', 'Alt_R': 'AltR',
        'Super_L': 'WinL', 'Super_R': 'WinR', 'Win_L': 'WinL', 'Win_R': 'WinR',
        'Up': 'Up', 'Down': 'Down', 'Left': 'Left', 'Right': 'Right',
        'Return': 'Return', 'space': 'Space', 'BackSpace': 'BackSpace', 'Tab': 'Tab',
        'Insert': 'Insert', 'Delete': 'Delete', 'Home': 'Home', 'End': 'End',
        'Next': 'PageDown', 'Prior': 'PageUp', 'Help': 'Help', 'Escape': 'Escape',
        'Print': 'Print', 'Pause': 'Pause', 'Num_Lock': 'NumLock',
        'KP_Add': 'Add', 'KP_Separator': 'Separator', 'KP_Subtract': 'Subtract',
        'KP_Decimal': 'Decimal', 'KP_Divide': 'Divide',
    }

    def _keyconfig_keysym_to_edf5_name(self, keysym):
        """Translate a Tkinter <KeyPress> event's keysym to an EDF5_KEY_TABLE name, or None if this key isn't in that table at all."""
        if len(keysym) == 1:
            return keysym  # encode_keybind_letter() upper-cases single-char names itself
        return self._TK_KEYSYM_TO_EDF5_NAME.get(keysym)

    def _keyconfig_categories_for_mode(self):
        """Category list for whichever mode is currently selected. Controller mode: just the soldier classes with controller data mapped. Keyboard mode: all 11 categories for both EDF5 and EDF6."""
        game = getattr(self, 'current_game', 'EDF6')
        is_controller = getattr(self, 'keyconfig_mode_var', None) is not None and self.keyconfig_mode_var.get() == "Controller"
        if _game_is_edf41(game):
            # EDF4.1's confirmed categories are "Solder"/"Fencer" for Controller mode, and EDF41_KEYBOARD_CATEGORIES for Keyboard mode; placeholder categories show a "not yet confirmed" row rather than a blank panel.
            if is_controller:
                return ["Solder", "Fencer"]
            return list(EDF41_KEYBOARD_CATEGORIES)
        if is_controller:
            return list((CONTROLLER_ACTIONS_EDF6 if _game_is_edf6(game) else CONTROLLER_ACTIONS).keys())
        return EDF6_KEYCONFIG_CATEGORIES if _game_is_edf6(game) else KEYCONFIG_CATEGORIES

    def refresh_keyconfig_selector_controls(self):
        """Retranslate the Key Config panel's Mode/Category dropdown values on a language switch; category_var stays canonical for lookups, category_display_var is bound to the dropdown."""
        if not hasattr(self, 'keyconfig_category_menu'):
            return
        try:
            if hasattr(self, 'keyconfig_mode_menu'):
                mode_values = [self.tr('keyconfig_mode_keyboard', "Keyboard"), self.tr('keyconfig_mode_controller', "Controller")]
                self.keyconfig_mode_menu.configure(values=mode_values)
                is_controller = self.keyconfig_mode_var.get() == "Controller"
                self.keyconfig_mode_display_var.set(mode_values[1] if is_controller else mode_values[0])
            categories = self._keyconfig_categories_for_mode()
            labels = [self._keyconfig_category_label(c) for c in categories]
            self.keyconfig_category_menu.configure(values=labels)
            self.keyconfig_category_display_var.set(self._keyconfig_category_label(self.keyconfig_category_var.get()))
            if hasattr(self, 'keyconfig_controller_type_menu'):
                self._controller_type_labels = {
                    "xbox": self.tr('keyconfig_controller_type_xbox', "Xbox / Generic"),
                    "ps4": self.tr('keyconfig_controller_type_ps4', "PlayStation"),
                    "switch": self.tr('keyconfig_controller_type_switch', "Switch Pro"),
                }
                self.keyconfig_controller_type_menu.configure(values=list(self._controller_type_labels.values()))
                self.controller_type_display_var.set(self._controller_type_labels[self.controller_type_var.get()])
        except Exception as e:
            self._warn(e)

    def on_keyconfig_mode_display_change(self, display_value):
        """Switch between Keyboard and Controller mode: swaps the Category dropdown's values to match, and resets the selection to that mode's first category if the current one isn't valid there."""
        is_controller = display_value == self.tr('keyconfig_mode_controller', "Controller")
        self.keyconfig_mode_var.set("Controller" if is_controller else "Keyboard")
        categories = self._keyconfig_categories_for_mode()
        self.keyconfig_category_menu.configure(values=[self._keyconfig_category_label(c) for c in categories])
        if self.keyconfig_category_var.get() not in categories:
            self.keyconfig_category_var.set(categories[0])
        self.keyconfig_category_display_var.set(self._keyconfig_category_label(self.keyconfig_category_var.get()))
        self.rebuild_keyconfig_rows()

    def on_keyconfig_category_display_change(self, display_value):
        categories = self._keyconfig_categories_for_mode()
        canonical_map = {self._keyconfig_category_label(c): c for c in categories}
        self.keyconfig_category_var.set(canonical_map.get(display_value, display_value))
        self.rebuild_keyconfig_rows()

    def refresh_keyconfig_panel(self):
        """Called after app.keybind_data/controller_keybind_data are populated (or reset) - (re)builds the currently selected category's rows from scratch, same as a category-dropdown change."""
        self.rebuild_keyconfig_rows()

    def rebuild_keyconfig_rows(self, force=False):
        """(Re)build the row list for whichever category is currently selected. Called on Mode/Category dropdown change and after Load Save. Cancels any in-progress keyboard rebind capture first, since that would otherwise leave a dangling keypress binding pointed at a row that no longer exists.

        Perf note (2026-09-09): refresh_keyconfig_panel() calls this on EVERY Load Save, but the
        game/mode/category/player combo almost never actually changes just because a save was
        (re)loaded - only the underlying keybind_data does. Destroying and recreating every row's
        frame/label/value-widget from scratch on every load was pure waste (same CTk-construction
        cost already proven expensive for the Color Customization grid). So: if the exact same row
        set is still on screen, skip the destroy/rebuild entirely and just push the new values into
        the existing widgets via _refresh_keyconfig_row_values(). Pass force=True to bypass this
        (game switches use it, since the action list itself can differ there).

        The rows themselves (frame + label) are also now plain tk.Frame/tk.Label rather than
        CTkFrame/CTkLabel - same "hybrid" conversion already validated for the color grid. The value
        widget started out as CTkButton (Keyboard mode, kept) / CTkOptionMenu (Controller mode), but
        CTkOptionMenu turned out to still be the dominant cost on real hardware (bench_keyconfig_
        controller.py: ~90ms/30 rows vs ~19ms for a plain tk.OptionMenu), so Controller mode's value
        widget is now a plain tk.OptionMenu too - CTkButton is the only CTk widget left in this panel."""
        if not hasattr(self, 'keyconfig_rows_frame'):
            return
        self._cancel_keyconfig_rebind()

        game = getattr(self, 'current_game', 'EDF6')
        is_controller = getattr(self, 'keyconfig_mode_var', None) is not None and self.keyconfig_mode_var.get() == "Controller"
        category = self.keyconfig_category_var.get()
        player = int(self.keyconfig_player_var.get()) if hasattr(self, 'keyconfig_player_var') else 1
        # Both Controller and Keyboard mode are available for EDF5, EDF6, and EDF4.1 now.
        available = _game_is_edf5(game) or _game_is_edf6(game) or _game_is_edf41(game)
        # Controller-type selector is only meaningful in Controller mode for EDF6 or EDF4.1 - EDF5 never shipped PS4/Switch glyph variants. Disabled rather than hidden otherwise, so its value/position stays stable across mode/game switches.
        if hasattr(self, 'keyconfig_controller_type_menu'):
            self.keyconfig_controller_type_menu.configure(state="normal" if (available and is_controller and (_game_is_edf6(game) or _game_is_edf41(game))) else "disabled")
        # Player 2 keyboard is hard-hidden (not just disabled) for EDF6 and EDF4.1 Keyboard mode, since neither game's PC port wired up real Player 2 keyboard/mouse support. Controller mode's Player 2 is real and confirmed for both games.
        hide_player2_selector = (not is_controller) and (_game_is_edf6(game) or _game_is_edf41(game))
        if hasattr(self, 'keyconfig_player_menu') and hasattr(self, 'keyconfig_player_label_widget'):
            self.keyconfig_player_label_widget.pack_forget()
            self.keyconfig_player_menu.pack_forget()
            if hide_player2_selector:
                self.keyconfig_player_var.set("1")  # force Player 1 - nothing else is real here
            else:
                # Explicit before= re-insertion keeps Player in its original position ahead of the Controller-type selector, instead of pack() appending to the row's end each time this toggles.
                if hasattr(self, 'keyconfig_controller_type_label_widget'):
                    self.keyconfig_player_label_widget.pack(side="left", padx=(0, 4), before=self.keyconfig_controller_type_label_widget)
                    self.keyconfig_player_menu.pack(side="left", padx=(0, 10), before=self.keyconfig_controller_type_label_widget)
                else:
                    self.keyconfig_player_label_widget.pack(side="left", padx=(0, 4))
                    self.keyconfig_player_menu.pack(side="left", padx=(0, 10))

        sig = (game, is_controller, category, player)
        if (not force) and self.keyconfig_rows and getattr(self, '_keyconfig_built_sig', None) == sig:
            # Same row set already built for this exact combo - refresh displayed values only.
            try:
                self._refresh_keyconfig_row_values()
            except Exception as e:
                self._warn(e)
            return
        self._keyconfig_built_sig = sig

        for child in self.keyconfig_rows_frame.winfo_children():
            child.destroy()
        self.keyconfig_rows = []

        if not available:
            self.keyconfig_unavailable_label = ctk.CTkLabel(
                self.keyconfig_rows_frame,
                text=self.tr('kill_table_unavailable', "Not yet available for this game"),
                font=(FONT_FAMILY, BASE_FONT_SIZE),
            )
            self.keyconfig_unavailable_label.pack(anchor="w", pady=4)
            return
        self.keyconfig_unavailable_label = None

        # Sampled once per rebuild from a throwaway CTk widget so the plain-tk row/label colors
        # match the real installed theme/appearance-mode instead of a hardcoded guess - same
        # helper _build_color_grid() uses.
        palette = self._sample_ctk_default_colors(self.keyconfig_rows_frame)
        label_fg_confirmed = palette['label_fg']
        label_fg_unverified = "#c9a227"

        if is_controller:
            # Controller rows: every action in a category shares the same class-level confirmation status, unlike keyboard's per-action flags; inert placeholder slots are skipped entirely. EDF4.1's mapped actions are always confirmed data.
            confirmed = True if _game_is_edf41(game) else (CONTROLLER_CONFIRMED_EDF6 if _game_is_edf6(game) else CONTROLLER_CONFIRMED).get(category, False)
            keybind_data = getattr(self, 'controller_keybind_data', {}) or {}
            for action_name in get_controller_actions(category, game=game, player=player):
                if action_name.startswith("("):
                    continue
                row = tk.Frame(self.keyconfig_rows_frame, bg=palette['row_bg'], highlightthickness=0)
                row.pack(fill="x", pady=1, padx=2)
                display_action = self._keyconfig_action_label(action_name)
                label_text = display_action if confirmed else f"{display_action} ({self.tr('keyconfig_unverified', 'unverified')})"
                lbl = tk.Label(row, text=label_text, width=28, anchor="w", bg=palette['row_bg'],
                                fg=label_fg_confirmed if confirmed else label_fg_unverified, highlightthickness=0)
                lbl.pack(side="left", padx=(4, 8))
                raw_value = keybind_data.get((player, category, action_name))
                value_var = tk.StringVar(value=self._controller_display_text(raw_value))
                button_names = [name for _raw, name in gamepad_button_names(self._controller_display_type(), game=game)]
                # Perf note (2026-09-09): this was ctk.CTkOptionMenu - benchmarked at ~90ms to build
                # a 30-row category (bench_keyconfig_controller.py, real hardware) vs ~19ms for this
                # plain tk.OptionMenu (Menubutton-based), a ~4.9x speedup, on top of the row/label
                # hybrid conversion already shipped. It's the last heavy widget left in Key Config.
                value_menu = tk.OptionMenu(
                    row, value_var, *button_names,
                    command=lambda display_value, a=action_name: self.on_keyconfig_controller_value_change(a, display_value),
                )
                menu_default_bg = palette['optionmenu_bg']
                menu_default_hover = palette['optionmenu_hover']
                menu_default_text = palette['optionmenu_text']
                value_menu.configure(bg=menu_default_bg, fg=menu_default_text,
                                      activebackground=menu_default_hover, activeforeground=menu_default_text,
                                      highlightthickness=0, relief="flat", width=18, anchor="w")
                try:
                    value_menu["menu"].configure(bg=menu_default_bg, fg=menu_default_text,
                                                  activebackground=menu_default_hover, activeforeground=menu_default_text)
                except Exception as e:
                    self._warn(e)
                value_menu.pack(side="left", padx=(0, 4))
                self.keyconfig_rows.append({
                    "action_name": action_name, "confirmed": confirmed, "label": lbl, "value_menu": value_menu,
                    "value_var": value_var,
                    "value_menu_default_bg": menu_default_bg,
                    "value_menu_default_hover": menu_default_hover,
                    "value_menu_default_text": menu_default_text,
                })
                self._apply_gamepad_face_color(value_menu, raw_value, menu_default_bg, menu_default_hover, menu_default_text)
            return

        actions = get_keyconfig_actions(category, game=game)
        if not actions:
            # A valid, selectable category with no real offset data behind it yet, so a contributor sees this rather than a blank panel. Distinct wording from the game-level "Not yet available" placeholder.
            self.keyconfig_unavailable_label = ctk.CTkLabel(
                self.keyconfig_rows_frame,
                text=self.tr('keyconfig_category_unconfirmed', "Not yet confirmed for this game"),
                font=(FONT_FAMILY, BASE_FONT_SIZE),
            )
            self.keyconfig_unavailable_label.pack(anchor="w", pady=4)
            return
        keybind_data = getattr(self, 'keybind_data', {}) or {}
        for action_name, _slot, confirmed in actions:
            row = tk.Frame(self.keyconfig_rows_frame, bg=palette['row_bg'], highlightthickness=0)
            row.pack(fill="x", pady=1, padx=2)
            display_action = self._keyconfig_action_label(action_name)
            label_text = display_action if confirmed else f"{display_action} ({self.tr('keyconfig_unverified', 'unverified')})"
            lbl = tk.Label(row, text=label_text, width=28, anchor="w", bg=palette['row_bg'],
                            fg=label_fg_confirmed if confirmed else label_fg_unverified, highlightthickness=0)
            lbl.pack(side="left", padx=(4, 8))
            raw_value = keybind_data.get((player, category, action_name))
            key_btn = ctk.CTkButton(
                row, text=self._keyconfig_display_text(raw_value), width=140,
                command=lambda a=action_name: self.start_keyconfig_rebind(a),
            )
            key_btn.pack(side="left", padx=(0, 4))
            self.keyconfig_rows.append({"action_name": action_name, "confirmed": confirmed, "label": lbl, "key_btn": key_btn})

    def _refresh_keyconfig_row_values(self):
        """Fast path taken by rebuild_keyconfig_rows() when the game/mode/category/player combo
        hasn't changed since the rows were last built (see that method's docstring) - pushes the
        current keybind_data/controller_keybind_data values into the already-built widgets instead
        of destroying and recreating them. Cheap: this is a handful of .configure()/.set() calls
        per row, not a full widget rebuild."""
        game = getattr(self, 'current_game', 'EDF6')
        is_controller = getattr(self, 'keyconfig_mode_var', None) is not None and self.keyconfig_mode_var.get() == "Controller"
        category = self.keyconfig_category_var.get()
        player = int(self.keyconfig_player_var.get()) if hasattr(self, 'keyconfig_player_var') else 1
        if is_controller:
            keybind_data = getattr(self, 'controller_keybind_data', {}) or {}
            for row in self.keyconfig_rows:
                value_menu = row.get("value_menu")
                if value_menu is None:
                    continue
                action_name = row["action_name"]
                raw_value = keybind_data.get((player, category, action_name))
                value_var = row.get("value_var")
                try:
                    if value_var is not None:
                        value_var.set(self._controller_display_text(raw_value))
                except Exception as e:
                    self._warn(e)
                self._apply_gamepad_face_color(
                    value_menu, raw_value,
                    row.get("value_menu_default_bg"), row.get("value_menu_default_hover"), row.get("value_menu_default_text"),
                )
        else:
            keybind_data = getattr(self, 'keybind_data', {}) or {}
            for row in self.keyconfig_rows:
                key_btn = row.get("key_btn")
                if key_btn is None:
                    continue
                action_name = row["action_name"]
                raw_value = keybind_data.get((player, category, action_name))
                try:
                    key_btn.configure(text=self._keyconfig_display_text(raw_value))
                except Exception as e:
                    self._warn(e)

    def _keyconfig_display_text(self, raw_value):
        if raw_value is None:
            return self.tr('keyconfig_unbound', "(unbound)")
        game = getattr(self, 'current_game', 'EDF6')
        decoded = decode_keybind_letter(raw_value, game=game)
        if decoded is not None:
            return decoded
        return f"#{raw_value}"  # outside the game's key table - most likely gamepad/mouse, show raw

    def _controller_display_type(self):
        """Which button-name overlay to display with ('xbox'/'ps4'/'switch'). Forces 'xbox' for EDF5 specifically, since it never shipped PS4/Switch button glyphs, regardless of the selector's stored value. EDF6/EDF4.1 pass the selector's value through."""
        game = getattr(self, 'current_game', 'EDF6')
        if _game_is_edf5(game):
            return "xbox"
        return getattr(self, 'controller_type_var', None).get() if hasattr(self, 'controller_type_var') else "xbox"

    def on_controller_type_display_change(self, display_value):
        """Handler for the Controller-type selector. Purely cosmetic - swaps which overlay rebuild_keyconfig_rows() uses next, doesn't touch any stored keybind value; persisted via save_config() like toggle_theme(). Also recolors the segmented button to the new platform's brand color."""
        canonical_map = {label: key for key, label in self._controller_type_labels.items()}
        self.controller_type_var.set(canonical_map.get(display_value, "xbox"))
        brand = self._controller_type_brand_colors.get(self.controller_type_var.get())
        if brand:
            try:
                self.keyconfig_controller_type_menu.configure(selected_color=brand[0], selected_hover_color=brand[1])
            except Exception as e:
                self._warn(e)
        try:
            self.save_config()
        except Exception as e:
            self._warn(e)
        # force=True: the row set (game/mode/category/player) hasn't changed, but each
        # CTkOptionMenu's own selectable-values list is platform-specific (xbox/ps4/switch button
        # names) and was baked in at build time, so the fast "just refresh values" path in
        # rebuild_keyconfig_rows() can't fix that - a real rebuild is needed here.
        self.rebuild_keyconfig_rows(force=True)

    def _controller_display_text(self, raw_value):
        if raw_value is None:
            return self.tr('keyconfig_unbound', "(unbound)")
        game = getattr(self, 'current_game', 'EDF6')
        return decode_gamepad_button(raw_value, self._controller_display_type(), game=game)

    def on_keyconfig_controller_value_change(self, action_name, display_value):
        """Controller mode's equivalent of _on_keyconfig_keypress: rebinding is a plain dropdown pick rather than a live "press a button" capture flow, since there's no gamepad capture wired in. Commits straight into app.controller_keybind_data on selection."""
        category = self.keyconfig_category_var.get()
        player = int(self.keyconfig_player_var.get()) if hasattr(self, 'keyconfig_player_var') else 1
        game = getattr(self, 'current_game', 'EDF6')
        raw_value = next((raw for raw, name in gamepad_button_names(self._controller_display_type(), game=game) if name == display_value), None)
        if raw_value is None:
            return
        if not hasattr(self, 'controller_keybind_data'):
            self.controller_keybind_data = {}
        self.controller_keybind_data[(player, category, action_name)] = raw_value
        row = next((r for r in self.keyconfig_rows if r["action_name"] == action_name), None)
        if row is not None and "value_menu" in row:
            self._apply_gamepad_face_color(
                row["value_menu"], raw_value,
                row.get("value_menu_default_bg"), row.get("value_menu_default_hover"), row.get("value_menu_default_text"),
            )

    @staticmethod
    def _readable_text_color(hex_color):
        """Pick black or white text for legibility against `hex_color`, using ITU-R BT.601 perceptual brightness weighting rather than a flat RGB average or a fixed per-color guess."""
        h = (hex_color or "").lstrip("#")
        if len(h) != 6:
            return "#FFFFFF"
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#000000" if brightness > 0.6 else "#FFFFFF"

    def _apply_gamepad_face_color(self, value_menu, raw_value, default_bg, default_hover, default_text):
        """Recolor a controller-mode value dropdown (plain tk.OptionMenu, see rebuild_keyconfig_rows'
        2026-09-09 perf note) to match its selected face button's real color, or reset it to its own
        captured default theme colors for anything without a real-world brand color. Text color is
        picked per-background via _readable_text_color. Also recolors the dropdown menu itself
        (value_menu["menu"]) so the open list matches, not just the closed button."""
        per_type = self._GAMEPAD_FACE_BUTTON_COLORS.get(raw_value)
        color = per_type.get(self._controller_display_type()) if per_type else None
        try:
            if color:
                bg, hover, text = color[0], color[1], self._readable_text_color(color[0])
            else:
                bg, hover, text = default_bg, default_hover, default_text
            value_menu.configure(bg=bg, activebackground=hover, fg=text, activeforeground=text)
            try:
                value_menu["menu"].configure(bg=bg, fg=text, activebackground=hover, activeforeground=text)
            except Exception:
                pass
        except Exception as e:
            self._warn(e)

    def start_keyconfig_rebind(self, action_name):
        """Begin capturing the next keystroke or mouse input for `action_name`. Only one capture is active at a time. Mouse capture (<Button-1/2/3>/<MouseWheel>) is armed via bind_all rather than self.bind since a click can land on any widget, and deferred one idle tick so the same click that opened capture doesn't immediately re-fire as the new value. Reuses _pause_global_scroll/_resume_global_scroll so MouseWheel reaches this handler instead of being consumed by page scrolling."""
        if not (_game_is_edf5(getattr(self, 'current_game', 'EDF6')) or _game_is_edf6(getattr(self, 'current_game', 'EDF6')) or _game_is_edf41(getattr(self, 'current_game', 'EDF6'))):
            return
        self._cancel_keyconfig_rebind()
        row = next((r for r in self.keyconfig_rows if r["action_name"] == action_name), None)
        if row is None:
            return
        category = self.keyconfig_category_var.get()
        player = int(self.keyconfig_player_var.get()) if hasattr(self, 'keyconfig_player_var') else 1
        # Stashed here (not a static default) so restoring it afterward is always exact regardless of theme, since cget() reads what the button actually showed a moment ago.
        default_fg = row["key_btn"].cget("fg_color")
        default_hover = row["key_btn"].cget("hover_color")
        default_text = row["key_btn"].cget("text_color")
        self.keyconfig_rebind_target = (player, category, action_name, row["key_btn"], default_fg, default_hover, default_text)
        row["key_btn"].configure(
            text=self.tr('keyconfig_press_key', "Press a key or click a mouse button..."),
            fg_color=self._KEYCONFIG_CAPTURE_COLOR,
            hover_color=self._KEYCONFIG_CAPTURE_HOVER_COLOR,
            # The gold capture color is bright enough that white text loses contrast, same luminance-based fix as _readable_text_color for gamepad face-button colors.
            text_color=self._readable_text_color(self._KEYCONFIG_CAPTURE_COLOR),
        )
        self.bind('<KeyPress>', self._on_keyconfig_keypress)
        self._pause_global_scroll()
        self.after_idle(self._arm_keyconfig_mouse_capture)

    _KEYCONFIG_MOUSE_BUTTON_NAMES = {1: "MouseL", 2: "MouseM", 3: "MouseR"}

    def _arm_keyconfig_mouse_capture(self):
        """Deferred half of start_keyconfig_rebind's mouse capture - see that method's docstring
        for why this can't just run inline. Bails out quietly if the capture was already
        cancelled/completed before this idle callback got to run (e.g. Escape pressed fast)."""
        if self.keyconfig_rebind_target is None:
            return
        try:
            for seq in ('<Button-1>', '<Button-2>', '<Button-3>'):
                self.bind_all(seq, self._on_keyconfig_mouseclick, add=False)
            self.bind_all('<MouseWheel>', self._on_keyconfig_mousewheel, add=False)
        except Exception as e:
            self._warn(e)

    def _release_keyconfig_mouse_capture(self):
        for seq in ('<Button-1>', '<Button-2>', '<Button-3>', '<MouseWheel>'):
            try:
                self.unbind_all(seq)
            except Exception:
                pass
        self._resume_global_scroll()

    def _on_keyconfig_mouseclick(self, event):
        if self.keyconfig_rebind_target is None:
            return
        self._commit_keyconfig_capture(self._KEYCONFIG_MOUSE_BUTTON_NAMES.get(event.num))
        return "break"

    def _on_keyconfig_mousewheel(self, event):
        if self.keyconfig_rebind_target is None:
            return
        self._commit_keyconfig_capture("MouseWheel")
        return "break"

    def _cancel_keyconfig_rebind(self, restore_display=True):
        if self.keyconfig_rebind_target is None:
            return
        player, _category, action_name, key_btn, default_fg, default_hover, default_text = self.keyconfig_rebind_target
        try:
            self.unbind('<KeyPress>')
        except Exception:
            pass
        self._release_keyconfig_mouse_capture()
        self.keyconfig_rebind_target = None
        if restore_display:
            try:
                keybind_data = getattr(self, 'keybind_data', {}) or {}
                raw_value = keybind_data.get((player, self.keyconfig_category_var.get(), action_name))
                key_btn.configure(text=self._keyconfig_display_text(raw_value), fg_color=default_fg, hover_color=default_hover, text_color=default_text)
            except Exception:
                pass  # widget may already be destroyed (category switched mid-capture)

    def _on_keyconfig_keypress(self, event):
        if self.keyconfig_rebind_target is None:
            return
        if event.keysym == 'Escape':
            self._cancel_keyconfig_rebind()
            return
        edf5_name = self._keyconfig_keysym_to_edf5_name(event.keysym)
        self._commit_keyconfig_capture(edf5_name)

    def _commit_keyconfig_capture(self, name):
        """Shared finish-line for every capture input source. `name` is an EDF5_KEY_TABLE or EDF5_MOUSE_TABLE name string, or None if the input source couldn't map to a known name."""
        if self.keyconfig_rebind_target is None:
            return
        player, category, action_name, key_btn, default_fg, default_hover, default_text = self.keyconfig_rebind_target
        game = getattr(self, 'current_game', 'EDF6')
        raw_value = encode_keybind_letter(name, game=game) if name else None
        try:
            self.unbind('<KeyPress>')
        except Exception:
            pass
        self._release_keyconfig_mouse_capture()
        self.keyconfig_rebind_target = None
        if raw_value is None:
            # Not in EDF5_KEY_TABLE/EDF5_MOUSE_TABLE - refuse the edit rather than guess an encoding. Leave the stored value untouched, just tell the user via the button text; color is still restored immediately.
            key_btn.configure(text=self.tr('keyconfig_unsupported_key', "Unsupported key"), fg_color=default_fg, hover_color=default_hover, text_color=default_text)
            return
        if not hasattr(self, 'keybind_data'):
            self.keybind_data = {}
        self.keybind_data[(player, category, action_name)] = raw_value
        key_btn.configure(text=self._keyconfig_display_text(raw_value), fg_color=default_fg, hover_color=default_hover, text_color=default_text)

    def update_color_preview(self, is_secondary, idx):
        """Update the small preview swatch for palette row idx in the given column (Primary/
        Secondary) from its current R/G/B entries (alpha isn't representable in a flat color
        swatch, so it's ignored for the preview)."""
        rows = self.color_palette_rows.get(is_secondary, [])
        if idx >= len(rows):
            return
        row = rows[idx]
        try:
            r = max(0.0, min(1.0, float(row["entries"]["R"].get())))
            g = max(0.0, min(1.0, float(row["entries"]["G"].get())))
            b = max(0.0, min(1.0, float(row["entries"]["B"].get())))
        except ValueError:
            return
        hex_color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        try:
            # preview is a plain tk.Frame now (see _build_color_grid) - bg, not fg_color.
            row["preview"].configure(bg=hex_color)
        except Exception as e:
            print(f"[WARN] update_color_preview failed: {e}")

    def pick_color(self, is_secondary, idx):
        """Open the native color picker for palette row idx and write the chosen RGB back into the R/G/B entries as 0.0-1.0 floats. Alpha isn't touched since colorchooser has no alpha channel."""
        rows = self.color_palette_rows.get(is_secondary, [])
        if idx >= len(rows):
            return
        row = rows[idx]
        try:
            r = max(0.0, min(1.0, float(row["entries"]["R"].get())))
            g = max(0.0, min(1.0, float(row["entries"]["G"].get())))
            b = max(0.0, min(1.0, float(row["entries"]["B"].get())))
            initial = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        except ValueError:
            initial = "#ffffff"
        result = colorchooser.askcolor(color=initial, title="Pick Color UI")
        rgb = result[0]
        if not rgb:
            return
        r, g, b = (c / 255.0 for c in rgb)
        for comp, v in zip(("R", "G", "B"), (r, g, b)):
            entry = row["entries"][comp]
            entry.delete(0, "end")
            entry.insert(0, f"{v:.4f}")
        self.update_color_preview(is_secondary, idx)

if __name__ == "__main__":
    app = SaveEditor()
    # Nuitka's onefile splash screen (see BuildEDFSE_Nuitka_OneFile.bat) does NOT auto-close for
    # tkinter apps - confirmed against Nuitka's own user manual, which is explicit that dismissing
    # it is the program's own responsibility: it watches for a feedback file in the temp dir and
    # keeps the splash up until that file is deleted. Without this block the splash just stays on
    # screen forever after the real window is ready (2026-09-09 bug report). No-ops entirely for
    # PyInstaller/Nuitka-standalone builds and plain `python EDFSaveEditorMain.py` runs, since
    # NUITKA_ONEFILE_PARENT is only ever set by a Nuitka onefile exe's bootstrap process.
    try:
        if "NUITKA_ONEFILE_PARENT" in os.environ:
            import tempfile
            # Force the real window to actually paint before we signal the splash's removal, so
            # there's no blank-screen gap between the splash disappearing and the window appearing.
            app.update()
            splash_filename = os.path.join(
                tempfile.gettempdir(),
                "onefile_%d_splash_feedback.tmp" % int(os.environ["NUITKA_ONEFILE_PARENT"]),
            )
            if os.path.exists(splash_filename):
                os.unlink(splash_filename)
    except Exception as e:
        print(f"[WARN] Failed to signal Nuitka splash screen removal: {e}")
    app.mainloop()