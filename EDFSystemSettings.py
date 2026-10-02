"""System Settings section: edits the game's graphics/screen options in <save root>/SYSTEM/SYSTEMWIN32.CFG.
Offsets mapped 2026-10-02 via in-game before/after diffs (SystemSettingsRE/SYSTEM_SETTINGS_LOG.md).
EDF6, EDF5 and EDF4.1 supported."""
import os, struct
import customtkinter as ctk
from EDFSaveEditorSave_Handler import load_save, save_save, load_save_edf41, save_save_edf41
from EDFSaveEditorLogic import _backup_before_overwrite

SYSCFG_NAME = "SYSTEMWIN32.CFG"
ONOFF = [(0, "OFF"), (1, "ON")]
ANISO = [(0, "Off"), (1, "2x"), (2, "4x"), (3, "8x"), (4, "16x")]
LANGS = [(0, "Japanese"), (1, "English"), (2, "Chinese"), (3, "Korean")]
# key -> (label, struct fmt, options). Row order in the UI follows this list.
ALL_FIELDS = [
    ("aa",       "Anti-aliasing",         "<B", ONOFF),
    ("shadow",   "Shadow",                "<B", ONOFF),
    ("aniso",    "Anisotropic Filtering", "<I", ANISO),
    ("mode",     "Display Mode",          "<I", [(0, "Window Mode"), (1, "Fullscreen"), (2, "Borderless Window")]),
    ("fullscr",  "FullScreen",            "<B", ONOFF),
    ("letter",   "Letter Box",            "<B", ONOFF),
    ("textlang", "Text Language",         "<I", LANGS),
    ("voicelang","Voice Language",        "<I", LANGS),
]
# Per game: key -> offset in decrypted SYSTEMWIN32.CFG, plus resolution W/H offsets.
GAME_LAYOUTS = {
    "EDF6": {"fields": {"aa": 0x18, "shadow": 0x19, "letter": 0x1A, "mode": 0x1C, "aniso": 0x20},
             "res": (0x24, 0x28)},
    # EDF5: header is 12 bytes longer than EDF6. "fullscr" @0x2E is by elimination (only unexplained byte
    # between confirmed AA 0x2C / Shadow 0x2D / LetterBox 0x2F) - not yet seen to change in-game.
    "EDF5": {"fields": {"voicelang": 0x24, "textlang": 0x28, "aa": 0x2C, "shadow": 0x2D,
                        "fullscr": 0x2E, "letter": 0x2F, "aniso": 0x30},
             "res": (0x34, 0x38)},
    # EDF4.1 (EDF4.M folder): all fields confirmed by in-game diffs 2026-10-02. Language menu only offers
    # JA/EN; value 2 (Chinese) is accepted but UI falls back to Japanese, so it isn't offered here.
    "EDF4.1": {"fields": {"aa": 0x18, "shadow": 0x19, "fullscr": 0x1A, "letter": 0x1B,
                          "textlang": 0x20, "voicelang": 0x24, "aniso": 0x38},
               "res": (0x30, 0x34),
               "opts": {"textlang": LANGS[:2], "voicelang": LANGS[:2]}},
}
COMMON_RESOLUTIONS = ["1280x720", "1366x768", "1600x900", "1920x1080", "2560x1080", "2560x1440",
                      "3440x1440", "3840x1600", "3840x2160", "5120x1440", "5120x2880", "7680x4320"]


def _layout_key(app):
    g = _game(app)
    if g.startswith("EDF4"):
        return "EDF4.1"
    return "EDF5" if g.startswith("EDF5") else ("EDF6" if g.startswith("EDF6") else None)


def _opts(layout, key, default):
    return layout.get("opts", {}).get(key, default)


def _read(path, lk):
    return load_save_edf41(path) if lk == "EDF4.1" else load_save(path, game=lk)


def _write(path, data, lk):
    if lk == "EDF4.1":
        save_save_edf41(path, data)
    else:
        save_save(path, data, game=lk)


def _game(app):
    g = app.game_var.get() if hasattr(app, "game_var") else getattr(app, "current_game", "EDF6")
    return str(g).upper()


def find_syscfg_path(app):
    """SYSTEM folder sits beside the saveslotNN folders: <root>/saveslot00/MAIN.GST -> <root>/SYSTEM/SYSTEMWIN32.CFG."""
    roots = []
    cur = getattr(app, "current_file", None)
    if cur:
        roots.append(os.path.dirname(os.path.dirname(cur)))
        roots.append(os.path.dirname(cur))
    d = getattr(app, "default_save_dir", None)
    if d:
        roots += [d, os.path.dirname(d)]
    for r in roots:
        p = os.path.join(r, "SYSTEM", SYSCFG_NAME)
        if os.path.isfile(p):
            return p
    return None


