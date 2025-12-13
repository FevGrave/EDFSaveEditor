# EDFSaveEditorLogic.py
import struct
import os
import json
import sys  # added for frozen exe path handling
from tkinter import filedialog
from EDFSaveEditorSave_Handler import load_save, save_save, generate_key_iv, aes_ctr_decrypt, aes_ctr_encrypt, crc32c, generate_mst_key_iv_variants

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

# Replaced direct open with safe loader using resource_path
WEAPON_NAMES = load_json_safe(resource_path('simple_weapons.json'), {})

ARMOR_STRUCTURE = [
    (0x134, 0x4, "<I", "Ranger Armor", lambda v, mg: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * 0.5600000023841858 + 200, 2),
        "Modded Armor Gain": round(v * (mg * 0.5600000023841858) + 200, 2),
    }),
    (0x138, 0x4, "<I", "Wingdiver Armor", lambda v, mg: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * 0.3499999940395355 + 150, 2),
        "Modded Armor Gain": round(v * (mg * 0.3499999940395355) + 150, 2),
    }),
    (0x13C, 0x4, "<I", "Air Raider Armor", lambda v, mg: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * 0.5600000023841858 + 200, 2),
        "Modded Armor Gain": round(v * (mg * 0.5600000023841858) + 200, 2),
    }),
    (0x140, 0x4, "<I", "Fencer Armor", lambda v, mg: {
        "Total You Really Have": v,
        "Base Game Gain": round(v * 0.5950000286102295 + 250, 2),
        "Modded Armor Gain": round(v * (mg * 0.5950000286102295) + 250, 2),
    }),
]

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

# --- KILL FIELDS for Achievements Tab ---
KILL_FIELDS = [
    (0x104, 4, 'android_kills'),
    (0x108, 4, 'super_android_kills'),
    (0x10C, 4, 'high_mobility_android_kills'),
    (0x110, 4, 'grenadier_kills'),
    (0x114, 4, 'cyclops_kills'),
    (0x118, 4, 'giant_grenadier_kills'),
    (0x11C, 4, 'giant_android_kills'),
    (0x120, 4, 'king_kills'),
    (0x128, 4, 'teleport_ship_kills'),
    (0x12C, 4, 'gamma_kills'),
    (0x130, 4, 'deroys_kills'),
    (0x134, 4, 'giant_tadpole_kills'),
    (0x138, 4, 'tadpole_kills'),
    (0x164, 4, 'colonists_kills'),
    (0x168, 4, 'species_alpha_kills'),
    (0x16C, 4, 'mother_monster_kills'),
    (0x170, 4, 'flying_aggressors_kills'),
    (0x174, 4, 'queen_kills'),
    (0x178, 4, 'beta_kills'),
    (0x17C, 4, 'high_grade_drone_kills'),
    (0x180, 4, 'drone_kills'),
    (0x184, 4, 'cosmonaut_kills'),
    (0x19C, 4, 'small_hive_kills'),
    (0x1A0, 4, 'imperial_drone_kills'),
    (0x1A4, 4, 'tier2_drone_kills'),
    (0x1AC, 4, 'primer_kills'),
    (0x1B0, 4, 'kruuls_kills'),
    (0x1B4, 4, 'scylla_kills'),
    (0x1B8, 4, 'erginues_kills'),
    (0x1BC, 4, 'archeluses_kills'),
    (0x1C4, 4, 'arnea_kills'),
    (0x1CC, 4, 'offline_games_started'),
    (0x1D0, 4, 'online_games_started'),
    (0x1F8, 4, 'rescues_done'),
    (0x1FC, 4, 'ring_kills'),
    (0x200, 4, 'high_grade_excavators_kills'),
    (0x204, 4, 'excavators_kills'),
    (0x208, 4, 'shield_bearer_kills'),
    (0x20C, 4, 'high_grade_tier3_drone_kills'),
    (0x210, 4, 'tier3_drone_kills'),
    (0x214, 4, 'haze_kills'),
    (0x218, 4, 'teleport_anchor_kills'),
    (0x21C, 4, 'tail_anchor_kills'),
    (0x220, 4, 'kraken_kills'),
    (0x224, 4, 'weapons_collected'),
]

