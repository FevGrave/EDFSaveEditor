import os, shutil, subprocess, struct, psutil, win32gui, win32process, argparse, json, random
'''Librarian.py
This script is a comprehensive analysis and utility tool for EDF6 (Earth Defense Force 6) save files. It provides the following core functionalities:
- Copies and prepares EDF6 save slot data for analysis.
- Runs an external decryption tool (EDFDecrypt.exe) to decrypt save files.
- Parses and validates headers of key save files (GST, CFG, DAT, MST).
- Defines detailed binary structures for EDF6 save files, including offsets, types, and descriptions for MAIN.GST, COMMON.CFG, TROPHY.DAT, and MST files.
- Extracts and decodes various game data, such as player stats, color palettes, weapon tables, mission progress, and control settings.
- Supports color palette analysis with RGB-to-HSV conversion and ASCII plotting.
- Loads weapon names from a JSON file for enhanced weapon table annotation.
- Generates ImHex-compatible bookmark files (.hexbm) for visual binary analysis.
- Optionally launches ImHex with the relevant files for further inspection.
- Computes and prints coverage statistics for each file structure, indicating documentation completeness.
Key Components:
- `GST_STRUCTURE`, `CFG_STRUCTURE`, `DAT_STRUCTURE`, `MST_STRUCTURE`: Detailed mappings of file offsets, data types, and descriptions for each save file type.
- Utility functions for file operations, parsing, logging, and bookmark generation.
- Command-line interface for optional ImHex launching.
- Logging to both console and a log file for traceability.
Intended Usage:
- Run as a standalone script to analyze, document, and visualize EDF6 save data.
- Assists in reverse engineering, modding, or understanding EDF6 save file internals.
Requirements:
- Python 3.12.4 or higher
- External dependencies: psutil, pywin32 (win32gui, win32process)
- ImHex (optional, for binary visualization with bookmarks as .hexbm)
- EDFDecrypt.exe (for decryption)
Author: (FevGrave)'''

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_SLOT_DIR = os.path.join(SCRIPT_DIR, "saveslot03")
ENCRYPT_DIR = os.path.join(SCRIPT_DIR, "EDF6_Encrypted")
DECRYPT_EXE = os.path.join(SCRIPT_DIR, "EDFDecrypt.exe")
DECRYPT_DIR = os.path.join(SCRIPT_DIR, "EDF6_Decrypted")

GST_FILE = os.path.join(DECRYPT_DIR, "MAIN.GST")
ALL_WEAPONS_GST_FILE = os.path.join(DECRYPT_DIR, "PREVIOUS.GST")
TROPHY_FILE = os.path.join(DECRYPT_DIR, "TROPHY.DAT")
PREVIOUS_DAT_FILE = os.path.join(DECRYPT_DIR, "PREVIOUS.DAT")
CFG_FILE = os.path.join(DECRYPT_DIR, "COMMON.CFG")
PREVIOUS_CFG_FILE = os.path.join(DECRYPT_DIR, "PREVIOUS.CFG")
PREVIOUS_MST_FILE = os.path.join(DECRYPT_DIR, "PREVIOUS.MST")

MST_FILES = [
    "DEFP_M00.MST",
    "DEFP_DLC1.MST",  #Incomplete Decryption
    "DEFP_DLC2.MST",  #Incomplete Decryption
    #"LostMP.MST"  #Incomplete Edcryption
]

WEAPONTEXT_FILE = os.path.join(DECRYPT_DIR, "WEAPONTEXT.EN.json")

LOG_FILE = os.path.join(SCRIPT_DIR, "log.txt")

# Path to ImHex executable (update this based on your installation)
IMHEX_EXE = r"C:\Program Files\ImHex\imhex.exe"  # Adjust as needed

# Global dictionary to store parsed data
parsed_data = {}
ModdedGain = 1.0  # Adjust this value for modded games
PLAYER_CLASS_MAP = {0: "Ranger", 1: "Wingdiver", 2: "Air Raider", 3: "Fencer"}  # Map byte to class name
PLAYER_SKIN_MAP = {4294967295: "Follow the Mission", 2: "Devastation", 3: "Up-and-Coming", 0: "Civilian", 1: "Soldier"}

weapon_names = {}

def log(message):
    print(message)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def copy_save_data():
    if not os.path.exists(SAVE_SLOT_DIR):
        log(f"Save slot directory not found: {SAVE_SLOT_DIR}")
        return False
    if os.path.exists(ENCRYPT_DIR):
        shutil.rmtree(ENCRYPT_DIR)
    shutil.copytree(SAVE_SLOT_DIR, ENCRYPT_DIR)
    log(f"[✓] Copied {SAVE_SLOT_DIR} to {ENCRYPT_DIR}")
    return True

def rename_to_previous():
    if os.path.exists(DECRYPT_DIR):
        files_to_rename = {
            "MAIN.GST": "PREVIOUS.GST",
            "COMMON.CFG": "PREVIOUS.CFG",
            "TROPHY.DAT": "PREVIOUS.DAT",
            "DEFP_M00.MST": "PREVIOUS.MST",
        }
        for old_name, new_name in files_to_rename.items():
            old_path = os.path.join(DECRYPT_DIR, old_name)
            new_path = os.path.join(DECRYPT_DIR, new_name)
            if os.path.exists(old_path):
                if os.path.exists(new_path):
                    os.remove(new_path)
                os.rename(old_path, new_path)
                log(f"[✓] Renamed {old_name} to {new_name}")
            else:
                log(f"[!] {old_name} not found, skipping rename")