def build_system_settings_section(app, parent):
    content = app.create_collapsible_section(parent, "system_settings_section")
    app.system_settings_content = content
    app._syscfg_path = None
    app._syscfg_data = None

    grid = ctk.CTkFrame(content, fg_color="transparent")
    grid.pack(anchor="w", padx=10, pady=6)
    app._syscfg_vars = {}
    app._syscfg_rows = {}
    row = 0
    for key, label, _fmt, opts in ALL_FIELDS:
        lbl = ctk.CTkLabel(grid, text=label, width=200, anchor="w")
        lbl.grid(row=row, column=0, sticky="w", pady=2)
        var = ctk.StringVar(value=opts[0][1])
        m = ctk.CTkOptionMenu(grid, values=[o[1] for o in opts], variable=var, width=200)
        m.grid(row=row, column=1, sticky="w", pady=2)
        app._syscfg_vars[key] = var
        app._syscfg_rows[key] = (lbl, m)
        row += 1
    _apply_row_visibility(app, "EDF6")
    ctk.CTkLabel(grid, text="Resolution", width=200, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
    app._syscfg_res_var = ctk.StringVar(value="1920x1080")
    res = ctk.CTkComboBox(grid, values=COMMON_RESOLUTIONS, variable=app._syscfg_res_var, width=200)
    res.grid(row=row, column=1, sticky="w", pady=2)
    ctk.CTkLabel(grid, text="(pick or type WxH)", anchor="w").grid(row=row, column=2, sticky="w", padx=6)

    return content


def _apply_row_visibility(app, layout_key):
    fields = GAME_LAYOUTS.get(layout_key, {}).get("fields", {})
    for key, (lbl, m) in app._syscfg_rows.items():
        if key in fields:
            lbl.grid(); m.grid()
        else:
            lbl.grid_remove(); m.grid_remove()


def _status(app, text, color):
    # No on-panel status line any more; log instead (and surface errors via the main save label).
    print(f"[SystemSettings] {text}")


def load_system_settings(app, quiet=True):
    app._syscfg_data = None
    lk = _layout_key(app)
    if lk is None:
        _status(app, f"{_game(app)} system settings not mapped yet.", "orange")
        return False
    path = find_syscfg_path(app)
    if not path:
        _status(app, "SYSTEM\\SYSTEMWIN32.CFG not found - load a save slot first.", "red")
        return False
    try:
        data = bytearray(_read(path, lk))
    except Exception as e:
        _status(app, f"Failed to read {SYSCFG_NAME}: {e}", "red")
        return False
    layout = GAME_LAYOUTS[lk]
    app._syscfg_path, app._syscfg_data, app._syscfg_layout = path, data, lk
    _apply_row_visibility(app, lk)
    for key, _l, fmt, opts in ALL_FIELDS:
        off = layout["fields"].get(key)
        if off is None:
            continue
        opts = _opts(layout, key, opts)
        menu = app._syscfg_rows[key][1]
        try: menu.configure(values=[o[1] for o in opts])
        except Exception: pass
        v = struct.unpack_from(fmt, data, off)[0]
        app._syscfg_vars[key].set(dict(opts).get(v, f"Unknown ({v})"))
    w, h = (struct.unpack_from("<I", data, o)[0] for o in layout["res"])
    app._syscfg_res_var.set(f"{w}x{h}")
    _status(app, f"{lk} system settings loaded from {path}.", "green")
    return True


def save_system_settings(app):
    """Called from the main Save button. Writes only if a value actually changed. Raises on error."""
    if app._syscfg_data is None:
        return False
    lk = app._syscfg_layout
    layout = GAME_LAYOUTS[lk]
    data = bytearray(app._syscfg_data)
    for key, label, fmt, opts in ALL_FIELDS:
        off = layout["fields"].get(key)
        if off is None:
            continue
        opts = _opts(layout, key, opts)
        disp = app._syscfg_vars[key].get()
        rev = {d: v for v, d in opts}
        if disp not in rev:
            continue  # "Unknown (n)" - leave the original value untouched
        struct.pack_into(fmt, data, off, rev[disp])
    try:
        w, h = (int(x) for x in app._syscfg_res_var.get().lower().replace(" ", "").split("x"))
        if not (320 <= w <= 16384 and 240 <= h <= 16384):
            raise ValueError
    except Exception:
        raise ValueError("System Settings: Resolution must be WxH, e.g. 2560x1440.")
    struct.pack_into("<I", data, layout["res"][0], w)
    struct.pack_into("<I", data, layout["res"][1], h)
    if data == app._syscfg_data:
        return False
    _backup_before_overwrite(app._syscfg_path)
    _write(app._syscfg_path, data, lk)
    app._syscfg_data = data
    _status(app, "System settings saved.", "green")
    return True