def extract_kill_fields(dat_data):
    """Extract kill field values from DAT file data as a dict, using 16-bit little-endian. Defaults to 0 if data is missing."""
    kills = {}
    for offset, size, key in KILL_FIELDS:
        # Always read as 16-bit little-endian (2 bytes)
        if len(dat_data) >= offset + 2:
            val = int.from_bytes(dat_data[offset:offset+2], 'little')
        else:
            val = 0  # Default to 0 if not enough data
        kills[key] = val
    return kills

def load_save_data(app):
    folder = filedialog.askdirectory(title="Select Save Folder")
    if folder:
        gst_files = [f for f in os.listdir(folder) if f.endswith('.GST')]
        if not gst_files:
            print("No GST files found in the folder.")
            return
        # For simplicity, assume MAIN.GST or first GST file
        gst_file = os.path.join(folder, 'MAIN.GST') if 'MAIN.GST' in gst_files else os.path.join(folder, gst_files[0])
        data = load_save(gst_file)  # Returns decrypted bytes
        app.current_file = gst_file
        # Load armor
        for i, (offset, _, fmt, _, _) in enumerate(ARMOR_STRUCTURE):
            if len(data) < offset + 4:
                print(f"Warning: File too small for offset {offset}")
                continue
            v = struct.unpack_from(fmt, data, offset)[0]
            app.armor_entries[i].delete(0, "end")
            app.armor_entries[i].insert(0, str(v))
        # Load loadouts
        for i, (offset, _, fmt, _) in enumerate(LOADOUT_STRUCTURE):
            if len(data) < offset + 4:
                print(f"Warning: File too small for offset {offset}")
                continue
            v = struct.unpack_from(fmt, data, offset)[0]
            app.loadout_entries[i].delete(0, "end")
            app.loadout_entries[i].insert(0, str(v))
        # Load weapon table
        weapon_data = []
        for i in range(0, 0x6000, 12):
            if len(data) < 0x7CFC + i + 12:
                break
            entry = data[0x7CFC + i : 0x7CFC + i + 12]
            avg = struct.unpack("<I", entry[0:4])[0]  # Changed from <f to <I, no rounding needed
            stats = list(entry[4:12])
            name = WEAPON_NAMES.get(str(i//12), "Unknown")
            weapon_data.append([i//12, name, avg] + stats)
        app.weapon_data = weapon_data
        for child in app.tree.get_children():
            app.tree.delete(child)
        for idx, row in enumerate(weapon_data):
            app.tree.insert("", "end", iid=str(idx), values=row)
        # Load mission data from DEFP_M00.MST
        mst_file = os.path.join(folder, 'DEFP_M00.MST')
        if os.path.exists(mst_file):
            mst_data = load_save(mst_file)
            if len(mst_data) >= 0x61C + 0x200:
                app.mission_arrays[0] = bytearray(mst_data[0x1C:0x1C+0x200])  # Ranger
                app.mission_arrays[1] = bytearray(mst_data[0x21C:0x21C+0x200])  # Wing Diver
                app.mission_arrays[2] = bytearray(mst_data[0x41C:0x41C+0x200])  # Air Raider
                app.mission_arrays[3] = bytearray(mst_data[0x61C:0x61C+0x200])  # Fencer
                for arr in app.mission_arrays:
                    for i in range(len(arr)):
                        arr[i] &= 0x1F  # Mask to lower 5 bits for difficulties
                app.update_mission_table()
                app.update_completion()
                app.sheet.column_width(0, 300)
                for col in app.data_cols:
                    app.sheet.column_width(col, 34)
                for col in app.sep_cols:
                    app.sheet.column_width(col, 4)
                app.sheet.redraw(True)
            else:
                print("Warning: MST file too small for mission data")
            app.current_mst_file = mst_file
        else:
            print("Warning: DEFP_M00.MST not found - mission data skipped")
        # Load additional files from the same folder
        folder = os.path.dirname(app.current_file) if app.current_file else None
        if folder:
            # TROPHY.DAT
            trophy_file = os.path.join(folder, 'TROPHY.DAT')
            td = None
            if os.path.exists(trophy_file):
                # Prefer a decrypted copy produced by an external tool if present
                decrypted_workspace_path = os.path.join(os.path.dirname(__file__), '..', 'EDF6_Decrypted', 'TROPHY.DAT')
                decrypted_workspace_path = os.path.normpath(decrypted_workspace_path)
                if os.path.exists(decrypted_workspace_path):
                    try:
                        with open(decrypted_workspace_path, 'rb') as f:
                            td = f.read()
                        app.trophy_encrypted = False
                        app.trophy_key = None
                        app.trophy_iv = None
                        print(f"Loaded TROPHY.DAT from decrypted workspace copy: {decrypted_workspace_path}")
                    except Exception as e:
                        print(f"Error reading decrypted workspace TROPHY.DAT: {e}")
                        td = None
                if td is None:
                    # Read raw ciphertext
                    with open(trophy_file, 'rb') as f:
                        raw = f.read()
                    trophy_data = None
                    app.trophy_key = None
                    app.trophy_iv = None
                    app.trophy_encrypted = False

                    # Try decrypting using GST-derived key/iv first (most likely)
                    try:
                        if app.current_file:
                            try:
                                gst_key, gst_iv = generate_key_iv(app.current_file)
                                dec = aes_ctr_decrypt(raw, gst_key, gst_iv)
                                if dec[:4] == b'MDB0':
                                    trophy_data = dec
                                    app.trophy_encrypted = True
                                    app.trophy_key = gst_key
                                    app.trophy_iv = gst_iv
                                    print("TROPHY.DAT decrypted using GST key/iv")
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # Brute-force reasonable variants if GST key didn't work
                    if trophy_data is None:
                        import hashlib
                        suffix_candidates = [b"Edf41.*_Steam_Ver", b"Edf5.*_Steam_Ver"]
                        base_name = os.path.splitext(os.path.basename(trophy_file))[0]
                        bases = [base_name, 'GAMESTATE']
                        found = False
                        for digit in ('6', '5'):
                            if found:
                                break
                            for base in bases:
                                if found:
                                    break
                                for suffix in suffix_candidates:
                                    str1 = f"edf{digit}{base}.sav"
                                    str2 = f"edf{digit}{base}.stm"
                                    k_part = hashlib.md5(str1.encode('utf-16le')).digest()
                                    iv_part = hashlib.md5(str2.encode('utf-16le')).digest()
                                    if len(suffix) != 16:
                                        continue
                                    key_candidate = k_part + suffix
                                    iv_candidate = iv_part
                                    try:
                                        dec = aes_ctr_decrypt(raw, key_candidate, iv_candidate)
                                    except Exception:
                                        continue
                                    if dec[:4] == b'MDB0':
                                        trophy_data = dec
                                        app.trophy_encrypted = True
                                        app.trophy_key = key_candidate
                                        app.trophy_iv = iv_candidate
                                        print(f"TROPHY.DAT decrypted with variant {str1}+{suffix.decode('ascii','ignore')}")
                                        found = True
                                        break
                        # If still not found, try MST-style generated variants which may include more suffix/key combos
                        if not found:
                            try:
                                for tag, k_candidate, iv_candidate in generate_mst_key_iv_variants(trophy_file):
                                    try:
                                        dec = aes_ctr_decrypt(raw, k_candidate, iv_candidate)
                                    except Exception:
                                        continue
                                    if dec[:4] == b'MDB0':
                                        trophy_data = dec
                                        app.trophy_encrypted = True
                                        app.trophy_key = k_candidate
                                        app.trophy_iv = iv_candidate
                                        print(f"TROPHY.DAT decrypted with MST variant {tag}")
                                        found = True
                                        break
                                # allow outer loop to exit
                            except Exception:
                                pass
                        # Last-resort: try load_save which uses generate_key_iv internally
                        if trophy_data is None:
                            try:
                                trophy_data = load_save(trophy_file)
                                app.trophy_encrypted = True
                                try:
                                    k, iv = generate_key_iv(trophy_file)
                                    app.trophy_key = k
                                    app.trophy_iv = iv
                                except Exception:
                                    app.trophy_key = None
                                    app.trophy_iv = None
                                print("TROPHY.DAT decrypted via load_save() fallback")
                            except Exception:
                                # Fallback to plain file
                                trophy_data = raw
                                app.trophy_encrypted = False
                                app.trophy_key = None
                                app.trophy_iv = None
                                print("TROPHY.DAT used as plain bytes (no decryption succeeded)")

                    td = trophy_data if isinstance(trophy_data, (bytes, bytearray)) else bytes(trophy_data)

                # Remember current trophy path
                app.current_trophy_file = trophy_file

                # Debug: header and snippets
                try:
                    header = td[0:4].decode('ascii', errors='replace')
                except Exception:
                    header = str(td[0:4])
                hex_014 = td[0x14:0x14+32].hex(' ').upper() if len(td) >= 0x14+32 else ''
                hex_034 = td[0x34:0x34+8].hex(' ').upper() if len(td) >= 0x34+8 else ''
                hex_160 = td[0x160:0x160+4].hex(' ').upper() if len(td) >= 0x160+4 else ''

                # Extra debug: show raw ciphertext bytes at 0x160 and key/iv used (if available)
                raw_preview = ''
                try:
                    if 'raw' in locals() and raw is not None and len(raw) >= 0x160 + 4:
                        raw_preview = raw[0x160:0x160+4].hex(' ').upper()
                except Exception:
                    raw_preview = ''
                key_hex = getattr(app, 'trophy_key', None).hex().upper() if getattr(app, 'trophy_key', None) is not None else None
                iv_hex = getattr(app, 'trophy_iv', None).hex().upper() if getattr(app, 'trophy_iv', None) is not None else None
                print(f"TROPHY.DAT header: {header} | bytes[0x14..0x14+32]: {hex_014} | bytes[0x34..0x34+8]: {hex_034} | bytes[0x160..0x160+4]: {hex_160}")
                print(f"DEBUG: raw[0x160..0x163]={raw_preview} dec[0x160..0x163]={hex_160} key={key_hex} iv={iv_hex}")

                # Interpret total-time value (ticks at 60Hz -> seconds)
                if len(td) >= 0x160 + 4:
                    v_le = struct.unpack_from("<I", td, 0x160)[0]
                    hours = v_le // 0x34bc0        # 0x34bc0 == 216000 == 3600*60 H
                    minutes = (v_le // 0xE10) % 60 # 0xE10 == 3600 == 60*60 M
                    seconds = (v_le // 0x3C) % 60  # 0x3C == 60 == ticks per S
                    formatted = f"{hours}h {minutes}m {seconds}s"
                    app.playtime_label.configure(text=formatted)
                    print(f"TROPHY.DAT time raw ticks={v_le} -> {formatted}")
                else:
                    app.playtime_label.configure(text="TROPHY.DAT Too Small")

                # Load achievements and normalize flags to 0/1
                achievement_data = []
                percentages = list(range(5, 65, 5)) + list(range(62, 102, 2))
                while len(percentages) < 32:
                    percentages.append(percentages[-1])
                raw_progress = list(td[0x14:0x14+32])
                print('Progress achievement flags (raw):', raw_progress)
                for i in range(32):
                    raw_flag = td[0x14 + i] if (0x14 + i) < len(td) else 0
                    flag = 1 if raw_flag != 0 else 0
                    perc = percentages[i]
                    name = f"Conquest{perc} (Made {perc}% game progress)"
                    achievement_data.append([i, name, flag])
                raw_other = list(td[0x34:0x34+7])
                print('Other achievement flags (raw):', raw_other)
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
                    raw_flag = td[0x34 + i] if (0x34 + i) < len(td) else 0
                    flag = 1 if raw_flag != 0 else 0
                    name = other_achievements_names[i]
                    achievement_data.append([32 + i, name, flag])

                app.achievement_data = achievement_data

            else:
                app.playtime_label.configure(text="TROPHY.DAT Not Found")

            # After loading DAT file, extract kill fields using the already-loaded td if available
            if 'td' in locals() and td is not None:
                app.kill_fields = extract_kill_fields(td)
            else:
                app.kill_fields = {}

            # COMMON.CFG
            cfg_file = os.path.join(folder, 'COMMON.CFG')
            if os.path.exists(cfg_file):
                try:
                    # Prefer decrypted via load_save, but fall back to raw bytes if decryption fails
                    try:
                        cfg_data = load_save(cfg_file)
                    except ValueError:
                        with open(cfg_file, 'rb') as f:
                            cfg_data = f.read()
                    if len(cfg_data) >= 0x5014 + 0x20:
                        v = cfg_data[0x5014:0x5014 + 0x20]
                        name = v.decode("utf-16le", errors="replace").rstrip("\x00")
                        app.profile_name_label.configure(text=name)
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
                except Exception as e:
                    print(f"Error reading COMMON.CFG: {e}")
                    app.profile_name_label.configure(text="COMMON.CFG Read Error")
            else:
                app.profile_name_label.configure(text="COMMON.CFG Not Found")
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

    data = bytearray(load_save(file))  # Load original as bytearray
    # Save armor
    for i, (offset, _, fmt, _, _) in enumerate(ARMOR_STRUCTURE):
        try:
            v = int(app.armor_entries[i].get())
        except ValueError:
            v = 0
        struct.pack_into(fmt, data, offset, v)
    # Save loadouts
    for i, (offset, _, fmt, _) in enumerate(LOADOUT_STRUCTURE):
        try:
            v = int(app.loadout_entries[i].get())
        except ValueError:
            v = 0
        struct.pack_into(fmt, data, offset, v)
    # Save weapon table
    weapon_data = app.weapon_data
    for r, row in enumerate(weapon_data):
        offset = 0x7CFC + r * 12
        if offset + 12 > len(data):
            break  # Don't save beyond file size
        try:
            avg = int(row[2])  # Changed from float to int
            stats = bytes([int(s) for s in row[3:11]])
        except ValueError:
            continue  # Skip invalid rows
        struct.pack_into("<I", data, offset, avg)  # Changed from <f to <I
        data[offset+4:offset+12] = stats
    # Save mission data to DEFP_M00.MST
    if hasattr(app, 'current_mst_file') and app.current_mst_file:
        mst_data = bytearray(load_save(app.current_mst_file))
        mst_data[0x1C:0x1C+0x200] = app.mission_arrays[0]   # Ranger
        mst_data[0x21C:0x21C+0x200] = app.mission_arrays[1] # Wing Diver
        mst_data[0x41C:0x41C+0x200] = app.mission_arrays[2] # Air Raider
        mst_data[0x61C:0x61C+0x200] = app.mission_arrays[3] # Fencer
        save_save(app.current_mst_file, mst_data)
    # Save achievements to TROPHY.DAT
    if hasattr(app, 'current_trophy_file') and app.current_trophy_file:
        try:
            trophy_data = bytearray(load_save(app.current_trophy_file))
        except ValueError:
            # If decryption fails, load as plain
            with open(app.current_trophy_file, 'rb') as f:
                trophy_data = bytearray(f.read())
        for idx, row in enumerate(app.achievement_data):
            if idx < 32:
                offset = 0x14 + idx
            else:
                offset = 0x34 + (idx - 32)
            unlocked = 1 if row[2] else 0
            if offset < len(trophy_data):
                trophy_data[offset] = unlocked
        # Save as plain, since it might be plain
        with open(app.current_trophy_file, 'wb') as f:
            f.write(trophy_data)
    # Save the modified GST data back to file
    save_save(file, data)

def update_displays(app):
    try:
        mg = float(app.modded_gain_entry.get())
    except ValueError:
        mg = 1.0
    for i, (_, _, _, _, calc) in enumerate(ARMOR_STRUCTURE):
        try:
            v = int(app.armor_entries[i].get())
        except ValueError:
            v = 0
        results = calc(v, mg)
        app.base_gain_labels[i].configure(text=f"Base Game Gain: {results['Base Game Gain']}")
        app.modded_gain_labels[i].configure(text=f"Modded Armor Gain: {results['Modded Armor Gain']}")