def run_decrypt_tool():
    if not os.path.exists(DECRYPT_EXE):
        log("[!] EDFDecrypt.exe not found!")
        return False
    log("[*] Running decrypt tool...")
    try:
        proc = subprocess.Popen(
            [DECRYPT_EXE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=SCRIPT_DIR,
            text=True,
            bufsize=1
        )
        proc.stdin.write("d\n")
        proc.stdin.flush()
        proc.stdin.close()

        proc.wait()
        log("[✓] Decrypt tool completed.\n")
        return True
    except Exception as e:
        log(f"[!] Error running decrypt tool: {e}")
        return False

def check_file_header(file_path, expected=b'MDB0'):
    if not os.path.exists(file_path):
        log(f"[!] Missing file: {file_path}")
        return
    with open(file_path, "rb") as f:
        header = f.read(4)
        readable = header.decode(errors="replace")
        if header == expected:
            log(f"[✓] {os.path.basename(file_path)}: Valid header {readable}")
        else:
            log(f"[X] {os.path.basename(file_path)}: Invalid header {readable} ({header.hex().upper()})")

def launch_imhex(file_paths):
    files_exist = all(os.path.exists(fp) for fp in file_paths)
    if not files_exist:
        for fp in file_paths:
            if not os.path.exists(fp):
                log(f"[!] {os.path.basename(fp)} not found for ImHex!")
        return False

    # Check for running ImHex processes
    imhex_running = False
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            if 'imhex.exe' in proc.info['name'].lower() and IMHEX_EXE in proc.info['exe']:
                imhex_running = True
                hwnd = win32gui.FindWindow(None, None)  # Find any ImHex window
                while hwnd:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid == proc.info['pid']:
                        win32gui.SetForegroundWindow(hwnd)  # Bring existing window to front
                        log(f"[✓] Found existing ImHex instance, brought to front (open {', '.join(map(os.path.basename, file_paths))} manually)")
                        return True
                    hwnd = win32gui.FindWindowEx(None, hwnd, None, None)
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            continue

    if not imhex_running:
        if not os.path.exists(IMHEX_EXE):
            log(f"[!] ImHex executable not found at {IMHEX_EXE}!")
            return False
        try:
            subprocess.Popen([IMHEX_EXE] + file_paths)
            log(f"[✓] Launched new ImHex instance with {', '.join(map(os.path.basename, file_paths))}")
            return True
        except Exception as e:
            log(f"[!] Error launching ImHex: {e}")
            return False

def rgb_to_hsv(r, g, b, max_rgb):
    """
    Convert RGB floats to HSV (H: 0–360°, S: 0–100%, V: 0–100%) with dynamic scaling.
    Returns (H, S, V) as integers for display.
    """
    # Normalize by max_rgb to approximate real Value
    scale = 1.5 if max_rgb <= 1.5 else max_rgb  # Use 1.5 for primaries, else dynamic
    r_norm = r / scale if r > 0 else 0.0
    g_norm = g / scale if g > 0 else 0.0
    b_norm = b / scale if b > 0 else 0.0
    
    # Clamp to [0,1] to handle rounding errors
    r_norm = max(0.0, min(1.0, r_norm))
    g_norm = max(0.0, min(1.0, g_norm))
    b_norm = max(0.0, min(1.0, b_norm))
    
    c_max = max(r_norm, g_norm, b_norm)
    c_min = min(r_norm, g_norm, b_norm)
    delta = c_max - c_min
    
    # Hue
    if delta == 0:
        h = 0.0
    elif c_max == r_norm:
        h = 60.0 * (((g_norm - b_norm) / delta) % 6)
    elif c_max == g_norm:
        h = 60.0 * (((b_norm - r_norm) / delta) + 2)
    elif c_max == b_norm:
        h = 60.0 * (((r_norm - g_norm) / delta) + 4)
    h = h % 360.0  # Keep as float for precision
    
    # Saturation
    s = 0.0 if c_max == 0 else (delta / c_max) * 100.0
    
    # Value: Adjust to approximate real Value (reduce by ~25–75%)
    v = c_max * 100.0 * 0.75  # Heuristic: reduce Value to align with real values
    
    return round(h), round(s), round(v)

def read_rgba_floats(file_path, offset, length=16):
    """Read 16 bytes at the given offset and decode as four little-endian floats (RGBA)."""
    try:
        with open(file_path, "rb") as f:
            f.seek(offset)
            data = f.read(length)
            if len(data) < 16:
                log(f"[!] Error: Insufficient data at offset 0x{offset:04X} (got {len(data)} bytes)")
                return None
            r, g, b, a = struct.unpack("<ffff", data)
            return [r, g, b, a]
    except Exception as e:
        log(f"[!] Error reading RGBA floats at offset 0x{offset:04X}: {e}")
        return None

def plot_rgb_text(data, max_value=2.0, bar_length=20, char='#'):
    """
    Plot RGBA float values as text-based ASCII bars with calculated HSV, logging to console and log file.
    
    Args:
        data: List of tuples (RGBA_floats, label), where RGBA_floats is [R, G, B, A].
        max_value: Maximum float value for scaling (default 2.0).
        bar_length: Maximum number of characters for the bar (default 20).
        char: Character to use for the bar (default '#').
    """
    log(f"Text-Only RGBA Plot (Scale: 0.0 to {max_value:.1f})")
    log("=" * 50)
    
    # Print scale
    scale_marks = ['0.0', '0.5', '1.0', '1.5', '2.0']
    scale_positions = [int(i * bar_length / max_value) for i in [0.0, 0.5, 1.0, 1.5, 2.0]]
    scale_line = [' '] * (bar_length + 1)
    for pos, mark in zip(scale_positions, scale_marks):
        scale_line[pos] = '|'
    log("Scale: " + ''.join(scale_line))
    log("       " + ' '.join(f'{mark:>3}' for mark in scale_marks))
    log("-" * 50)
    
    for rgba, label in data:
        r, g, b, a = rgba
        max_rgb = max(r, g, b) if max(r, g, b) > 0 else 1.0  # Avoid division by zero
        h, s, v = rgb_to_hsv(r, g, b, max_rgb)
        hsv_str = f"HSV ({h:3d}°, {s:3d}%, {v:3d}%)"
        hsv_str = f"{hsv_str:<20} | {label}"
        
        log(hsv_str)
        for component, value in zip(['R', 'G', 'B', 'A'], rgba):
            num_chars = int(round(min(value, max_value) * bar_length / max_value))
            bar = char * num_chars
            log(f"{component}: {value:.3f} |{bar:<{bar_length}}|")
        log("-" * 50)

GST_STRUCTURE = [
    (0x00, 0x4, "str", "Header (should be MDB0)\n"),
    (0x4, 0x4, "uint", "File Version\n"),
    (0x08, 0x4, "uint", "unknown?\n"),
    (0x0C, 0x4, "uint", "CRC32 Checksum\n"),
    (0x10, 0x4, "uint", "unknown?\n"),
    (0x14, 0x4, "uint", "Ranger Armor", lambda v: {
        "scaled": round(v * 0.5600000023841858 + 200, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.5600000023841858 + 200) * (10 * 0.5600000023841858 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n"
    }),
    (0x18, 0x4, "uint", "Wingdiver Armor", lambda v: {
        "scaled": round(v * 0.3499999940395355 + 150, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.3499999940395355 + 150) * (10 * 0.3499999940395355 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n"
    }),
    (0x1C, 0x4, "uint", "Air Raider Armor", lambda v: {
        "scaled": round(v * 0.5600000023841858 + 200, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.5600000023841858 + 200) * (10 * 0.5600000023841858 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n"
    }),
    (0x20, 0x4, "uint", "Fencer Armor", lambda v: {
        "scaled": round(v * 0.5950000286102295 + 250, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.5950000286102295 + 250) * (10 * 0.5950000286102295 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n"
    }),
    (0x24, 0x4, "unknown", "unknown"),
    (0x28, 0x14, "null", "Spacer\n"),
    (0x3C, 1, "uint", "Current Player Class", lambda v: PLAYER_CLASS_MAP.get(v, f"unknown ({v})\n")),
    (0x3D, 3, "uint", "Current Player Class Spacer\n"),
    (0x40, 0x4, "uint", "Current Player SKIN\n", lambda v: {
        "value": v,
        "state": PLAYER_SKIN_MAP.get(v, f"unknown ({v})\n"),
        "note": f"Expected states: -1(Follow the Mission), 0(Civilian), 1(Soldier), 2(Devastation), 3(Up-and-Coming)\n"
    }),
    (0x44, 0x4, "uint", "Current Ranger Primary Weapon ID\n"),
    (0x48, 0x4, "uint", "Current Ranger Secondary Weapon ID\n"),
    (0x4C, 0x4, "uint", "Current Ranger Backpack Equipment ID\n"),
    (0x50, 0x4, "uint", "Current Ranger Support Equipment ID\n"),
    (0x54, 0x4, "uint", "Unused Ranger Slot\n"),
    (0x58, 0x4, "uint", "Unused Ranger Slot\n"),
    (0x5C, 0x4, "uint", "Current Wingdiver Primary Weapon ID\n"),
    (0x60, 0x4, "uint", "Current Wingdiver Secondary Weapon ID\n"),
    (0x64, 0x4, "uint", "Current Wingdiver Independently Operated Equipment ID\n"),
    (0x68, 0x4, "uint", "Current Wingdiver Plasma Core ID\n"),
    (0x6C, 0x4, "uint", "Unused Wingdiver Slot\n"),
    (0x70, 0x4, "uint", "Unused Wingdiver Slot\n"),
    (0x74, 0x4, "uint", "Current Air Raider Primary Weapon ID\n"),
    (0x78, 0x4, "uint", "Current Air Raider Secondary Weapon ID\n"),
    (0x7C, 0x4, "uint", "Current Air Raider Tertiary Weapon ID\n"),
    (0x80, 0x4, "uint", "Current Air Raider Backpack Equipment ID\n"),
    (0x84, 0x4, "uint", "Current Air Raider Vehicle Equipment ID\n"),
    (0x88, 0x4, "uint", "Unused Air Raider Slot\n"),
    (0x8C, 0x4, "uint", "Current Fencer L. Hand Primary Weapon ID\n"),
    (0x90, 0x4, "uint", "Current Fencer R. Hand Secondary Weapon ID\n"),
    (0x94, 0x4, "uint", "Current Fencer L. Hand Tertiary Weapon ID\n"),
    (0x98, 0x4, "uint", "Current Fencer R. Hand Quaternary Weapon ID\n"),
    (0x9C, 0x4, "uint", "Current Fencer Reinforced Parts Primary Color ID\n"),
    (0xA0, 0x4, "uint", "Current Fencer Reinforced Parts Secondary ID\n"),
    (0xA4, 0x4, "unknown", "unknown\n"),
    (0xA8, 0x8C, "null", "FF Spacer\n"),
    (0x134, 0x4, "uint", "Ranger Max Armor", lambda v: {
        "scaled": round(v * 0.5600000023841858 + 200, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.5600000023841858 + 200) * (10 * 0.5600000023841858 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n"
    }),
    (0x138, 0x4, "uint", "Wingdiver Max Armor", lambda v: {
        "scaled": round(v * 0.3499999940395355 + 150, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.3499999940395355 + 150) * (10 * 0.3499999940395355 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n"
    }),
    (0x13C, 0x4, "uint", "Air Raider Max Armor", lambda v: {
        "scaled": round(v * 0.5600000023841858 + 200, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.5600000023841858 + 200) * (10 * 0.5600000023841858 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n"
    }),
    (0x140, 0x4, "uint", "Fencer Max Armor", lambda v: {
        "scaled": round(v * 0.5950000286102295 + 250, 2),
        "degrowth": v,
        "Modded Armor Gain": round((v * 0.5950000286102295 + 250) * (10 * 0.5950000286102295 * ModdedGain), 2),
        "note": "Values may not be exact due to floating-point precision\n",
    }),
    (0x144, 0x18, "null", "Max Armor Spacer Into Color Pallets\n"),
    (0x19DC, 0x24BC, "bytes", "Unused Color Pallets\n"),
    (0x3E98, 0x124, "bytes", "Default Settings for all Classes Head\n"),
    (0x3FBC, 0x3D3C, "bytes", "Default Settings for all Classes Color Pallets\n"),
    (0x7CFC, 0x6000, "bytes", "Weapon Table", lambda v: {
        "count": len(v) // 12,
        "entry_size": 12,
        "note": "Each weapon: 4-byte avg star + 8 stat stars (1 byte each)"
    })
]

# Define color sets for each class
class_color_sets = {
    "Ranger": [0x15C, 0x2E4, 0x46C, 0x5F4],
    "Wingdiver": [0x77C, 0x904, 0xA8C, 0xC14],
    "Air Raider": [0xD9C, 0xF24, 0x10AC, 0x1234],
    "Fencer": [0x13BC, 0x1544, 0x16CC, 0x1854],
}

skin_labels = ["Civilian", "Soldier", "Devastation", "Up-and-Coming"]

for class_name, set_starts in class_color_sets.items():
    for set_idx, set_start in enumerate(set_starts):
        skin_label = skin_labels[set_idx]
        # Primary palettes
        primary_start = set_start
        for pal_idx in range(12):
            offset = primary_start + pal_idx * 16
            desc = f"Raw Hex {class_name} {skin_label} Primary Color palette {pal_idx}"
            GST_STRUCTURE.append((offset, 16, "HEX", desc))
        # Primary swatch
        swatch_offset = primary_start + 12 * 16
        desc = f"Current {class_name} {skin_label} Primary Color Swatch ID\n"
        GST_STRUCTURE.append((swatch_offset, 0x4, "uint", desc))
        # Secondary palettes
        secondary_start = swatch_offset + 4
        for pal_idx in range(12):
            offset = secondary_start + pal_idx * 16
            desc = f"Raw Hex {class_name} {skin_label} Secondary Color palette {pal_idx}"
            GST_STRUCTURE.append((offset, 16, "HEX", desc))
        # Secondary swatch
        swatch_offset = secondary_start + 12 * 16
        desc = f"Current {class_name} {skin_label} Secondary Color Swatch ID\n"
        GST_STRUCTURE.append((swatch_offset, 0x4, "uint", desc))

CFG_STRUCTURE = [
    (0x00, 0x4, "str", "Header (should be MDB0)"),
    (0x4, 0x4, "uint", "File Version"),
    (0x08, 0x4, "unknown", "unknown"),
    (0x0C, 0x4, "uint", "CRC32 Checksum"),
    (0x10, 0x4, "float", "unknown"),
    (0x14, 0x4, "unknown", "unknown"),
    (0x18, 0x4, "bool", "Look Left / Right", lambda v: {
        "value": v,
        "state": "Normal" if v == 0 else "Inverted" if v == 1 else "unknown",
        "note": "0 = Normal, 1 = Inverted, unknown state"
    }),
    (0x1C, 0x4, "bool", "Look Up / Down", lambda v: {
        "value": v,
        "state": "Normal" if v == 0 else "Inverted" if v == 1 else "unknown",
        "note": "0 = Normal, 1 = Inverted, unknown state"
    }),
    (0x22, 1, "bool", "Platform ID", lambda v: {
        "value": v,
        "state": "On" if v == 0 else "Off" if v == 1 else "unknown",
        "note": "0 = On, 1 = Off, unknown state"
    }),
    (0x2C, 0x4, "uint", "Camera Type", lambda v: {
        "value": v,
        "state": "Camera Type 1" if v == 1 else "Camera Type 2" if v == 2 else "Camera Type 3" if v == 3 else "Camera Type 4" if v == 4 else "unknown",
    }),
    (0x30, 0x4, "uint", "Damage Value Display Type", lambda v: {
        "value": v,
        "state": "Camera Type 1" if v == 1 else "Camera Type 2" if v == 2 else "Camera Type 3" if v == 3 else "Camera Type 4" if v == 4 else "unknown",
    }),
    
    (0xC4, 0x4, "uint", "Ranger's Operation Controls Attack"),
    (0xC8, 0x4, "uint", "Ranger's Operation Controls Zoom / Activate"),
    (0xCC, 0x4, "uint", "Ranger's Operation Controls Jump"),
    (0xD0, 0x4, "uint", "Ranger's Operation Controls Switch Weapons"),
    (0xD4, 0x4, "uint", "Ranger's Operation Controls Reload"),
    (0xD8, 0x4, "uint", "Ranger's Operation Controls Sprint"),
    (0xDC, 0x4, "uint", "Ranger's Operation Controls Call Vehicle Dropoff"),
    (0xE0, 0x4, "uint", "Ranger's Operation Controls Use Backpack Tools"),
    (0xE4, 0x4, "unknown", "unknown"),
    (0xE8, 0x4, "unknown", "unknown"),
    (0xEC, 0x4, "unknown", "unknown"),
    (0xF0, 0x4, "unknown", "unknown"),
    (0xF4, 0x4, "unknown", "unknown"),
    (0xF8, 0x4, "unknown", "unknown"),
    (0xFC, 0x4, "unknown", "unknown"),
    (0x100, 0x4, "unknown", "unknown"),
    (0x104, 0x4, "uint", "Ranger's Vehicle (B) Operation Controls Accelerate"),
    (0x108, 0x4, "uint", "Ranger's Vehicle (B) Operation Controls Brake / Reverse"),
    (0x10C, 0x4, "uint", "Ranger's Vehicle (B) Operation Controls Handbrake"),
    (0x110, 0x4, "uint", "Ranger's Vehicle (B) Operation Controls Attack 1"),
    (0x114, 0x4, "uint", "Ranger's Vehicle (B) Operation Controls Attack 2"),
    (0x170, 0x4, "uint", "Ranger's Vehicle (B) Operation Controls Horn"),
    (0x118, 0x4, "uint", "Ranger's Combat Vehicle Operation Controls Attack 1"),
    (0x11C, 0x4, "uint", "Ranger's Combat Vehicle Operation Controls Attack 2"),
    (0x120, 0x4, "uint", "Ranger's Combat Vehicle Operation Horn"),
    (0x124, 0x4, "uint", "Ranger's Combat Frame Operation Controls Attack - Right Hand"),
    (0x128, 0x4, "uint", "Ranger's Combat Frame Operation Controls Attack - Left Hand"),
    (0x12C, 0x4, "uint", "Ranger's Combat Frame Operation Controls Attack - Right Shoulder"),
    (0x130, 0x4, "uint", "Ranger's Combat Frame Operation Controls Attack - Left Shoulder"),
    (0x134, 0x4, "uint", "Ranger's Combat Frame Operation Controls Jump"),
    (0x138, 0x4, "uint", "Ranger's Barga Operation Controls Punch - Right Hand"),
    (0x13C, 0x4, "uint", "Ranger's Barga Operation Controls Punch - Left Hand"),
    (0x140, 0x4, "uint", "Ranger's Barga Operation Controls Stamp - Right Foot"),
    (0x144, 0x4, "uint", "Ranger's Barga Operation Controls Stamp - Left Foot"),
    (0x148, 0x4, "uint", "Ranger's Barga Operation Controls Special Pose"),
    (0x14C, 0x4, "uint", "Ranger's Barga Operation Controls Special Attack"),
    (0x150, 0x4, "uint", "Ranger's Depth Crawler Operation Controls Bombard - Right"),
    (0x154, 0x4, "uint", "Ranger's Depth Crawler Operation Controls Bombard - Left"),
    (0x158, 0x4, "uint", "Ranger's Depth Crawler Operation Controls Gatling"),
    (0x15C, 0x4, "uint", "Ranger's Depth Crawler Operation Controls Emergency Avoidance"),
    (0x160, 0x4, "uint", "Ranger's Depth Crawler Operation Controls Jump"),
    (0x164, 0x4, "uint", "Ranger's Helicopter Operation Controls Attack 1"),
    (0x168, 0x4, "uint", "Ranger's Helicopter Operation Controls Attack 2"),
    (0x16C, 0x4, "uint", "Ranger's Helicopter Operation Controls Fly"),
    (0x174, 0x2C4, "null", "Spacer for Ranger's Controls\n"),

    (0x4C0, 0x4, "uint", "Wingdiver's Controls Attack"),
    (0x4C4, 0x4, "uint", "Wingdiver's Controls Zoom / Activate"),
    (0x4C8, 0x4, "uint", "Wingdiver's Controls Jump / Ascend"),
    (0x4CC, 0x4, "uint", "Wingdiver's Controls Switch Weapons"),
    (0x4D0, 0x4, "uint", "Wingdiver's Controls Reload"),
    (0x4D4, 0x4, "uint", "Wingdiver's Controls Boost"),

    (0x4D8, 0x4, "unknown", "Wingdiver's Controls unknown (Possibly )"),
    (0x4DC, 0x4, "uint", "Wingdiver's Controls Use Independently Operated Equipment"),

    (0x500, 0x4, "uint", "Wingdiver's Vehicle (B) Operation Controls Accelerate"),
    (0x504, 0x4, "uint", "Wingdiver's Vehicle (B) Operation Controls Brake / Reverse"),
    (0x508, 0x4, "uint", "Wingdiver's Vehicle (B) Operation Controls Handbrake"),
    (0x50C, 0x4, "uint", "Wingdiver's Vehicle (B) Operation Controls Attack 1"),
    (0x510, 0x4, "uint", "Wingdiver's Vehicle (B) Operation Controls Attack 2"),
    (0x56C, 0x4, "uint", "Wingdiver's Vehicle (B) Operation Controls Horn"),
    (0x514, 0x4, "uint", "Wingdiver's Combat Vehicle Operation Controls Attack 1"),
    (0x518, 0x4, "uint", "Wingdiver's Combat Vehicle Operation Controls Attack 2"),
    (0x51C, 0x4, "uint", "Wingdiver's Combat Vehicle Operation Horn"),
    (0x520, 0x4, "uint", "Wingdiver's Combat Frame Operation Controls Attack - Right Hand"),
    (0x524, 0x4, "uint", "Wingdiver's Combat Frame Operation Controls Attack - Left Hand"),
    (0x528, 0x4, "uint", "Wingdiver's Combat Frame Operation Controls Attack - Right Shoulder"),
    (0x52C, 0x4, "uint", "Wingdiver's Combat Frame Operation Controls Attack - Left Shoulder"),
    (0x530, 0x4, "uint", "Wingdiver's Combat Frame Operation Controls Jump"),
    (0x534, 0x4, "uint", "Wingdiver's Barga Operation Controls Punch - Right Hand"),
    (0x538, 0x4, "uint", "Wingdiver's Barga Operation Controls Punch - Left Hand"),
    (0x53C, 0x4, "uint", "Wingdiver's Barga Operation Controls Stamp - Right Foot"),
    (0x540, 0x4, "uint", "Wingdiver's Barga Operation Controls Stamp - Left Foot"),
    (0x544, 0x4, "uint", "Wingdiver's Barga Operation Controls Special Pose"),
    (0x548, 0x4, "uint", "Wingdiver's Barga Operation Controls Special Attack"),
    (0x54C, 0x4, "uint", "Wingdiver's Depth Crawler Operation Controls Bombard - Right"),
    (0x550, 0x4, "uint", "Wingdiver's Depth Crawler Operation Controls Bombard - Left"),
    (0x554, 0x4, "uint", "Wingdiver's Depth Crawler Operation Controls Gatling"),
    (0x558, 0x4, "uint", "Wingdiver's Depth Crawler Operation Controls Emergency Avoidance"),
    (0x55C, 0x4, "uint", "Wingdiver's Depth Crawler Operation Controls Jump"),
    (0x560, 0x4, "uint", "Wingdiver's Helicopter Operation Controls Attack - Right"),
    (0x564, 0x4, "uint", "Wingdiver's Helicopter Operation Controls Attack - Left"),
    (0x568, 0x4, "uint", "Wingdiver's Helicopter Operation Controls Fly"),
    (0x570, 0x2C4, "null", "Spacer for Wingdiver's Controls\n"),

    (0x8BC, 0x4, "uint", "Air Raider's Operation Controls Attack"),
    (0x8C0, 0x4, "uint", "Air Raider's Operation Controls Zoom / Activate"),
    (0x8C4, 0x4, "uint", "Air Raider's Operation Controls Jump"),
    (0x8C8, 0x4, "uint", "Air Raider's Operation Controls Switch Weapons"),
    (0x8CC, 0x4, "uint", "Air Raider's Operation Controls Reload"),
    (0x8D0, 0x4, "unknown", "unknown"),
    (0x8D4, 0x4, "uint", "Air Raider's Operation Controls Call Vehicle Dropoff"),
    (0x8D8, 0x4, "uint", "Air Raider's Operation Controls Use Backpack Tools"),
    (0x8DC, 0x4, "unknown", "unknown"),
    (0x8E0, 0x4, "unknown", "unknown"),
    (0x8E4, 0x4, "unknown", "unknown"),
    (0x8E8, 0x4, "unknown", "unknown"),
    (0x8EC, 0x4, "unknown", "unknown"),
    (0x8F0, 0x4, "unknown", "unknown"),
    (0x8F4, 0x4, "unknown", "unknown"),
    (0x8F8, 0x4, "unknown", "unknown"),
    (0x8FC, 0x4, "uint", "Air Raider's Vehicle (B) Operation Controls Accelerate"),
    (0x900, 0x4, "uint", "Air Raider's Vehicle (B) Operation Controls Brake / Reverse"),
    (0x904, 0x4, "uint", "Air Raider's Vehicle (B) Operation Controls Handbrake"),
    (0x908, 0x4, "uint", "Air Raider's Vehicle (B) Operation Controls Attack 1"),
    (0x90C, 0x4, "uint", "Air Raider's Vehicle (B) Operation Controls Attack 2"),
    (0x968, 0x4, "uint", "Air Raider's Vehicle (B) Operation Controls Horn"),
    (0x910, 0x4, "uint", "Air Raider's Combat Vehicle Operation Controls Attack 1"),
    (0x914, 0x4, "uint", "Air Raider's Combat Vehicle Operation Controls Attack 2"),
    (0x918, 0x4, "uint", "Air Raider's Combat Vehicle Operation Horn"),
    (0x91C, 0x4, "uint", "Air Raider's Combat Frame Operation Controls Attack - Right Hand"),
    (0x920, 0x4, "uint", "Air Raider's Combat Frame Operation Controls Attack - Left Hand"),
    (0x924, 0x4, "uint", "Air Raider's Combat Frame Operation Controls Attack - Right Shoulder"),
    (0x928, 0x4, "uint", "Air Raider's Combat Frame Operation Controls Attack - Left Shoulder"),
    (0x92C, 0x4, "uint", "Air Raider's Combat Frame Operation Controls Jump"),
    (0x930, 0x4, "uint", "Air Raider's Barga Operation Controls Punch - Right Hand"),
    (0x934, 0x4, "uint", "Air Raider's Barga Operation Controls Punch - Left Hand"),
    (0x938, 0x4, "uint", "Air Raider's Barga Operation Controls Stamp - Right Foot"),
    (0x93C, 0x4, "uint", "Air Raider's Barga Operation Controls Stamp - Left Foot"),
    (0x940, 0x4, "uint", "Air Raider's Barga Operation Controls Special Pose"),
    (0x944, 0x4, "uint", "Air Raider's Barga Operation Controls Special Attack"),
    (0x948, 0x4, "uint", "Air Raider's Depth Crawler Operation Controls Bombard - Right"),
    (0x94C, 0x4, "uint", "Air Raider's Depth Crawler Operation Controls Bombard - Left"),
    (0x950, 0x4, "uint", "Air Raider's Depth Crawler Operation Controls Gatling"),
    (0x954, 0x4, "uint", "Air Raider's Depth Crawler Operation Controls Emergency Avoidance"),
    (0x958, 0x4, "uint", "Air Raider's Depth Crawler Operation Controls Jump"),
    (0x95C, 0x4, "uint", "Air Raider's Helicopter Operation Controls Attack - Right"),
    (0x960, 0x4, "uint", "Air Raider's Helicopter Operation Controls Attack - Left"),
    (0x964, 0x4, "uint", "Air Raider's Helicopter Operation Controls Fly"),
    (0x96C, 0x2C4, "null", "Spacer for Air Raider's Controls\n"),

    (0xCD8, 0x4, "uint", "Fencer's Controls Attack - Right Hand"),
    (0xCDC, 0x4, "uint", "Fencer's Controls Attack - Left Hand"),
    (0xCE0, 0x4, "uint", "Fencer's Controls Use Equipment - Right Hand"),
    (0xCE4, 0x4, "uint", "Fencer's Controls Use Equipment - Left Hand"),
    (0xCE8, 0x4, "uint", "Fencer's Controls Jump"),
    (0xCEC, 0x4, "uint", "Fencer's Controls Switch Weapons"),
    (0xCF0, 0x4, "uint", "Fencer's Controls Reload"),
    (0xCF4, 0x4, "uint", "Fencer's Controls Reload Shield"),
    (0xCF8, 0x4, "uint", "Fencer's Vehicle (B) Operation Controls Accelerate"),
    (0xCFC, 0x4, "uint", "Fencer's Vehicle (B) Operation Controls Brake / Reverse"),
    (0xD00, 0x4, "uint", "Fencer's Vehicle (B) Operation Controls Handbrake"),
    (0xD04, 0x4, "uint", "Fencer's Vehicle (B) Operation Controls Attack 1"),
    (0xD08, 0x4, "uint", "Fencer's Vehicle (B) Operation Controls Attack 2"),
    (0xD64, 0x4, "uint", "Fencer's Vehicle (B) Operation Controls Horn"),
    (0xD0C, 0x4, "uint", "Fencer's Combat Vehicle Operation Controls Attack 1"),
    (0xD10, 0x4, "uint", "Fencer's Combat Vehicle Operation Controls Attack 2"),
    (0xD14, 0x4, "uint", "Fencer's Combat Vehicle Operation Horn"),
    (0xD18, 0x4, "uint", "Fencer's Combat Frame Operation Controls Attack - Right Hand"),
    (0xD1C, 0x4, "uint", "Fencer's Combat Frame Operation Controls Attack - Left Hand"),
    (0xD20, 0x4, "uint", "Fencer's Combat Frame Operation Controls Attack - Right Shoulder"),
    (0xD24, 0x4, "uint", "Fencer's Combat Frame Operation Controls Attack - Left Shoulder"),
    (0xD28, 0x4, "uint", "Fencer's Combat Frame Operation Controls Jump"),
    (0xD2C, 0x4, "uint", "Fencer's Barga Operation Controls Punch - Right Hand"),
    (0xD30, 0x4, "uint", "Fencer's Barga Operation Controls Punch - Left Hand"),
    (0xD34, 0x4, "uint", "Fencer's Barga Operation Controls Stamp - Right Foot"),
    (0xD38, 0x4, "uint", "Fencer's Barga Operation Controls Stamp - Left Foot"),
    (0xD3C, 0x4, "uint", "Fencer's Barga Operation Controls Special Pose"),
    (0xD40, 0x4, "uint", "Fencer's Barga Operation Controls Special Attack"),
    (0xD44, 0x4, "uint", "Fencer's Depth Crawler Operation Controls Bombard - Right"),
    (0xD48, 0x4, "uint", "Fencer's Depth Crawler Operation Controls Bombard - Left"),
    (0xD4C, 0x4, "uint", "Fencer's Depth Crawler Operation Controls Gatling"),
    (0xD50, 0x4, "uint", "Fencer's Depth Crawler Operation Controls Emergency Avoidance"),
    (0xD54, 0x4, "uint", "Fencer's Depth Crawler Operation Controls Jump"),
    (0xD58, 0x4, "uint", "Fencer's Helicopter Operation Controls Attack - Right"),
    (0xD5C, 0x4, "uint", "Fencer's Helicopter Operation Controls Attack - Left"),
    (0xD60, 0x4, "uint", "Fencer's Helicopter Operation Controls Fly"),
    (0xD68, 0x2C4, "null", "Spacer for Fencer's Controls\n"),
    (0x102C, 0xC8, "unknown", "unknown structure\n"),
    (0x10F4, 0x334, "null", "unknown structure padding\n"),
    (0x1428, 0xC8, "unknown", "unknown structure 2\n"),
    (0x14F0, 0x334, "null", "unknown structure 2 padding\n"),
    (0x1824, 0xC8, "unknown", "unknown structure 3\n"),
    (0x18EC, 0x334, "null", "unknown structure 3 padding\n"),
    (0x1C20, 0xC8, "unknown", "unknown structure 4\n"),
    (0x1CE8, 0x334, "null", "unknown structure 4 padding\n"),
    (0x2014, 0xD0, "unknown", "unknown structure 5 header\n"),
    (0x20E4, 0x334, "null", "unknown structure 5 padding\n"),
    (0x2418, 0xC8, "unknown", "unknown structure 6 header\n"),
    (0x24E0, 0x334, "null", "unknown structure 6 padding\n"),

    (0x2814, 0x2800, "bytes", "Default Settings for all Classes Body\n"),


    (0x5014, 0x20, "str", "Save Profile Name\n", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 16 characters max with padding\n"
    }),
    (0x5034, 0x4, "null", "Save name spacer"),
    (0x5038, 0x4, "uint", "Emote Wheel Slot Compass North Menu 1"),
    (0x503C, 0x4, "uint", "Emote Wheel Slot Compass North Menu 2"),
    (0x5040, 0x4, "uint", "Emote Wheel Slot Compass North Menu 3"),
    (0x5044, 0x40, "bytes", "Emote Wheel Slot Compass North Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x5084, 0x40, "null", "Spacer for North to North East"),
    (0x50C4, 0x4, "uint", "Emote Wheel Slot Compass North East Menu 1"),
    (0x50C8, 0x4, "uint", "Emote Wheel Slot Compass North East Menu 2"),
    (0x50CC, 0x4, "uint", "Emote Wheel Slot Compass North East Menu 3"),
    (0x50D0, 0x40, "bytes", "Emote Wheel Slot Compass North East Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x5110, 0x40, "null", "Spacer for North East to East"),
    (0x5150, 0x4, "uint", "Emote Wheel Slot Compass East Menu 1"),
    (0x5154, 0x4, "uint", "Emote Wheel Slot Compass East Menu 2"),
    (0x5158, 0x4, "uint", "Emote Wheel Slot Compass East Menu 3"),
    (0x515C, 0x40, "bytes", "Emote Wheel Slot Compass East Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x519C, 0x40, "null", "Spacer for East to South East"),
    (0x51DC, 0x4, "uint", "Emote Wheel Slot Compass South East Menu 1"),
    (0x51E0, 0x4, "uint", "Emote Wheel Slot Compass South East Menu 2"),
    (0x51E4, 0x4, "uint", "Emote Wheel Slot Compass South East Menu 3"),
    (0x51E8, 0x40, "bytes", "Emote Wheel Slot Compass South East Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x5228, 0x40, "null", "Spacer for South East to South"),
    (0x5268, 0x4, "uint", "Emote Wheel Slot Compass South Menu 1"),
    (0x526C, 0x4, "uint", "Emote Wheel Slot Compass South Menu 2"),
    (0x5270, 0x4, "uint", "Emote Wheel Slot Compass South Menu 3"),
    (0x5274, 0x40, "bytes", "Emote Wheel Slot Compass South Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x52B4, 0x40, "null", "Spacer for South to South West"),
    (0x52F4, 0x4, "uint", "Emote Wheel Slot Compass South West Menu 1"),
    (0x52F8, 0x4, "uint", "Emote Wheel Slot Compass South West Menu 2"),
    (0x52FC, 0x4, "uint", "Emote Wheel Slot Compass South West Menu 3"),
    (0x5300, 0x40, "bytes", "Emote Wheel Slot Compass South West Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x5340, 0x40, "null", "Spacer for South West to West"),
    (0x5380, 0x4, "uint", "Emote Wheel Slot Compass West Menu 1"),
    (0x5384, 0x4, "uint", "Emote Wheel Slot Compass West Menu 2"),
    (0x5388, 0x4, "uint", "Emote Wheel Slot Compass West Menu 3"),
    (0x538C, 0x40, "bytes", "Emote Wheel Slot Compass West Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x53CC, 0x40, "null", "Spacer for West to North West"),
    (0x540C, 0x4, "uint", "Emote Wheel Slot Compass North West Menu 1"),
    (0x5410, 0x4, "uint", "Emote Wheel Slot Compass North West Menu 2"),
    (0x5414, 0x4, "uint", "Emote Wheel Slot Compass North West Menu 3"),
    (0x5418, 0x40, "bytes", "Emote Wheel Slot Compass North West Menu Custom Value", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "Decoded as UTF-16, 32 characters max with padding\n",
    }),
    (0x5458, 0x40, "null", "Spacer for North West to End of file flags"),
    (0x5499, 1, "bool", "Camera Effects", lambda v: {
        "value": v,
        "state": "On" if v == 0 else "Off" if v == 1 else "unknown",
        "note": "0 = On, 1 = Off, unknown state"
    }),

    (0x549C, 0x4, "uint", "End of CFG File\n"),

]

DAT_STRUCTURE = [
    (0x00, 0x4, "str", "Header (should be MDB0)"),
    (0x4, 0x4, "uint", "File Version"),
    (0x08, 0x4, "unknown", "unknown"),
    (0x0C, 0x4, "uint", "CRC32 Checksum"),
    (0x10, 0x4, "unknown", "unknown"),
    (0x14, 0x20, "bytes", "Progress achievement flags 00 for not unlocked 01 unlocked, 5% to 100% in order"),
    (0x34, 8, "bytes", "Other achievement flags 00 for not unlocked 01 unlocked, rescue and AP level reached"),
    (0x3C, 160, "null", "Achievements Padding"),
    (0xDC, 0x4, "unknown", "unknown"),
    (0xE0, 0x4, "unknown", "unknown"),
    (0xE4, 0x4, "unknown", "unknown"),
    (0xE8, 0x4, "unknown", "unknown"),
    (0xEC, 0x4, "uint", "Game's Player has started"),
    (0xF0, 0x4, "unknown", "unknown"),
    (0xF4, 0x4, "uint", "Missions Played as Air Raider"),
    (0xF8, 0x4, "unknown", "unknown777777777"),
    (0xFC, 0x4, "uint", "Teleport Device Kills"),
    (0x100, 0x4, "uint", "Total Armor Points Acquired"),
    (0x104, 0x4, "uint", "Android Kills"),
    (0x108, 0x4, "uint", "Super Android Kills"),
    (0x10C, 0x4, "uint", "High Mobility Android Kills"),
    (0x110, 0x4, "uint", "Grenadier Kills"),
    (0x114, 0x4, "uint", "Cyclops Kills"),
    (0x118, 0x4, "uint", "Giant Grenadier Kills"),
    (0x11C, 0x4, "uint", "Giant Android Kills"),
    (0x120, 0x4, "uint", "King Kills"),
    (0x124, 0x4, "unknown", "Unallocated Memory ?"),
    (0x128, 0x4, "uint", "Teleport Ship Kills"),
    (0x12C, 0x4, "uint", "Gamma Kills"),
    (0x130, 0x4, "uint", "Deroys Kills"),
    (0x134, 0x4, "uint", "Giant Tadpole Kills"),
    (0x138, 0x4, "uint", "Tadpole Kills"),
    (0x13C, 0x4, "unknown", "unknown777777777"),
    (0x140, 0x4, "unknown", "unknown777777777"),
    (0x144, 0x4, "unknown", "unknown"),
    (0x148, 0x4, "unknown", "unknown"),
    (0x14C, 0x4, "unknown", "unknown"),
    (0x150, 0x4, "unknown", "unknown"),
    (0x154, 0x4, "unknown", "unknown"),
    (0x158, 0x4, "uint", "Missions Played as Fencer"),
    (0x15C, 0x4, "uint", "Mobile Base, Mothership Kills ????????????"),
    (0x160, 0x4, "uint", "TOTAL TIME PLAYED ON THIS SAVE", lambda v: {
        "hours": v // 0x34bc0,
        "minutes": (v // 0xe10) % 60,
        "seconds": (v // 0x3c) % 60,
        "formatted": f"{v // 0x34bc0}h {(v // 0xe10) % 60}m {(v // 0x3c) % 60}s",
        "note": "Total time in seconds, converted to hours, minutes, and seconds"
    }),
    (0x164, 0x4, "uint", "Colonists Kills"),
    (0x168, 0x4, "uint16", "Species Alpha kills"),
    (0x16C, 0x4, "uint", "Mother Monster kills"),
    (0x170, 0x4, "uint", "Flying Aggressors kills"),
    (0x174, 0x4, "uint", "Queen kills"),
    (0x178, 0x4, "uint", "Beta Kills"),
    (0x17C, 0x4, "uint", "High Grade Drone kills"),
    (0x180, 0x4, "uint", "Drone kills"),
    (0x184, 0x4, "uint", "Cosmonaut kills"),
    (0x188, 0x4, "unknown", "unknown"),
    (0x18C, 0x4, "unknown", "unknown"),
    (0x190, 0x4, "unknown", "unknown"),
    (0x194, 0x4, "unknown", "unknown"),
    (0x198, 0x4, "unknown", "unknown"),
    (0x19C, 0x4, "uint", "Small Hive Kills"),
    (0x1A0, 0x4, "uint", "Imperial Drone Kills"),
    (0x1A4, 0x4, "uint", "Tier 2 Drone Kills"),
    (0x1A8, 0x4, "unknown", "unknown"),
    (0x1AC, 0x4, "uint", "Primer Kills"),
    (0x1B0, 0x4, "uint", "Kruuls Kills"),
    (0x1B4, 0x4, "uint", "Scylla Kills"),
    (0x1B8, 0x4, "uint", "Erginues Kills"),
    (0x1BC, 0x4, "uint", "Archeluses Kills"),
    (0x1C0, 0x4, "uint", "Mobile Base, Mothership Kills ????????????"),
    (0x1C4, 0x4, "uint", "Arnea Kills"),
    (0x1C8, 0x4, "unknown", "unknown"),
    (0x1CC, 0x4, "uint", "Offline Games Started"),
    (0x1D0, 0x4, "uint", "Online Games Started"),
    (0x1D4, 0x4, "unknown", "unknown"),
    (0x1D8, 0x4, "unknown", "unknown"),
    (0x1DC, 0x4, "unknown", "unknown"),
    (0x1E0, 0x4, "unknown", "unknown"),
    (0x1E4, 0x4, "unknown", "unknown"),
    (0x1E8, 0x4, "unknown", "unknown"),
    (0x1EC, 0x4, "unknown", "unknown"),
    (0x1F0, 0x4, "unknown", "unknown"),
    (0x1F4, 0x4, "uint", "Missions Played as Ranger"),
    (0x1F8, 0x4, "uint", "Rescues Done"),
    (0x1FC, 0x4, "uint", "Ring Kills"),
    (0x200, 0x4, "uint", "High Grade Excavators Kills"),
    (0x204, 0x4, "uint", "Excavators Kills"),
    (0x208, 0x4, "uint", "Shield Bearer Kills"),
    (0x20C, 0x4, "uint", "High Grade Tier 3 Drone Kills"),
    (0x210, 0x4, "uint", "Tier 3 Drone Kills"),
    (0x214, 0x4, "uint", "Haze Kills"),
    (0x218, 0x4, "uint", "Teleport Anchor Kills"),
    (0x21C, 0x4, "uint", "Tail Anchor Kills"),
    (0x220, 0x4, "uint", "Kraken Kills"),
    (0x224, 0x4, "uint", "Weapon's Collected Out of 1572 for EDF 6"),
    (0x228, 0x4, "unknown", "unknown"),
    (0x22C, 0x4, "unknown", "unknown"),
    (0x230, 0x4, "unknown", "unknown"),
    (0x234, 0x4, "unknown", "unknown"),
    (0x238, 0x4, "unknown", "unknown"),
    (0x23C, 0x4, "unknown", "unknown"),
    (0x240, 0x4, "unknown", "unknown"),
    (0x244, 0x4, "uint", "Missions Played as Wingdiver"),
    (0x248, 0x1B4, "unknown", "Unallocated Memory"),
]

MST_STRUCTURE = [
    (0x00, 0x4, "str", "Header (should be MDB0)"),
    (0x4, 0x4, "uint", "MST Version (EDF6=3?)"),
    (0x08, 0x4, "unknown", "unknown"),
    (0x0C, 0x4, "uint", "CRC32 Checksum"),
    (0x10, 0x4, "null", "Spacer"),
    (0x14, 0x4, "uint", "Mission Currently On"),
    (0x18, 0x4, "uint", "Difficulty Currently On"),
    (0x1C, 0x200, "bytes", "Ranger Mission Save Table\n", lambda v: {
        "value": v.hex().upper(),
        "note": " Per-byte additive flags: 0x01=Easy, 0x02=Normal, 0x4=Hard, 0x08=Hardest, 0x10=Inferno\n"
    }),
    (0x21C, 0x200, "bytes", "Wing Diver Mission Save Table\n", lambda v: {
        "value": v.hex().upper(),
        "note": " Per-byte additive flags: 0x01=Easy, 0x02=Normal, 0x4=Hard, 0x08=Hardest, 0x10=Inferno\n"
    }),
    (0x41C, 0x200, "bytes", "Air Raider Mission Save Table\n", lambda v: {
        "value": v.hex().upper(),
        "note": " Per-byte additive flags: 0x01=Easy, 0x02=Normal, 0x4=Hard, 0x08=Hardest, 0x10=Inferno\n"
    }),
    (0x61C, 0x200, "bytes", "Fencer Mission Save Table\n", lambda v: {
        "value": v.hex().upper(),
        "note": " Per-byte additive flags: 0x01=Easy, 0x02=Normal, 0x4=Hard, 0x08=Hardest, 0x10=Inferno\n"
    }),
    (0x81C, 0x200, "null", "Spacer"),
    (0xA1C, 0x800, "bytes", "Default Mission tables\n"),
    (0x121C, 0x200, "null", "Spacer\n"),
    (0x141C, 0x28, "str", "Lobby Name\n", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "UTF-16LE, max 20 characters with padding\n"
    }),
    (0x1444, 0x2, "null", "Spacer\n"),
    (0x1446, 0x30, "str", "Open Message Input\n", lambda v: {
        "value": v.decode("utf-16le", errors="replace").rstrip("\x00"),
        "note": "UTF-16LE, max 24 characters with padding\n"
    }),
    (0x1476, 0x2, "null", "Spacer\n"),
    (0x1478, 0x4, "uint", "Select Set Phrase 1 Category\n"),
    (0x147C, 0x4, "uint", "Select Set Phrase 1 Contents\n"),
    (0x1480, 0x4, "uint", "Select Set Phrase 2 Contents\n"),
    (0x1484, 0x4, "uint", "Select Set Phrase 2 Contents\n"),
    (0x1488, 0x4, "int", "Default 1\n"),
    (0x148C, 0x4, "int", "Default 1\n"),
    (0x1490, 0x4, "unknown", "unknown\n"),
    (0x1494, 0x4, "int", "Default 3?\n"),
    (0x1498, 0x4, "int", "0=Everyone, 1=Friends of Participants / Invite Only, 1=Invite Only, 2=Password, 3=RoomNameOnly"),
    (0x149C, 0x8, "str", "Password\n", lambda v: {
        "value": v.decode("utf-8", errors="replace").rstrip("\x00"),
        "note": "UTF-8, max 10 characters with padding\n"
    }),
    (0x14A4, 0x4, "unknown", "unknown\n"),
    (0x14A8, 0x4, "int", "0=Everyone, 2=Friends of Participants / Invite Only, 3=Invite Only, 0=Password, 0=RoomNameOnly"),
    (0x14AC, 0x4, "int", "Default 2?\n"),
    (0x14B0, 0x218, "null", "Tail Spacer"),
    (0x16C8, 0x4, "uint", "TailFlagA (observed 0x01, or 0x0101)"),
    (0x16CC, 0x2, "uint16", "TailFlagB1 (observed 0x0101)"),
    (0x16CE, 0x2, "uint16", "DLC Variant Value (M00=0x9CC9 DLC1=0x7DFB DLC2=0x2BF4)"),
    (0x16D0, 0x8, "null", "Tail Padding / End"),
]

RoomTypeMST = [
    (0x1498, 0x4, "Room ID?", "0=Everyone, 1=Friends of Participants / Invite Only, 1=Invite Only, 2=Password, 3=RoomNameOnly"),
    (0x14A8, 0x4, "Room ID?", "0=Everyone, 2=Friends of Participants / Invite Only, 3=Invite Only, 0=Password, 0=RoomNameOnly"),
]

def generate_hexbm_bookmarks(structure, bookmark_path):
    bookmarks = []
    bookmark_id = 1  # Global ID counter for all bookmarks
    for entry in structure:
        if len(entry) < 4:
            continue
        offset, length, rtype, desc = entry[0:4]
        rest = entry[4:] if len(entry) > 4 else []
        comment = ""
        if rest and isinstance(rest[0], str):
            comment = rest[0]
        elif rest and callable(rest[0]):
            comment = "Processed value with possible note"

        if rtype == "table" and length == 0x6000 and offset == 0x7CFC:  # Specific handling for the large weapon table
            entry_size = 0xC  # 12 bytes per entry: 4-byte float + 8-byte stat levels
            num_entries = length // entry_size
            for i in range(num_entries):
                sub_offset = offset + i * entry_size
                sub_length = entry_size
                sub_name = f"{desc.strip().replace('\n', ' ')} - Entry {i}"
                if i in weapon_names:
                    sub_name += f" : {weapon_names[i]}"
                sub_name += f" [0x{sub_offset:X} - 0x{sub_offset + sub_length - 1:X}]"
                sub_comment = "Average Level (little-endian float, 0x4 bytes), Stat Levels (8 bytes: list of integers 0-100)"
                color = random.randint(0, 0xFFFFFFFF)  # Random color
                bookmarks.append({
                    "color": color,
                    "comment": sub_comment,
                    "id": bookmark_id,
                    "locked": False,
                    "name": sub_name,
                    "region": {
                        "address": sub_offset,
                        "size": sub_length
                    }
                })
                bookmark_id += 1
        else:
            # Standard single bookmark
            name = f"{desc.strip().replace('\n', ' ')} [0x{offset:X} - 0x{offset + length - 1:X}]"
            color = random.randint(0, 0xFFFFFFFF)  # Random color
            bookmarks.append({
                "color": color,
                "comment": comment,
                "id": bookmark_id,
                "locked": False,
                "name": name,
                "region": {
                    "address": offset,
                    "size": length
                }
            })
            bookmark_id += 1

    os.makedirs(os.path.dirname(bookmark_path), exist_ok=True)
    with open(bookmark_path, "w", encoding="utf-8") as f:
        json.dump({"bookmarks": bookmarks}, f, indent=4)
    log(f"[✓] Generated bookmark file: {bookmark_path}")

def parse_structure(file_path, structure, label="File"):
    global parsed_data
    if not os.path.exists(file_path):
        log(f"[!] Cannot parse {label}, file missing: {file_path}")
        return

    file_size = os.path.getsize(file_path)
    log(f"\n[*] Parsing structure: {label} (File size: {file_size} bytes)")
    with open(file_path, "rb") as f:
        # Log hex dump only if 0x7C0C exists in structure with valid length
        if any(len(entry) >= 4 and entry[0] == 0x7C0C for entry in structure):
            if 0x7C0C + 16 <= file_size:  # Ensure hex dump fits
                f.seek(0x7C0C)
                hex_data = f.read(16).hex().upper()
                log(f"  Hex dump at 0x7C0C (first 16 bytes): {hex_data}")
            else:
                log(f"[!] Hex dump at 0x7C0C exceeds file size {file_size}")
            f.seek(0)  # Reset file pointer

        parsed_data[label] = {}
        for entry in structure:
            if len(entry) == 4:
                offset, length, rtype, desc = entry
                process = None
            elif len(entry) == 5:
                offset, length, rtype, desc, process = entry
            else:
                log(f"[!] Invalid entry tuple in structure: {entry}")
                continue

            if offset + length > file_size:
                log(f"[!] Offset 0x{offset:04X} + length 0x{length:X} exceeds file size {file_size}")
                continue

            f.seek(offset)
            data = f.read(length)
            current_pos = f.tell()
            log(f"Debug: Offset 0x{offset:04X}, Expected Length {length}, Actual data length: {len(data)} bytes, File pos after read: {current_pos}")
            if len(data) != length:
                log(f"[!] Warning: Expected {length} bytes at 0x{offset:04X}, got {len(data)} bytes. Retrying...")
                f.seek(offset)  # Reset and retry
                data = f.read(length)
                log(f"Retry: Actual data length: {len(data)} bytes, File pos: {f.tell()}")
                if len(data) != length:
                    log(f"[!] Error: Insufficient data at offset 0x{offset:04X} after retry (expected {length}, got {len(data)} bytes)")
                    continue

            value = data  # Keep raw bytes initially

            if rtype == "null" or rtype == "padding":
                log(f"  Offset 0x{offset:04X}: <{rtype}> ({length} bytes) - {desc}")
                f.seek(offset)
                preview = f.read(min(16, length))
                log(f"    Hex preview: {preview.hex(' ').upper()}")
                continue
            elif rtype == "str" and not process:
                value = data.decode("ascii", errors="replace")  # Decode only if rtype is str and no process
            elif rtype == "uint":
                if len(data) < 4:
                    log(f"[!] Error: Insufficient data at offset 0x{offset:04X} for uint (expected 4, got {len(data)} bytes)")
                    continue
                value = struct.unpack("<I", data)[0]
            elif rtype == "uint8":
                if len(data) < 1:
                    log(f"[!] Error: Insufficient data at offset 0x{offset:04X} for uint8 (expected 1, got {len(data)} bytes)")
                    continue
                value = struct.unpack("B", data)[0]
            elif rtype == "uint16":
                if len(data) < 2:
                    log(f"[!] Error: Insufficient data at offset 0x{offset:04X} for uint16 (expected >=2, got {len(data)} bytes)")
                    continue
                if len(data) > 2:
                    # Gracefully handle entries that specify 4 bytes length for a uint16 field
                    log(f"[i] Warning: uint16 field at 0x{offset:04X} defined with length {len(data)}; using first 2 bytes")
                value = struct.unpack("<H", data[:2])[0]
            elif rtype == "float":
                if len(data) < 4:
                    log(f"[!] Error: Insufficient data at offset 0x{offset:04X} for float (expected 4, got {len(data)} bytes)")
                    continue
                value = struct.unpack("<f", data)[0]
            elif rtype in ["HEX", "bytes"]:
                value = data  # Keep as bytes, process will handle conversion
            elif rtype == "table":
                value = data
            else:
                value = data.hex()

            if process:
                try:
                    result = process(data if rtype == "str" else value)  # Pass raw data for str, processed value for others
                    if isinstance(result, dict):
                        log(f"  Offset 0x{offset:04X}: {result.get('value', value)} ({rtype}) - {desc}")
                        parsed_data[label][f"0x{offset:04X}"] = {
                            "value": result.get('value', value),
                            "type": rtype,
                            "desc": desc.strip(),
                            "result": result
                        }
                        for key, val in result.items():
                            log(f"    {key.capitalize()}: {val}")
                    elif isinstance(result, list):
                        log(f"  Offset 0x{offset:04X}: ({rtype}) - {desc}")
                        parsed_data[label][f"0x{offset:04X}"] = {
                            "value": value,
                            "type": rtype,
                            "desc": desc.strip(),
                            "result": result[:5] if len(result) > 10 else result  # Store first 5 entries for brevity
                        }
                        log(f"    {len(result)} entries (0x{len(value):X} bytes):")
                        for idx, entry in enumerate(result[:5]):
                            log(f"      Entry {idx}: Average Level = {entry['average_level']}, Stat Levels = {entry['stat_levels']}")
                            if entry.get('note'):
                                log(f"        Note: {entry['note']}")
                        if len(result) > 10:
                            log(f"      ... (skipping {len(result) - 10} entries) ...")
                        for idx, entry in enumerate(result[-5:], start=len(result)-5):
                            log(f"      Entry {idx}: Average Level = {entry['average_level']}, Stat Levels = {entry['stat_levels']}")
                            if entry.get('note'):
                                log(f"        Note: {entry['note']}")
                    else:
                        derived = result
                        log(f"  Offset 0x{offset:04X}: {value} ({rtype}) - {desc} → {derived}")
                        parsed_data[label][f"0x{offset:04X}"] = {
                            "value": value,
                            "type": rtype,
                            "desc": desc.strip(),
                            "derived": derived
                        }
                except Exception as e:
                    log(f"[!] Error processing offset 0x{offset:04X}: {e}")
            else:
                log(f"  Offset 0x{offset:04X}: {value} ({rtype}) - {desc}")
                parsed_data[label][f"0x{offset:04X}"] = {
                    "value": value,
                    "type": rtype,
                    "desc": desc.strip()
                }

def compute_coverage(structure, file_end_offset, name=""):
    total_bytes = 0
    documented_bytes = 0
    unknown_bytes = 0
    null_bytes = 0

    for entry in structure:
        if len(entry) < 4:
            continue

        offset = entry[0]
        size = entry[1]
        rtype = entry[2]
        desc = entry[3].lower()

        if not isinstance(offset, int) or not isinstance(size, int):
            continue

        total_bytes += size

        if rtype in ("null", "padding"):
            null_bytes += size
        elif "unknown" in desc:
            unknown_bytes += size
        else:
            documented_bytes += size

    byte_coverage = round((total_bytes / file_end_offset) * 100, 2)
    doc_coverage = round((documented_bytes / file_end_offset) * 100, 2)
    unknown_coverage = round((unknown_bytes / file_end_offset) * 100, 2)
    null_coverage = round((null_bytes / file_end_offset) * 100, 2)

    print(f"\n--- Completion Summary for {name} ---")
    print(f"File range: 0x0 to 0x{file_end_offset:X} ({file_end_offset} bytes)")
    print(f"Total structure bytes mapped: {total_bytes} → {byte_coverage}%")
    print(f"  Documented bytes: {documented_bytes} → {doc_coverage}%")
    print(f"  unknown bytes:    {unknown_bytes} → {unknown_coverage}%")
    print(f"  Null/Padding:     {null_bytes} → {null_coverage}%\n")

    return {
        "total_mapped": total_bytes,
        "byte_coverage": byte_coverage,
        "documented": documented_bytes,
        "doc_coverage": doc_coverage,
        "unknown": unknown_bytes,
        "unknown_coverage": unknown_coverage,
        "null": null_bytes,
        "null_coverage": null_coverage
    }

def compare_mst_tails(decrypt_dir):
    names = ["DEFP_M00.MST", "DEFP_DLC1.MST", "DEFP_DLC2.MST"]
    tail_off = 0x16C8
    tail_len = 16
    blobs = {}
    for n in names:
        p = os.path.join(decrypt_dir, n)
        if not os.path.exists(p): continue
        with open(p, "rb") as f:
            f.seek(tail_off)
            blobs[n] = f.read(tail_len)
    if len(blobs) < 2:
        print("Need at least two MST files to compare.")
        return
    print(f"Tail @0x{tail_off:X} length {tail_len} bytes:")
    for n,b in blobs.items():
        print(f" {n}: {b.hex(' ').upper()}")
    print("Diff positions (byte index : values):")
    for i in range(tail_len):
        vals = {n: b[i] for n,b in blobs.items()}
        if len(set(vals.values())) > 1:
            print(f"  +{i:02}: " + ", ".join(f"{n}={v:02X}" for n,v in vals.items()))

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="EDF6 Save Analysis Script")
    parser.add_argument("--no-imhex", action="store_true", help="Disable launching ImHex")
    args = parser.parse_args()

    open(LOG_FILE, "w").close()
    log("[*] Starting EDF6 save analysis script")

    if not copy_save_data():
        return

    rename_to_previous()

    if not run_decrypt_tool():
        return

    log("[*] Checking file headers...")
    check_file_header(GST_FILE)
    check_file_header(TROPHY_FILE)
    check_file_header(CFG_FILE)
    for mst_name in MST_FILES:
        check_file_header(os.path.join(DECRYPT_DIR, mst_name))

    FILE_STRUCTURES = {
        "MAIN.GST": (GST_FILE, GST_STRUCTURE),
        "COMMON.CFG": (CFG_FILE, CFG_STRUCTURE),
        "TROPHY.DAT": (TROPHY_FILE, DAT_STRUCTURE),
    }
    for mst_name in MST_FILES:
        FILE_STRUCTURES[f"{mst_name}"] = (os.path.join(DECRYPT_DIR, mst_name), MST_STRUCTURE)

    # Add PREVIOUS files if they exist
    if os.path.exists(ALL_WEAPONS_GST_FILE):
        FILE_STRUCTURES["PREVIOUS.GST"] = (ALL_WEAPONS_GST_FILE, GST_STRUCTURE)
        check_file_header(ALL_WEAPONS_GST_FILE)
    if os.path.exists(PREVIOUS_CFG_FILE):
        FILE_STRUCTURES["PREVIOUS.CFG"] = (PREVIOUS_CFG_FILE, CFG_STRUCTURE)
        check_file_header(PREVIOUS_CFG_FILE)
    if os.path.exists(PREVIOUS_DAT_FILE):
        FILE_STRUCTURES["PREVIOUS.DAT"] = (PREVIOUS_DAT_FILE, DAT_STRUCTURE)
        check_file_header(PREVIOUS_DAT_FILE)
    if os.path.exists(PREVIOUS_MST_FILE):
        FILE_STRUCTURES["PREVIOUS.MST"] = (PREVIOUS_MST_FILE, MST_STRUCTURE)
        check_file_header(PREVIOUS_MST_FILE)

    for label, (path, struct_def) in FILE_STRUCTURES.items():
        parse_structure(path, struct_def, label=label)

    global weapon_names
    if os.path.exists(WEAPONTEXT_FILE):
        try:
            with open(WEAPONTEXT_FILE, 'r', encoding='utf-8') as f:
                weapon_data = json.load(f)
            # Extract names assuming structure like {"variables": [], "0": {"value": ["Name"]}, ...}
            for key, val in weapon_data.items():
                if key != "variables" and isinstance(val, dict) and "value" in val and isinstance(val["value"], list) and val["value"]:
                    try:
                        wid = int(key)
                        name = val["value"][0]
                        weapon_names[wid] = name
                    except ValueError:
                        pass
            log(f"[✓] Loaded {len(weapon_names)} weapon names from WEAPONTEXT.EN.json")
        except Exception as e:
            log(f"[!] Error loading WEAPONTEXT.EN.json: {e}")

    # Generate .hexbm files for each parsed file
    log("\n[*] Generating ImHex bookmark files (.hexbm)...")
    hexbm_FILE_STRUCTURES = {
        "MAIN.GST": (GST_FILE, GST_STRUCTURE),
        "COMMON.CFG": (CFG_FILE, CFG_STRUCTURE),
        "TROPHY.DAT": (TROPHY_FILE, DAT_STRUCTURE),
        'DEFP_M00.MST': (os.path.join(DECRYPT_DIR, 'DEFP_M00.MST'), MST_STRUCTURE),
    }
    for label, (path, struct_def) in hexbm_FILE_STRUCTURES.items():
        bookmark_path = path + ".hexbm"
        generate_hexbm_bookmarks(struct_def, bookmark_path)

    # Launch ImHex with all files if enabled
    if not args.no_imhex:
        files_to_open = [path for label, (path, _) in FILE_STRUCTURES.items()]
        if launch_imhex(files_to_open):
            log(f"[✓] ImHex opened with {', '.join(map(os.path.basename, files_to_open))}")
            log("[*] Bookmark files (.hexbm) generated in the decrypted folder. Import them in ImHex via the bookmarks view if supported.")
        else:
            log("[!] Failed to open ImHex with files, Process may already be running or executable not found.")

    # Compute and display coverage summaries
    log("\n[*] Computing coverage summaries...")
    compare_mst_tails(DECRYPT_DIR)

    log("\n[✓] All tasks completed.")

if __name__ == "__main__":
    main()

GST_END = 0xDCF8
CFG_END = 0x54A0
DAT_END = 0x3FC
MST_END = 0x16D8

# Assuming the structures are named as in your message:
compute_coverage(GST_STRUCTURE, GST_END, "GST_STRUCTURE")
compute_coverage(CFG_STRUCTURE, CFG_END, "CFG_STRUCTURE")
compute_coverage(DAT_STRUCTURE, DAT_END, "DAT_STRUCTURE")
compute_coverage(MST_STRUCTURE, MST_END, "MST_STRUCTURE")

