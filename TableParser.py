import json
import os

# ---------------- Weapon and Mission Parsing Script ----------------
# This script now:
# 1. Parses weapon name files into WeaponNamesLang.json (existing behavior, cleaned up)
# 2. Parses mission list files into MissionNames.json matching the provided structure
# ------------------------------------------------------------------

# Language set used across files
LANGS = ["en", "ja", "kr", "sc", "cn"]

# Weapon text files per game (placeholders for EDF5 / EDF4.1)
WEAPON_FILES = {
    "EDF6": {
        "en": "WEAPONTEXT.EN.json",
        "ja": "WEAPONTEXT.JA.json",
        "kr": "WEAPONTEXT.KR.json",
        "sc": "WEAPONTEXT.SC.json",
        "cn": "WEAPONTEXT.CN.json",
    },
    "EDF5": {lang: None for lang in LANGS},
    "EDF4.1": {lang: None for lang in LANGS},
}

# Mission list files grouped by content pack
MISSION_FILES = {
    "EDF6": {
        "en": "MISSIONLIST.ONLINE.TXT.EN.json",
        "ja": "MISSIONLIST.ONLINE.TXT.JA.json",
        "kr": "MISSIONLIST.ONLINE.TXT.KR.json",
        "sc": "MISSIONLIST.ONLINE.TXT.SC.json",
        "cn": "MISSIONLIST.ONLINE.TXT.CN.json",
    },
    "EDF6DLC1": {
        "en": "MISSIONLIST_DLC1.ONLINE.TXT.EN.json",
        "ja": "MISSIONLIST_DLC1.ONLINE.TXT.JA.json",
        "kr": "MISSIONLIST_DLC1.ONLINE.TXT.KR.json",
        "sc": "MISSIONLIST_DLC1.ONLINE.TXT.SC.json",
        "cn": "MISSIONLIST_DLC1.ONLINE.TXT.CN.json",
    },
    "EDF6DLC2": {
        "en": "MISSIONLIST_DLC2.ONLINE.TXT.EN.json",
        "ja": "MISSIONLIST_DLC2.ONLINE.TXT.JA.json",
        "kr": "MISSIONLIST_DLC2.ONLINE.TXT.KR.json",
        "sc": "MISSIONLIST_DLC2.ONLINE.TXT.SC.json",
        "cn": "MISSIONLIST_DLC2.ONLINE.TXT.CN.json",
    },
    # Placeholders for future support (empty language dicts)
    "EDF5": {lang: None for lang in LANGS},
    "EDF4.1": {lang: None for lang in LANGS},
}


def _strip_json_comments(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('//'):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)


def _load_json(path):
    # Try multiple encodings; some extracted files may be UTF-16 or Shift-JIS.
    encodings = ["utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "cp932", "shift_jis", "latin-1"]
    for enc in encodings:
        try:
            with open(path, 'r', encoding=enc) as f:
                raw = f.read()
            # Remove full-line // comments if present
            if '//' in raw:
                raw_no_comments = _strip_json_comments(raw)
            else:
                raw_no_comments = raw
            try:
                return json.loads(raw_no_comments)
            except json.JSONDecodeError:
                # Last resort: try to wrap removal of trailing commas (simple heuristic)
                fixed = raw_no_comments.replace(',\n}', '\n}').replace(',\n]', '\n]')
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            return None
        except UnicodeDecodeError:
            continue
        except Exception:
            continue
    print(f"Skipping file due to encoding/parse issues: {path}")
    return None


def parse_weapons():
    # Build output for all games (EDF6 + placeholders)
    output = {game: {"languages": {lang: {} for lang in LANGS}} for game in WEAPON_FILES}
    for game, lang_map in WEAPON_FILES.items():
        for lang, filename in lang_map.items():
            if not filename:
                continue
            data = _load_json(filename)
            if not data:
                continue
            try:
                text_table = data['variables'][0]['value']
            except (KeyError, IndexError, TypeError):
                continue
            for idx, weapon_entry in enumerate(text_table):
                try:
                    name = weapon_entry['value'][0]['value']
                except (KeyError, IndexError, TypeError):
                    continue
                output[game]["languages"][lang][str(idx)] = name
    with open('WeaponNamesLang.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("WeaponNamesLang.json created.")


def parse_missions():
    mission_output = {game: {lang: {} for lang in LANGS} for game in MISSION_FILES}

    def _select_entries(data):
        if not isinstance(data, dict):
            return []
        variables = data.get('variables', [])
        best = []
        for v in variables:
            if isinstance(v, dict):
                cand = v.get('value')
                if isinstance(cand, list) and len(cand) > len(best):
                    best = cand
        return best

    def _extract_name(entry):
        # Expected nested list structure
        val = entry.get('value') if isinstance(entry, dict) else None
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, dict) and 'value' in first:
                inner = first['value']
                if isinstance(inner, list) and inner:  # Sometimes one more nesting
                    maybe = inner[0]
                    if isinstance(maybe, dict) and 'value' in maybe and isinstance(maybe['value'], str):
                        return maybe['value']
                if isinstance(inner, str):
                    return inner
        elif isinstance(val, str):
            return val
        return None

    debug = bool(os.environ.get('PARSER_DEBUG'))

    for game, files in MISSION_FILES.items():
        for lang, filename in files.items():
            if not filename:
                continue
            data = _load_json(filename)
            if not data:
                if debug:
                    print(f"[missions] {game} {lang}: file not loaded")
                continue
            entries = _select_entries(data)
            if not entries:
                if debug:
                    print(f"[missions] {game} {lang}: no entries found in variables")
                continue
            mission_index = 1
            added = 0
            for entry in entries:
                name = None
                try:
                    name = _extract_name(entry)
                except Exception:
                    name = None
                if name:
                    mission_output[game][lang][str(mission_index)] = name
                    added += 1
                mission_index += 1
            if debug:
                print(f"[missions] {game} {lang}: added {added} names")

    with open('MissionNames.json', 'w', encoding='utf-8') as f:
        json.dump(mission_output, f, indent=2, ensure_ascii=False)
    print("MissionNames.json created.")


def main():
    parse_weapons()
    parse_missions()


if __name__ == "__main__":
    main()