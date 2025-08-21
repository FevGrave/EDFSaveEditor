# EDFSaveEditorMain.py
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import filedialog
import json, sys, subprocess, struct, os, hashlib
from tksheet import Sheet
from EDFSaveEditorLogic import *
from EDFSaveEditorSave_Handler import *
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

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

def load_json_safe(path: str, fallback):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return fallback

class SaveEditor(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Initialize language_var early
        self.language_var = ctk.StringVar(value="English")
        # Add current_theme default before loading config
        self.current_theme = 'dark'
        self.current_language = 'en'  # Default language
        self.current_game = "EDF6"  # For future expansion
        # Load translations
        translations_raw = load_json_safe(resource_path('languages.json'), {})
        # Support both original and flattened structures
        if 'EDF6' in translations_raw and 'languages' in translations_raw.get('EDF6', {}):
            self.translations = translations_raw['EDF6']['languages']
        elif 'languages' in translations_raw:
            self.translations = translations_raw['languages']
        else:
            self.translations = {'en': {}}
        # Load weapon names for all languages/games
        self.weapon_names_lang = load_json_safe(resource_path('WeaponNamesLang.json'), {})
        # Load mission names for all languages/games
        self.mission_names_data = load_json_safe(resource_path('MissionNames.json'), {})
        # Build language_map dynamically from translations
        self.language_map = {}
        for lang_code, lang_dict in self.translations.items():
            display_name = lang_dict.get(lang_code, lang_code)
            self.language_map[lang_code] = display_name
        # Also build a reverse map for display name -> code
        self.language_map_reverse = {v: k for k, v in self.language_map.items()}

        # Initialize config attributes BEFORE load_config
        self.config_data = {'language': 'en', 'theme': 'dark'}  # In-memory config fallback
        self.config_file_enabled = not is_frozen()
        # Load config after language_var is initialized
        self.load_config()
        # Apply loaded theme early
        try:
            ctk.set_appearance_mode(self.config_data.get('theme', 'dark'))
            self.current_theme = self.config_data.get('theme', 'dark')
        except Exception:
            pass
        
        # After load_config ensure selector reflects language
        # (language_selector created later; store desired code)
        self._pending_language_code = self.current_language
        # Replace local version variable with instance attribute
        self.version = "--- V 1.0.0"
        self.title(self.translations[self.current_language].get('title', 'EDF Save Editor') + " " + self.version)
        self.geometry("1320x960")
        self.armor_entries = []
        self.base_gain_labels = []
        self.modded_gain_labels = []
        self.loadout_entries = []
        self.loadout_name_labels = []
        self.current_file = None
        self.weapon_data = []
        self.profile_name_label = None
        self.playtime_label = None
        self.mission_arrays = [bytearray(512) for _ in range(4)]
        self.current_page = 1
        self.missions_per_page = 10
        self.total_missions = 147
        self.total_pages = (self.total_missions + self.missions_per_page - 1) // self.missions_per_page if self.total_missions > 0 else 1
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

        self.colors = ["#1e90ff", "#228b22", "#ffa600", "#ff4500", "#9932cc"]
        self.text_colors = ["#000000", "#000000", "#000000", "#000000", "#000000"]

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.scrollable_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.scrollable_frame.grid(row=0, column=0, sticky="nsew")

        header_frame = ctk.CTkFrame(self.scrollable_frame)
        header_frame.pack(side="top", fill="x", pady=5, padx=10)
        header_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        header_frame.grid_columnconfigure(5, weight=0)  # new column for language selector
        header_frame.grid_rowconfigure(0, weight=1)

        # Game selector replaces old language dropdown
        self.games_metadata = {
            'EDF6': {'total_missions': 147, 'missionlist': 'EDF6', 'missiontable': 'DEFP_M00.MST'},
            'EDF6 DLC1': {'total_missions': 19, 'missionlist': 'EDF6DLC1', 'coming_soon': True}, # 'missiontable': 'DEFP_DLC1.MST'} #Needs connection to  via EDFSaveEditorLogic
            'EDF6 DLC2': {'total_missions': 40, 'missionlist': 'EDF6DLC2', 'coming_soon': True}, # 'missiontable': 'DEFP_DLC2.MST'} #Needs connection to  via EDFSaveEditorLogic
            'EDF5 Offline': {'total_missions': 110, 'coming_soon': True},
            'EDF5 Offline DLC1': {'total_missions': 19, 'coming_soon': True},
            'EDF5 Offline DLC2': {'total_missions': 19, 'coming_soon': True},
            'EDF5 Online': {'total_missions': 111, 'coming_soon': True},            'EDF5 Online DLC1': {'total_missions': 40, 'coming_soon': True},
            'EDF5 Online DLC2': {'total_missions': 40, 'coming_soon': True},
            'EDF4.1 Offline': {'total_missions': 89, 'coming_soon': True},
            'EDF4.1 Online': {'total_missions': 89, 'coming_soon': True}
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
        try: self.update_default_save_dir()
        except Exception: pass

        self.theme_switch = ctk.CTkSwitch(
            header_frame,
            text=self.translations[self.current_language].get('theme_switch', 'Dark Mode'),
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
            text=self.translations[self.current_language].get('save_button', 'Save'),
            command=self.on_save_clicked  # changed to wrapper
        )
        self.save_btn.grid(row=0, column=2, padx=5, sticky="e")

        self.load_btn = ctk.CTkButton(
            header_frame,
            text=self.translations[self.current_language].get('load_button', 'Load Save'),
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
            text=self.translations[self.current_language].get('profile_label', 'Profile:'),
            font=("Arial", 10, "bold")
        ).pack(side="left", padx=2)
        self.profile_name_label = ctk.CTkLabel(self.profile_frame, text=self.translations[self.current_language].get('load_save_info', 'Not Loaded'), font=("Arial", 10))
        self.profile_name_label.pack(side="left", padx=2)

        self.playtime_frame = ctk.CTkFrame(stats_frame)
        self.playtime_frame.grid(row=0, column=1, sticky="e", padx=5)
        ctk.CTkLabel(
            self.playtime_frame,
            text=self.translations[self.current_language].get('playtime_label', 'Playtime:'),
            font=("Arial", 10, "bold")
        ).pack(side="left", padx=2)
        self.playtime_label = ctk.CTkLabel(self.playtime_frame, text=self.translations[self.current_language].get('load_save_info', 'Not Loaded'), font=("Arial", 10))
        self.playtime_label.pack(side="left", padx=2)

        main_content = ctk.CTkFrame(self.scrollable_frame)
        main_content.pack(side="top", fill="both", expand=True, pady=10, padx=10)

        # Armor section (unchanged)
        self.armor_content = self.create_collapsible_section(main_content, "armor_section", height=250)
        self.modded_frame = ctk.CTkFrame(self.armor_content)
        self.modded_frame.pack(pady=10, padx=10, fill="x")
        # Use new modded_multiplier_label key (static label without {value})
        self.modded_multiplier_label_widget = ctk.CTkLabel(
            self.modded_frame,
            text=self.translations[self.current_language].get('modded_multiplier_label', 'Armor Gain Multiplier:'),
            font=("Arial", 12)
        )
        self.modded_multiplier_label_widget.translation_key = 'modded_multiplier_label'
        self.modded_multiplier_label_widget.pack(side="left", padx=5)
        self.modded_gain_entry = ctk.CTkEntry(self.modded_frame, width=100)
        self.modded_gain_entry.pack(side="left", padx=5)
        self.modded_gain_entry.insert(0, "1.0")
        self.modded_gain_entry.bind("<KeyRelease>", lambda e: self.update_armor_display())
        note_label = ctk.CTkLabel(
            self.modded_frame,
            text=self.translations[self.current_language].get('modded_gain_note', 'Modded Values may not be exact due to floating-point precision'),
            font=("Arial", 10, "italic")
        )
        note_label.translation_key = 'modded_gain_note'
        note_label.pack(side="left", padx=10)

        # Replace armor rows creation to tag labels
        for i in range(4):
            frame = ctk.CTkFrame(self.armor_content)
            frame.pack(pady=5, padx=10, fill="x")
            class_name = PLAYER_CLASS_MAP[i]
            armor_label_key = f"{class_name.lower().replace(' ', '_')}_armor_label"  # FIX: ensure underscore for Air Raider
            armor_label = ctk.CTkLabel(frame, text=self.translations[self.current_language].get(armor_label_key, f'{class_name} MAX Armor:'), font=("Arial", 12, "bold"))
            armor_label.translation_key = armor_label_key
            armor_label.pack(side="left", padx=10)
            total_label_key = 'total_armor_label'
            total_label = ctk.CTkLabel(frame, text=self.translations[self.current_language].get(total_label_key, 'Total You Really Have:'), font=("Arial", 12))
            total_label.translation_key = total_label_key
            total_label.pack(side="left", padx=5)
            entry = ctk.CTkEntry(frame, width=100)
            entry.pack(side="left", padx=5)
            entry.insert(0, "0")
            entry.bind("<KeyRelease>", lambda e: self.update_armor_display())
            self.armor_entries.append(entry)
            inc_button = ctk.CTkButton(frame, text="+100", width=60, command=lambda idx=i: self.adjust_armor(idx, 100))
            inc_button.pack(side="left", padx=5)
            dec_button = ctk.CTkButton(frame, text="-100", width=60, command=lambda idx=i: self.adjust_armor(idx, -100))
            dec_button.pack(side="left", padx=5)
            base_label = ctk.CTkLabel(frame, text=self.translations[self.current_language].get('base_gain_label', 'Base Game Gain: {value}').format(value=0.0), font=("Arial", 12))
            base_label.translation_key = 'base_gain_label'
            base_label.pack(side="left", padx=10)
            self.base_gain_labels.append(base_label)
            modded_label = ctk.CTkLabel(frame, text=self.translations[self.current_language].get('modded_gain_label', 'Modded Armor Gain: {value}').format(value=0.0), font=("Arial", 12))
            modded_label.translation_key = 'modded_gain_label'
            modded_label.pack(side="left", padx=10)
            self.modded_gain_labels.append(modded_label)

        # Loadouts section (updated)
        self.loadout_content = self.create_collapsible_section(main_content, "loadouts_section", height=544)
        self.loadout_grid = ctk.CTkFrame(self.loadout_content)
        self.loadout_grid.pack(fill="both", expand=True, padx=10, pady=10)
        self.loadout_grid.grid_columnconfigure((0, 1), weight=1)
        self.loadout_grid.grid_rowconfigure((0, 1), weight=1)

        row, col = 0, 0
        for class_name, slots in LOADOUT_GROUPS.items():
            class_subframe = ctk.CTkFrame(self.loadout_grid)
            class_subframe.grid(row=row, column=col, pady=5, padx=5, sticky="nsew")
            normalized = class_name.lower().replace(' ', '_')  # ensure Air Raider uses underscores
            class_label_key = f'{normalized}_loadout_label'
            header_label = ctk.CTkLabel(class_subframe, text=self.translations[self.current_language].get(class_label_key, f"{class_name} Loadout:"), font=("Arial", 12, "bold"))
            header_label.translation_key = class_label_key
            header_label.pack(anchor="w", padx=5)
            for slot_index, slot in enumerate(slots):
                slot_desc = slot[3]
                slot_key = f"{normalized}_loadout_slot{slot_index+1}"
                slot_frame = ctk.CTkFrame(class_subframe)
                slot_frame.pack(fill="x", padx=10, pady=2)
                slot_label = ctk.CTkLabel(slot_frame, text=self.translations[self.current_language].get(slot_key, slot_desc) + ":", font=("Arial", 12))
                slot_label.translation_key = slot_key
                slot_label.pack(side="left", padx=5)
                entry = ctk.CTkEntry(slot_frame, width=100)
                entry.pack(side="left", padx=5)
                entry.insert(0, "0")
                entry.bind("<KeyRelease>", lambda e: self.update_loadout_names())
                self.loadout_entries.append(entry)
                name_label = ctk.CTkLabel(slot_frame, text="", font=("Arial", 12))
                name_label.pack(side="left", padx=10)
                self.loadout_name_labels.append(name_label)
            col += 1
            if col == 2:
                col = 0
                row += 1

        # Weapon table section
        self.weapon_content = self.create_collapsible_section(main_content, "weapon_table_section", height=400)
        self.search_entry = ctk.CTkEntry(
            master=self.weapon_content,
            placeholder_text="Search by weapon name...",
            width=300,
            font=("Arial", 14)
        )
        self.search_entry.pack(pady=10, padx=10, fill="x")
        self.search_entry.bind("<KeyRelease>", self.filter_table)
        self.search_placeholder_key = 'search_placeholder'
        self.search_placeholder_value = self.translations.get(self.current_language, {}).get(self.search_placeholder_key, 'Search by weapon name...')
        try:
            # Ensure current placeholder text matches translation
            self.search_entry.configure(placeholder_text=self.search_placeholder_value)
        except Exception:
            pass

        self.tree_frame = tk.Frame(self.weapon_content)
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.update_tree_style()

        # Use translations for column headers
        trans = self.translations.get(self.current_language, self.translations['en'])
        stat_label = trans.get('weapon_table_col_stat', 'Stat')
        columns = [
            trans.get('weapon_table_col_id', 'ID'),
            trans.get('weapon_table_col_name', 'Name'),
            trans.get('weapon_table_col_avg_level', 'Avg Level'),
        ] + [f"{stat_label}{i+1}" for i in range(8)]

        self.tree = ttk.Treeview(
            master=self.tree_frame,
            columns=columns,
            show="headings",
            height=10
        )
        for col in columns:
            self.tree.heading(col, text=col)
        self.tree.column(trans.get('weapon_table_col_id', 'ID'), width=50, anchor="c")
        self.tree.column(trans.get('weapon_table_col_name', 'Name'), width=300, anchor="w")
        self.tree.column(trans.get('weapon_table_col_avg_level', 'Avg Level'), width=80, anchor="c")
        for col in columns[3:]:
            self.tree.column(col, width=50, anchor="c")

        self.vsb = ttk.Scrollbar(master=self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", expand=True, fill="both")

        self.tree.bind("<Double-1>", self.edit_cell)

        # Initialize weapon_data with valid IDs and placeholder data
        self.weapon_data = [[i, "Unknown", 0, 0, 0, 0, 0, 0, 0, 0] for i in range(15)]
        # Populate the weapon table
        for idx, row in enumerate(self.weapon_data):
            self.tree.insert("", "end", iid=str(idx), values=row)
        # Update weapon names in the table
        self.update_weapon_table_names()

        # After creating self.tree and populating weapon_data, update names in the table
        self.update_weapon_table_names()

        # Mission section
        self.mission_content = self.create_collapsible_section(main_content, "mission_table_section", height=510)
        # Header frame for Mission Table and Completion
        header_grid = ctk.CTkFrame(self.mission_content)
        header_grid.pack(fill="x", pady=5)
        header_grid.grid_columnconfigure((0, 1), weight=1)

        # Dynamic completion label uses total_missions * 20 (4 classes * 5 difficulties)
        self.total_possible = self.total_missions * 20
        self.completion_label = ctk.CTkLabel(header_grid, text=f"Completion: 0.00% (0/{self.total_possible})", font=("Arial", 12))
        self.completion_label.grid(row=0, column=1, padx=10, sticky="e")

        # Buttons frame
        buttons_frame = ctk.CTkFrame(self.mission_content)
        buttons_frame.pack(pady=5, fill="x")
        buttons_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Use translated class/difficulty names and shorts for mission table and buttons
        trans = self.translations.get(self.current_language, self.translations['en'])
        classes = [
            trans.get('mission_table_col_ranger', 'Ranger'),
            trans.get('mission_table_col_wingdiver', 'Wingdiver'),
            trans.get('mission_table_col_airraider', 'Air Raider'),
            trans.get('mission_table_col_fencer', 'Fencer')
        ]
        classes_short = [
            trans.get('mission_table_col_ranger_short', 'R'),
            trans.get('mission_table_col_wingdiver_short', 'W'),
            trans.get('mission_table_col_airraider_short', 'A'),
            trans.get('mission_table_col_fencer_short', 'F')
        ]
        diffs = [
            trans.get('mission_table_col_easy', 'Easy'),
            trans.get('mission_table_col_normal', 'Normal'),
            trans.get('mission_table_col_hard', 'Hard'),
            trans.get('mission_table_col_hardest', 'Hardest'),
            trans.get('mission_table_col_inferno', 'Inferno')
        ]
        diffs_short = [
            trans.get('mission_table_col_easy_short', 'Ez'),
            trans.get('mission_table_col_normal_short', 'NL'),
            trans.get('mission_table_col_hard_short', 'HD'),
            trans.get('mission_table_col_hardest_short', 'H+'),
            trans.get('mission_table_col_inferno_short', 'IF')
        ]

        bits = [0x01, 0x02, 0x04, 0x08, 0x10]
        colors = self.colors[:len(diffs)]  # Use defined colors for difficulties
        text_colors = self.text_colors[:len(diffs)]  # Use defined text colors for difficulties

        self.mission_unlock_buttons = [[None for _ in range(len(diffs))] for _ in range(len(classes))]
        self.mission_reset_buttons = [[None for _ in range(len(diffs))] for _ in range(len(classes))]
        self.mission_class_labels = []
        for cl_idx, cl in enumerate(classes):
            class_frame = ctk.CTkFrame(buttons_frame)
            class_frame.grid(row=0, column=cl_idx, sticky="ew", padx=5)
            class_label = ctk.CTkLabel(class_frame, text=cl, font=("Arial", 10, "bold"))
            class_label.pack(fill="x")
            self.mission_class_labels.append(class_label)
            for d_idx, d in enumerate(diffs):
                diff_frame = ctk.CTkFrame(class_frame)
                diff_frame.pack(fill="x")
                unlock_btn = ctk.CTkButton(
                    diff_frame,
                    text=self.translations[self.current_language].get('unlock_button', 'Unlock {difficulty}').format(difficulty=d),
                    fg_color=colors[d_idx],
                    text_color=self.text_colors[d_idx],
                    command=lambda c=cl_idx, di=d_idx: self.unlock_mission(c, di)
                )
                unlock_btn.pack(side="left", expand=True)
                self.mission_unlock_buttons[cl_idx][d_idx] = unlock_btn
                reset_btn = ctk.CTkButton(
                    diff_frame,
                    text=self.translations[self.current_language].get('reset_button', 'Reset {difficulty}').format(difficulty=d),
                    command=lambda c=cl_idx, di=d_idx: self.reset_mission(c, di)
                )
                reset_btn.pack(side="left", expand=True)
                self.mission_reset_buttons[cl_idx][d_idx] = reset_btn

        # Grid for sheet and pagination
        mission_grid = ctk.CTkFrame(self.mission_content)
        mission_grid.pack(fill="both", expand=True, padx=10, pady=5)
        mission_grid.grid_columnconfigure(0, weight=1)
        mission_grid.grid_rowconfigure(0, weight=1)

        sheet_container = ctk.CTkFrame(mission_grid)
        sheet_container.grid(row=0, column=0, sticky="nsew")

        # Updated headers with class names
        headers = ["Mission"]
        for i, cl in enumerate(classes_short):
            for d in diffs_short:
                headers.append(f"{cl} {d}")
            if i < 3:
                headers.append("")

        self.sheet = Sheet(
            sheet_container,
            height=350,
            width=1210,
            show_vertical_scrollbar=False
        )
        self.sheet.pack(expand=True, fill="both")
        self.sheet.headers(headers)

        # Separator columns
        self.sep_cols = []
        self.data_cols = []
        col = 1
        for i in range(4):
            for j in range(5):
                self.data_cols.append(col)
                col += 1
            if i < 3:
                self.sep_cols.append(col)
                col += 1

        self.reset_sheet_formatting()

        self.sheet.readonly_columns(columns=[0] + self.sep_cols)
        self.sheet.enable_bindings(("single_select", "row_select", "column_select", "drag_select", "shift_select", "edit_cell", "copy", "cut", "paste", "delete", "undo", "redo"))

        self.sheet.extra_bindings([("double_click_cell", self.toggle_mission_cell), ("edit_cell", self.on_cell_edit)])

        # In __init__, within the pagination frame setup (around line 330)
        pag_frame = ctk.CTkFrame(mission_grid)
        pag_frame.grid(row=0, column=1, sticky="ns")

        self.prev_btn = ctk.CTkButton(pag_frame, text=self.translations[self.current_language].get('prev_button', 'Prev'), command=self.prev_page)
        self.prev_btn.pack(pady=5, fill="x")

        self.page_label = ctk.CTkLabel(pag_frame, text=self.translations[self.current_language].get('page_label', 'Page {current}/{total}').format(current=self.current_page, total=self.total_pages))
        self.page_label.pack(pady=5, expand=True, fill="both")

        # Add completion cell legend under the page counter
        trans = self.translations.get(self.current_language, self.translations['en'])
        yn_yes = trans.get('mission_table_cell_yes', 'Y')
        yn_no = trans.get('mission_table_cell_no', 'N')
        self.completion_legend_label = ctk.CTkLabel(pag_frame, text=f"{yn_yes}: {trans.get('mission_table_cell_yes_desc', 'Completed')}   {yn_no}: {trans.get('mission_table_cell_no_desc', 'Not Completed')}", font=("Arial", 10, "italic"))
        self.completion_legend_label.pack(pady=2, fill="x")

        self.next_btn = ctk.CTkButton(pag_frame, text=self.translations[self.current_language].get('next_button', 'Next'), command=self.next_page)
        self.next_btn.pack(pady=5, fill="x")

        # Achievements section
        self.achievement_content = self.create_collapsible_section(main_content, "achievements_section", height=1380)
        ach_frame = ctk.CTkFrame(self.achievement_content)
        ach_frame.pack(fill="both", expand=True)
        ach_frame.grid_rowconfigure(0, weight=1)
        ach_frame.grid_columnconfigure(0, weight=1, minsize=600)
        ach_frame.grid_columnconfigure(1, weight=1, minsize=400)
        # Left: Achievements List
        ach_columns = [
            self.translations[self.current_language].get('achievement_table_col_id', 'ID'),
            self.translations[self.current_language].get('achievement_table_col_name', 'Name'),
            self.translations[self.current_language].get('achievement_table_col_unlocked', 'Unlocked')
        ]
        self.ach_tree_frame = tk.Frame(ach_frame, width=600)
        self.ach_tree_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.ach_tree_frame.grid_rowconfigure(0, weight=1)
        self.ach_tree_frame.grid_columnconfigure(0, weight=1)
        ach_vsb = ttk.Scrollbar(master=self.ach_tree_frame, orient="vertical")
        ach_vsb.grid(row=0, column=1, sticky="ns")
        self.ach_tree = ttk.Treeview(
            master=self.ach_tree_frame,
            columns=ach_columns,
            show="headings",
            height=24,
            yscrollcommand=ach_vsb.set
        )
        style = ttk.Style()
        style.configure("Treeview.Heading")#, foreground="#FFFFFF")
        ach_vsb.config(command=self.ach_tree.yview)
        self.ach_tree.grid(row=0, column=0, sticky="nsew")
        self.ach_tree.bind("<Double-1>", self.edit_ach_cell)
        for i, col in enumerate(ach_columns):
            self.ach_tree.heading(col, text=col)
        self.ach_tree_frame.grid_propagate(False)
        # Right: Kill Statistics (static, not scrollable)
        kills_frame = ctk.CTkFrame(ach_frame, width=400)
        kills_frame.grid(row=0, column=1, sticky="nsew")
        kills_frame.grid_columnconfigure(0, weight=1)
        self.kills_box_label = ctk.CTkLabel(kills_frame, text=self.translations[self.current_language].get('kills_box_label', 'Kill Statistics (Read only)'), font=("Arial", 14, "bold"))
        self.kills_box_label.translation_key = 'kills_box_label'
        self.kills_box_label.pack(pady=(0, 5), fill="x")
        self.kill_fields_labels = {}
        self.kill_fields_label_widgets = {}
        self.kill_field_keys = [
            'android_kills','super_android_kills','high_mobility_android_kills','grenadier_kills','cyclops_kills','giant_grenadier_kills','giant_android_kills','king_kills','teleport_ship_kills','gamma_kills','deroys_kills','giant_tadpole_kills','tadpole_kills','colonists_kills','species_alpha_kills','mother_monster_kills','flying_aggressors_kills','queen_kills','beta_kills','high_grade_drone_kills','drone_kills','cosmonaut_kills','small_hive_kills','imperial_drone_kills','tier2_drone_kills','primer_kills','kruuls_kills','scylla_kills','erginues_kills','archeluses_kills','arnea_kills','offline_games_started','online_games_started','rescues_done','ring_kills','high_grade_excavators_kills','excavators_kills','shield_bearer_kills','high_grade_tier3_drone_kills','tier3_drone_kills','haze_kills','teleport_anchor_kills','tail_anchor_kills','kraken_kills','weapons_collected']
        for key in self.kill_field_keys:
            label = self.translations[self.current_language].get(key, key.replace('_', ' ').title())
            row = ctk.CTkFrame(kills_frame)
            row.pack(fill="x", pady=1)
            l = ctk.CTkLabel(row, text=label+":", width=200, anchor="w")
            l.translation_key = key
            l.pack(side="left", fill="x", expand=True)
            v = ctk.CTkEntry(row, width=250, state="readonly")
            v.pack(side="left", padx=2, fill="x", expand=True)
            self.kill_fields_labels[key] = v
            self.kill_fields_label_widgets[key] = l
        self.update_kill_fields()

        # Translation Editor section
        self.translation_content = self.create_collapsible_section(main_content, "translation_section", height=400)
        # Force open the translation (language) section by default
        try:
            if hasattr(self, 'translation_section_content') and hasattr(self, 'translation_section_button'):
                self.translation_section_content.pack(fill="both", expand=True, pady=5, padx=5)
                trans = self.translations.get(self.current_language, self.translations.get('en', {}))
                self.translation_section_button.configure(text=trans.get('translation_section', 'Translation Editor') + " ▼")
        except Exception:
            pass
        # Language dropdown and add button (above segmented button)
        lang_frame = ctk.CTkFrame(self.translation_content)
        lang_frame.pack(fill="x", padx=10, pady=(5, 0))
        self.translation_lang_var = ctk.StringVar(value=self.current_language)
        # Backwards compatibility alias (bug fix for code referencing translation_language_var)
        self.translation_language_var = self.translation_lang_var  # alias
        self.translation_lang_dropdown = ctk.CTkOptionMenu(
            lang_frame,
            values=list(self.translations.keys()),
            variable=self.translation_lang_var,
            command=self.on_translation_lang_change
        )
        self.translation_lang_dropdown.pack(side="left", padx=(0, 10))
        self.add_lang_btn = ctk.CTkButton(
            lang_frame,
            text="Add Language",
            command=self.add_new_language
        )
        self.add_lang_btn.pack(side="left")
        # Segmented button for file selection
        self.translation_tab_var = ctk.StringVar(value="UI Strings")
        self.translation_segmented = ctk.CTkSegmentedButton(
            self.translation_content,
            values=["UI Strings", "Weapon Names", "Mission Names"],
            variable=self.translation_tab_var,
            command=self.update_translation_tab
        )
        self.translation_segmented.pack(padx=10, pady=5, anchor="w")
        # Translation frame (will be updated by update_translation_tab)
        self.translation_frame = ctk.CTkFrame(self.translation_content)
        self.translation_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.update_translation_tab("UI Strings")

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
        unknown = self.translations.get(lang, {}).get('unknown_label', self.translations.get('en', {}).get('unknown_label', 'Unknown'))
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
        except Exception:
            pass
        return unknown

    def get_mission_name(self, mission_id):
        # Helper to fetch mission name via internal missionlist key
        try:
            mid = str(mission_id)
            lang = self.current_language
            mission_key = self.missionlist_key
            block = self.mission_names_data.get(mission_key, {})
            if lang in block and mid in block[lang]:
                return block[lang][mid]
            if 'en' in block and mid in block['en']:
                return block['en'][mid]
        except Exception:
            pass
        return f"Mission {mission_id}"

    def reload_mission_names(self):
        """Reload mission names from disk (using resource_path) and refresh mission table."""
        try:
            # Preserve existing data as fallback
            current = getattr(self, 'mission_names_data', {})
            self.mission_names_data = load_json_safe(resource_path('MissionNames.json'), current)
            # Validate current missionlist_key; fallback if missing
            if self.missionlist_key not in self.mission_names_data:
                fallback = self.games_metadata.get(self.current_game, {}).get('missionlist')
                if fallback and fallback in self.mission_names_data:
                    self.missionlist_key = fallback
        except Exception:
            pass
        # Refresh table if available
        if hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception: pass

    def update_translation_textbox(self, language=None):
        # Use the provided language or the current selection
        if language is None:
            language = self.translation_language_var.get()
        reverse_map = {v: k for k, v in self.language_map.items()}
        lang_code = reverse_map.get(language, None)
        if lang_code is None:
            # Fallback to current_language if dropdown value is not mapped
            lang_code = self.current_language
        translations = self.translations.get(lang_code, {})
        # Format translations as JSON
        json_text = json.dumps(translations, ensure_ascii=False, indent=2)
        self.translation_textbox.delete("1.0", "end")
        self.translation_textbox.insert("1.0", json_text)

    def save_translation(self):
        # Prevent write attempts inside frozen (packaged) builds
        if is_frozen():
            messagebox.showinfo("Read Only", "Cannot save translations while running packaged executable.")
            return
        lang = self.translation_lang_var.get()
        tab = self.translation_tab_var.get()
        json_text = self.translation_textbox.get("1.0", "end").strip()
        try:
            data = json.loads(json_text)
        except Exception as e:
            messagebox.showerror("Error", f"Invalid JSON: {e}")
            return
        if tab == "UI Strings":
            self.translations[lang] = data
            with open(resource_path('languages.json'), 'w', encoding='utf-8') as f:
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
            with open(resource_path('WeaponNamesLang.json'), 'w', encoding='utf-8') as f:
                json.dump(self.weapon_names_lang, f, ensure_ascii=False, indent=2)
        elif tab == "Mission Names":
            mission_key = self.missionlist_key
            if mission_key not in self.mission_names_data:
                self.mission_names_data[mission_key] = {lang: data}
            else:
                self.mission_names_data[mission_key][lang] = data
            with open(resource_path('MissionNames.json'), 'w', encoding='utf-8') as f:
                json.dump(self.mission_names_data, f, ensure_ascii=False, indent=2)
            # Ensure in-memory reload to reflect any external structure adjustments
            self.reload_mission_names()
        messagebox.showinfo("Saved", f"{tab} for '{lang}' saved.")
        self.update_translation_tab()

    def save_config(self):
        self.config_data['language'] = self.current_language
        # Persist current theme
        try:
            self.config_data['theme'] = 'dark' if ctk.get_appearance_mode().lower() == 'dark' else 'light'
        except Exception:
            # Fallback to switch state if appearance_mode unavailable
            try:
                self.config_data['theme'] = 'dark' if self.theme_switch.get() else 'light'
            except Exception:
                pass
        if self.config_file_enabled:
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f)
        # else: do nothing, keep in-memory only

    def load_config(self):
        if self.config_file_enabled:
            try:
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.current_language = config.get('language', 'en')
                self.language_var.set(self.language_map.get(self.current_language, "English"))
                # Load theme
                self.config_data['theme'] = config.get('theme', 'dark')
                self.current_theme = self.config_data['theme']
            except (FileNotFoundError, json.JSONDecodeError):
                self.current_language = 'en'
                self.language_var.set("English")
        else:
            self.current_language = self.config_data.get('language', 'en')
            self.language_var.set(self.language_map.get(self.current_language, "English"))
            self.current_theme = self.config_data.get('theme', 'dark')

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
            except Exception: pass
        if hasattr(self, 'language_selector'):
            try: self.language_selector.set(lang_code)
            except Exception: pass
        try: self.update_ui_text()
        except Exception: pass
        if hasattr(self, 'update_weapon_table_headers'):
            try: self.update_weapon_table_headers()
            except Exception: pass
        if hasattr(self, 'update_weapon_table_names'):
            try: self.update_weapon_table_names()
            except Exception: pass
        if hasattr(self, 'refresh_armor_labels'):
            try: self.refresh_armor_labels()
            except Exception: pass
        if hasattr(self, 'refresh_loadout_labels'):
            try: self.refresh_loadout_labels()
            except Exception: pass
        if hasattr(self, 'update_loadout_names'):
            try: self.update_loadout_names()
            except Exception: pass
        if hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception: pass
        if hasattr(self, 'update_achievement_table'):
            try: self.update_achievement_table()
            except Exception: pass
        if hasattr(self, 'refresh_kill_labels'):
            try: self.refresh_kill_labels()
            except Exception: pass
        try: update_displays(self)
        except Exception: pass
        if hasattr(self, 'filter_table'):
            try: self.filter_table()
            except Exception: pass
        try: self.update_search_placeholder()
        except Exception: pass
        if hasattr(self, 'update_translation_tab'):
            try: self.update_translation_tab()
            except Exception: pass
        self.save_config()

    def update_ui_text(self):
        trans = self.translations.get(self.current_language, self.translations.get('en', {}))
        # Title
        try:
            base_title = trans.get('title', 'EDF Save Editor')
            if hasattr(self, 'version'):
                self.title(f"{base_title} {self.version}")
            else:
                self.title(base_title)
        except Exception:
            pass
        # Buttons / switches
        if hasattr(self, 'save_btn'): self.save_btn.configure(text=trans.get('save_button', 'Save'))
        if hasattr(self, 'load_btn'): self.load_btn.configure(text=trans.get('load_button', 'Load Save'))
        if hasattr(self, 'theme_switch'): self.theme_switch.configure(text=trans.get('theme_switch', 'Dark Mode'))
        # Static labels for profile/playtime headers only (do NOT overwrite current values)
        if hasattr(self, 'profile_frame'):
            for child in self.profile_frame.winfo_children():
                if isinstance(child, ctk.CTkLabel) and child is not self.profile_name_label:
                    child.configure(text=trans.get('profile_label', 'Profile:'))
        if hasattr(self, 'playtime_frame'):
            for child in self.playtime_frame.winfo_children():
                if isinstance(child, ctk.CTkLabel) and child is not self.playtime_label:
                    child.configure(text=trans.get('playtime_label', 'Playtime:'))
        # Pagination / navigation
        if hasattr(self, 'prev_btn'): self.prev_btn.configure(text=trans.get('prev_button', 'Prev'))
        if hasattr(self, 'next_btn'): self.next_btn.configure(text=trans.get('next_button', 'Next'))
        if hasattr(self, 'page_label'): self.page_label.configure(text=trans.get('page_label', 'Page {current}/{total}').format(current=self.current_page, total=self.total_pages))
        # Search placeholder
        if hasattr(self, 'search_entry'):
            try: self.search_entry.configure(placeholder_text=trans.get('search_placeholder', 'Search by weapon name...'))
            except Exception: pass
        # Mission completion legend
        if hasattr(self, 'completion_legend_label'):
            yn_yes = trans.get('mission_table_cell_yes', 'Y'); yn_no = trans.get('mission_table_cell_no', 'N')
            self.completion_legend_label.configure(text=f"{yn_yes}: {trans.get('mission_table_cell_yes_desc', 'Completed')}   {yn_no}: {trans.get('mission_table_cell_no_desc', 'Not Completed')}")
        # Kill stats box (container label) handled here; individual kill labels handled in refresh_kill_labels
        if hasattr(self, 'kills_box_label'):
            try:
                self.kills_box_label.configure(text=trans.get(getattr(self.kills_box_label, 'translation_key', 'kills_box_label'), 'Kill Statistics (Read only)'))
            except Exception:
                pass
        # Section toggle buttons (use translation_key if present)
        for key in ['armor_section','loadouts_section','weapon_table_section','mission_table_section','achievements_section','translation_section']:
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
                        child.configure(text=trans.get('save_paths_info', 'Copy these EDF save directories (may adjust per install):'))
                    elif isinstance(child, ctk.CTkFrame):
                        for w in child.winfo_children():
                            if isinstance(w, ctk.CTkButton) and w.cget('text') in ('Copy', self.translations.get('en', {}).get('copy_button', 'Copy')):
                                w.configure(text=trans.get('copy_button', 'Copy'))
            except Exception:
                pass
        # Refresh dependent labels
        try: self.refresh_armor_labels()
        except Exception: pass
        try: self.refresh_loadout_labels()
        except Exception: pass
        try: self.refresh_mission_labels()
        except Exception: pass
        try: self.refresh_kill_labels()
        except Exception: pass

    def refresh_armor_labels(self):
        trans = self.translations.get(self.current_language, {})
        # Update multiplier label
        if hasattr(self, 'modded_multiplier_label_widget'):
            self.modded_multiplier_label_widget.configure(text=trans.get('modded_multiplier_label', 'Armor Gain Multiplier:'))
        # Update note label
        for child in self.modded_frame.winfo_children():
            if isinstance(child, ctk.CTkLabel) and getattr(child, 'translation_key', '') == 'modded_gain_note':
                child.configure(text=trans.get('modded_gain_note', 'Modded Values may not be exact due to floating-point precision'))
        # Update armor rows
        idx = 0
        for frame in self.armor_content.winfo_children():
            if frame is self.modded_frame:
                continue
            labels = [w for w in frame.winfo_children() if isinstance(w, ctk.CTkLabel)]
            if len(labels) < 2:
                continue
            class_name = PLAYER_CLASS_MAP[idx]
            # First label = armor label
            labels[0].configure(text=trans.get(f'{class_name.lower().replace(" ", "_")}_armor_label', f'{class_name} MAX Armor:'))
            # Second label = total armor label
            labels[1].configure(text=trans.get('total_armor_label', 'Total You Really Have:'))
            # Base / modded gain labels if present
            for lab in labels[2:]:
                key = getattr(lab, 'translation_key', '')
                if key == 'base_gain_label':
                    # Preserve numeric value portion after last space
                    try:
                        value_part = lab.cget('text').split(':')[-1]
                        lab.configure(text=trans.get('base_gain_label', 'Base Game Gain: {value}').format(value=value_part.strip()))
                    except Exception:
                        lab.configure(text=trans.get('base_gain_label', 'Base Game Gain: {value}').format(value=0.0))
                elif key == 'modded_gain_label':
                    try:
                        value_part = lab.cget('text').split(':')[-1]
                        lab.configure(text=trans.get('modded_gain_label', 'Modded Armor Gain: {value}').format(value=value_part.strip()))
                    except Exception:
                        lab.configure(text=trans.get('modded_gain_label', 'Modded Armor Gain: {value}').format(value=0.0))
            idx += 1
        # Update completion label pattern if exists
        if hasattr(self, 'completion_label'):
            try: self.update_completion()
            except Exception: pass

    def refresh_loadout_labels(self):
        trans = self.translations.get(self.current_language, {})
        # Iterate through subframes matching LOADOUT_GROUPS order
        subframes = self.loadout_grid.winfo_children()
        for (class_name, slots), frame in zip(LOADOUT_GROUPS.items(), subframes):
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
        unknown = trans.get('unknown_label', 'Unknown')
        for lbl in getattr(self, 'loadout_name_labels', []):
            if not lbl.cget('text') or lbl.cget('text') in ('Unknown', self.translations.get('en', {}).get('unknown_label', 'Unknown')):
                lbl.configure(text=unknown)

    def refresh_mission_labels(self):
        """Update mission table class labels, difficulty button texts, and unlock/reset buttons for current language."""
        if not hasattr(self, 'mission_class_labels'):
            return
        trans = self.translations.get(self.current_language, self.translations.get('en', {}))
        classes_full = [
            trans.get('mission_table_col_ranger', 'Ranger'),
            trans.get('mission_table_col_wingdiver', 'Wingdiver'),
            trans.get('mission_table_col_airraider', 'Air Raider'),
            trans.get('mission_table_col_fencer', 'Fencer')
        ]
        diffs_full = [
            trans.get('mission_table_col_easy', 'Easy'),
            trans.get('mission_table_col_normal', 'Normal'),
            trans.get('mission_table_col_hard', 'Hard'),
            trans.get('mission_table_col_hardest', 'Hardest'),
            trans.get('mission_table_col_inferno', 'Inferno')
        ]
        # Update class labels
        for i, lbl in enumerate(self.mission_class_labels):
            try: lbl.configure(text=classes_full[i])
            except Exception: pass
        # Update unlock/reset button texts
        if hasattr(self, 'mission_unlock_buttons') and hasattr(self, 'mission_reset_buttons'):
            for c in range(len(self.mission_unlock_buttons)):
                for d in range(len(self.mission_unlock_buttons[c])):
                    try:
                        ub = self.mission_unlock_buttons[c][d]
                        rb = self.mission_reset_buttons[c][d]
                        if ub:
                            ub.configure(text=trans.get('unlock_button', 'Unlock {difficulty}').format(difficulty=diffs_full[d]))
                        if rb:
                            rb.configure(text=trans.get('reset_button', 'Reset {difficulty}').format(difficulty=diffs_full[d]))
                    except Exception:
                        continue
        # Update sheet headers & data via existing method
        if hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception: pass

    def refresh_kill_labels(self):
        """Update kill statistics labels when language changes."""
        if not hasattr(self, 'kill_fields_label_widgets'):
            return
        trans = self.translations.get(self.current_language, self.translations.get('en', {}))
        for key, widget in self.kill_fields_label_widgets.items():
            try:
                base = trans.get(key, key.replace('_', ' ').title())
                widget.configure(text=base + ':')
            except Exception:
                continue
        if hasattr(self, 'kills_box_label'):
            try: self.kills_box_label.configure(text=trans.get('kills_box_label', 'Kill Statistics (Read only)'))
            except Exception: pass

    def update_weapon_table_headers(self):
        # Update the weapon table (Treeview) column headers to match the current language
        trans = self.translations.get(self.current_language, self.translations['en'])
        stat_label = trans.get('weapon_table_col_stat', 'Stat')
        columns = [
            trans.get('weapon_table_col_id', 'ID'),
            trans.get('weapon_table_col_name', 'Name'),
            trans.get('weapon_table_col_avg_level', 'Avg Level'),
        ] + [f"{stat_label}{i+1}" for i in range(8)]
        # Update headings
        for i, col in enumerate(columns):
            self.tree.heading(f"#{i+1}", text=col)

    def update_weapon_table_names(self):
        # Use fixed column index (second column) regardless of language
        if not hasattr(self, 'tree'):
            return
        name_column_id = self.tree['columns'][1]  # stable by index
        unknown = self.translations.get(self.current_language, {}).get('unknown_label', self.translations.get('en', {}).get('unknown_label', 'Unknown'))
        for idx, row in enumerate(self.weapon_data):
            try:
                weapon_id = str(row[0])
                name = self.get_weapon_name(weapon_id)
                if not name:
                    name = unknown
                self.weapon_data[idx][1] = name
                if self.tree.exists(str(idx)):
                    self.tree.set(str(idx), column=name_column_id, value=name)
            except Exception:
                continue
        # After names updated, re-apply filter to reflect any search in progress
        try:
            self.filter_table()
        except Exception:
            pass

    def reset_sheet_formatting(self):
        # Set column widths
        self.sheet.column_width(0, 300)  # Mission column increased
        for col in self.data_cols:
            self.sheet.column_width(col, 34)  # Smaller data columns
        for col in self.sep_cols:
            self.sheet.column_width(col, 4)
        # Highlight columns with class-based colors
        for idx, col in enumerate(self.data_cols):
            d_idx = idx % 5
            self.sheet.highlight_columns(columns=[col], bg=self.colors[d_idx], fg=self.text_colors[d_idx], redraw=False)

        # Alignments
        self.sheet.span(columns=self.data_cols).align("center", redraw=False)
        self.sheet.span(columns=[0]).align("w", redraw=False)
        self.sheet.span(header=True).align("center", redraw=True)

    def create_collapsible_section(self, parent, title_key, height=None):
        outer_frame = ctk.CTkFrame(parent)
        outer_frame.pack(pady=10, fill="x")
        trans = self.translations.get(self.current_language, self.translations['en'])
        btn = ctk.CTkButton(
            outer_frame,
            text=trans.get(title_key, title_key) + " ▶",
            font=("Arial", 14, "bold"),
            command=lambda: self.toggle_collapsible(outer_frame, btn, title_key)
        )
        # Tag button with translation key so generic refresh can find it
        btn.translation_key = title_key
        self.__setattr__(f"{title_key.lower()}_button", btn)
        btn.pack(fill="x")
        content_frame = ctk.CTkFrame(outer_frame)
        if height is not None:
            content_frame.configure(height=height)
            content_frame.pack_propagate(False)
        self.__setattr__(f"{title_key.lower()}_content", content_frame)
        return content_frame

    def toggle_collapsible(self, outer_frame, button, title_key):
        # Always use the current translation for the label
        trans = self.translations.get(self.current_language, self.translations['en'])
        label = trans.get(title_key, title_key)
        content_frame = outer_frame.winfo_children()[1]  # Assuming button is first, content second
        if (content_frame.winfo_ismapped()):
            content_frame.pack_forget()
            button.configure(text=label + " ▶")
        else:
            content_frame.pack(fill="both", expand=True, pady=5, padx=5)
            button.configure(text=label + " ▼")
            if title_key == "mission_table_section":  # Target only the mission section
                self.sheet.refresh(redraw_header=True, redraw_row_index=True)
                self.update_mission_table()
                self.update_completion()
                self.sheet.redraw(True)

    def toggle_theme(self):
        trans = self.translations.get(self.current_language, self.translations['en'])
        if self.theme_switch.get():
            ctk.set_appearance_mode("dark")
            self.current_theme = 'dark'
            self.theme_switch.configure(text=trans.get('theme_switch', 'Dark Mode'))
        else:
            ctk.set_appearance_mode("light")
            self.current_theme = 'light'
            self.theme_switch.configure(text=trans.get('theme_switch_light', 'Light Mode'))
        self.update_tree_style()
        # Save updated theme preference
        try:
            self.save_config()
        except Exception:
            pass

    def update_tree_style(self):
        appearance_mode = ctk.get_appearance_mode()
        style = ttk.Style()
        if (appearance_mode == "Dark"):
            style.configure("Treeview", background="#2a2d2e", foreground="white", fieldbackground="#2a2d2e", bordercolor="gray")
            style.map("Treeview", background=[('selected', "#22559b")], foreground=[('selected', "white")])
            style.configure("Treeview.Heading", background="#333333", foreground="black", relief="flat")
            style.map("Treeview.Heading", background=[('active', "#2a4066")])
        else:
            style.configure("Treeview", background="white", foreground="black", fieldbackground="white", bordercolor="gray")
            style.map("Treeview", background=[('selected', "#add8e6")], foreground=[('selected', "black")])
            style.configure("Treeview.Heading", background="#cccccc", foreground="#333333", relief="flat")
            style.map("Treeview.Heading", background=[('active', "#a3bffa")])

    def update_loadout_names(self):
        unknown = self.translations.get(self.current_language, {}).get('unknown_label', self.translations.get('en', {}).get('unknown_label', 'Unknown'))
        for i, entry in enumerate(self.loadout_entries):
            try:
                id_val = int(entry.get())
                name = self.get_weapon_name(id_val)
                self.loadout_name_labels[i].configure(text=name if name else unknown)
            except ValueError:
                self.loadout_name_labels[i].configure(text=unknown)

    def adjust_armor(self, idx, delta):
        """Increment/decrement armor value for class index idx by delta and refresh derived labels."""
        if 0 <= idx < len(self.armor_entries):
            entry = self.armor_entries[idx]
            try:
                val = int(entry.get() or 0)
            except ValueError:
                val = 0
            val = max(0, val + delta)
            entry.delete(0, "end")
            entry.insert(0, str(val))
            self.update_armor_display()

    def filter_table(self, event=None):
        if not hasattr(self, 'tree'):
            return
        query = self.search_entry.get().strip() if hasattr(self, 'search_entry') else ''
        if query == '' or query == self.search_placeholder_value:
            # Show all
            for item in self.tree.get_children():
                self.tree.reattach(item, '', 'end')
            return
        qlower = query.lower()
        for item in self.tree.get_children():
            values = self.tree.item(item, 'values')
            # ID + Name columns (0,1)
            id_text = str(values[0]).lower() if values else ''
            name_text = str(values[1]).lower() if len(values) > 1 else ''
            if qlower in id_text or qlower in name_text:
                self.tree.reattach(item, '', 'end')
            else:
                self.tree.detach(item)

    def update_search_placeholder(self):
        # Corrected implementation (replaces malformed earlier version if present)
        trans = self.translations.get(self.current_language, {})
        new_placeholder = trans.get(self.search_placeholder_key, 'Search by weapon name...')
        old_placeholder = getattr(self, 'search_placeholder_value', '')
        self.search_placeholder_value = new_placeholder
        if hasattr(self, 'search_entry'):
            try:
                self.search_entry.configure(placeholder_text=new_placeholder)
            except Exception:
                pass
            current_text = self.search_entry.get().strip()
            if current_text in ('', old_placeholder, new_placeholder):
                self.search_entry.delete(0, 'end')
        try:
            self.filter_table()
        except Exception:
            pass

    def edit_cell(self, event):
        # Re-added clean version
        if not hasattr(self, 'tree'):
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
        current_value = self.tree.item(item, 'values')[col_idx]
        edit_entry = ctk.CTkEntry(self.tree_frame)
        edit_entry.place(x=x, y=y, width=w, height=h)
        edit_entry.insert(0, current_value)
        edit_entry.focus()
        def save_edit(event=None):
            new_value = edit_entry.get().strip()
            if new_value == '':
                edit_entry.destroy(); return
            try:
                val = int(new_value)
                if col_idx == 2:
                    if val < 0: raise ValueError
                else:
                    if not 0 <= val <= 255: raise ValueError
                values = list(self.tree.item(item, 'values'))
                values[col_idx] = val
                self.tree.item(item, values=values)
                row_idx = int(item)
                self.weapon_data[row_idx][col_idx] = val
            except ValueError:
                pass
            edit_entry.destroy()
        edit_entry.bind('<Return>', save_edit)
        edit_entry.bind('<FocusOut>', save_edit)

    def edit_ach_cell(self, event):
        # Fixed missing trans assignment and incorrect item update call
        if not hasattr(self, 'ach_tree'):
            return
        item = self.ach_tree.identify_row(event.y)
        column = self.ach_tree.identify_column(event.x)
        if not item or not column:
            return
        col_idx = int(column.replace('#', '')) - 1
        if col_idx != 2:
            return  # Only unlocked column editable
        trans = self.translations.get(self.current_language, self.translations.get('en', {}))
        yn_yes = trans.get('mission_table_cell_yes', 'Y')
        yn_no = trans.get('mission_table_cell_no', 'N')
        old_value = self.ach_tree.item(item, 'values')[col_idx]
        new_value = yn_no if old_value == yn_yes else yn_yes
        values = list(self.ach_tree.item(item, 'values'))
        values[col_idx] = new_value
        self.ach_tree.item(item, values=values)
        try:
            row_idx = int(item)
            self.achievement_data[row_idx][2] = 1 if new_value == yn_yes else 0
        except Exception:
            pass

    def update_achievement_table(self):
        # Use translated achievement names for both progress and other achievements
        trans = self.translations.get(self.current_language, self.translations['en'])
        percentages = list(range(5, 65, 5)) + list(range(62, 102, 2))
        # Progress achievements
        for i in range(32):
            perc = percentages[i]
            # Use the template key for progress achievements
            template = trans.get("achievement_conquest_x", "Conquest {perc}% (Made {perc}% game progress)")
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
        yn_yes = trans.get('mission_table_cell_yes', 'Y')
        yn_no = trans.get('mission_table_cell_no', 'N')
        for child in self.ach_tree.get_children():
            self.ach_tree.delete(child)
        for idx, row in enumerate(self.achievement_data):
            self.ach_tree.insert("", "end", iid=str(idx), values=(row[0], row[1], yn_yes if row[2] else yn_no))
        self.update_kill_fields()
        # Update achievement tab title and box label
        if hasattr(self, 'achievements_section_button'):
            self.achievements_section_button.configure(text=trans.get('achievements_section', 'Achievements') + (" ▼" if self.achievement_content.winfo_ismapped() else " ▶"))
        # Robustly update the Achievements List label
        if hasattr(self, 'ach_tree_frame') and hasattr(self.ach_tree_frame.master, 'master'):
            parent = self.ach_tree_frame.master.master
            for widget in parent.winfo_children():
                if isinstance(widget, ctk.CTkLabel):
                    widget.configure(text=trans.get('achievements_box_label', 'Achievements List'))
                    break
        # Update achievement table headers
        ach_columns = [
            trans.get('achievement_table_col_id', 'ID'),
            trans.get('achievement_table_col_name', 'Name'),
            trans.get('achievement_table_col_unlocked', 'Unlocked')
        ]
        for i, col in enumerate(self.ach_tree['columns']):
            self.ach_tree.heading(col, text=ach_columns[i], anchor='center')
            self.ach_tree.column(col, anchor='center')
        # Set header text color to black for visibility
        style = ttk.Style()
        style.configure("Treeview.Heading")#, foreground="#000000")

    def update_kill_fields(self):
        # Ensure kill fields are always shown, even if value is 0
        if not hasattr(self, 'kill_fields_labels'):
            return
        kill_fields = getattr(self, 'kill_fields', {})
        for key, entry in self.kill_fields_labels.items():
            val = kill_fields.get(key, 0)
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, str(val))
            entry.configure(state="readonly")

    def toggle_mission_cell(self, event=None):
        selected = self.sheet.get_currently_selected()
        if not selected or selected.column == 0:
            return
        r, c = selected.row, selected.column  # 0-based
        if c in self.sep_cols:
            return
        logical_idx = self.data_cols.index(c)
        cl_idx = logical_idx // 5
        d_idx = logical_idx % 5
        miss_idx = (self.current_page - 1) * self.missions_per_page + r
        arr = self.mission_arrays[cl_idx]
        bit = [0x01, 0x02, 0x04, 0x08, 0x10][d_idx]
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
        cl_idx = logical_idx // 5
        d_idx = logical_idx % 5
        miss_idx = (self.current_page - 1) * self.missions_per_page + r
        arr = self.mission_arrays[cl_idx]
        bit = [0x01, 0x02, 0x04, 0x08, 0x10][d_idx]
        new_value = self.sheet.get_cell_data(r, c)
        if new_value.upper() == "Y":
            arr[miss_idx] |= bit
        elif new_value.upper() == "N":
            arr[miss_idx] &= ~bit
        self.update_completion()

    def unlock_mission(self, cl_idx, d_idx):
        bit = [0x01, 0x02, 0x04, 0x08, 0x10][d_idx]
        arr = self.mission_arrays[cl_idx]
        for i in range(self.total_missions):
            arr[i] |= bit
        self.update_mission_table()
        self.update_completion()

    def reset_mission(self, cl_idx, d_idx):
        bit = [0x01, 0x02, 0x04, 0x08, 0x10][d_idx]
        arr = self.mission_arrays[cl_idx]
        for i in range(self.total_missions):
            arr[i] &= ~bit
        self.update_mission_table()
        self.update_completion()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            if hasattr(self, 'page_label'):
                trans = self.translations.get(self.current_language, self.translations.get('en', {}))
                self.page_label.configure(text=trans.get('page_label', 'Page {current}/{total}').format(current=self.current_page, total=self.total_pages))
            self.update_mission_table()

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            if hasattr(self, 'page_label'):
                trans = self.translations.get(self.current_language, self.translations.get('en', {}))
                self.page_label.configure(text=trans.get('page_label', 'Page {current}/{total}').format(current=self.current_page, total=self.total_pages))
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
        trans = self.translations.get(self.current_language, self.translations['en'])
        classes_short = [
            trans.get('mission_table_col_ranger_short', 'R'),
            trans.get('mission_table_col_wingdiver_short', 'W'),
            trans.get('mission_table_col_airraider_short', 'A'),
            trans.get('mission_table_col_fencer_short', 'F')
        ]
        diffs_short = [
            trans.get('mission_table_col_easy_short', 'Ez'),
            trans.get('mission_table_col_normal_short', 'NL'),
            trans.get('mission_table_col_hard_short', 'HD'),
            trans.get('mission_table_col_hardest_short', 'H+'),
            trans.get('mission_table_col_inferno_short', 'IF')
        ]
        headers = [trans.get('mission_table_col_mission', 'Mission')]
        for i, cl in enumerate(classes_short):
            for d in diffs_short:
                headers.append(f"{cl} {d}")
            if i < 3:
                headers.append("")
        self.sheet.headers(headers)
        for m in range(start, end):
            name = self.mission_names.get(str(m+1), f"Mission {m+1}")
            row = [f"{m+1}: {name}"]
            for cl_idx in range(4):
                for d_idx in range(5):
                    bit = [0x01, 0x02, 0x04, 0x08, 0x10][d_idx]
                    yn_yes = trans.get('mission_table_cell_yes', 'Y')
                    yn_no = trans.get('mission_table_cell_no', 'N')
                    row.append(yn_yes if (self.mission_arrays[cl_idx][m] & bit) else yn_no)
                if cl_idx < 3:
                    row.append("")
            data.append(row)
        self.sheet.set_sheet_data(data, redraw=True, reset_row_positions=True)
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
        trans = self.translations.get(self.current_language, self.translations['en'])
        pattern = trans.get('completion_label', 'Completion: {percent:.2f}% ({total}/2940)')
        if '{max}' in pattern:
            try:
                text = pattern.format(percent=percent, total=total, max=self.total_possible)
            except Exception:
                text = f"Completion: {percent:.2f}% ({total}/{self.total_possible})"
        else:
            if '/2940' in pattern:
                pattern = pattern.replace('/2940', f'/{self.total_possible}', 1)
            try:
                text = pattern.format(percent=percent, total=total)
            except Exception:
                text = f"Completion: {percent:.2f}% ({total}/{self.total_possible})"
        if hasattr(self, 'completion_label'):
            self.completion_label.configure(text=text)
        # Update conquest achievements
        percentages = list(range(5, 65, 5)) + list(range(62, 102, 2))
        updated = False
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
            except Exception:
                pass

    def create_achievements_and_killstats_panel(self, parent):
        container = ctk.CTkFrame(parent)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=1)

        # Achievements panel (left)
        ach_frame = ctk.CTkFrame(container)
        ach_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=0)
        ach_frame.grid_rowconfigure(0, weight=1)
        ach_frame.grid_columnconfigure(0, weight=1)
        self.ach_tree_frame = ach_frame

        # Kill Statistics panel (right)
        kill_frame = ctk.CTkFrame(container)
        kill_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=0)
        kill_frame.grid_rowconfigure(0, weight=1)
        kill_frame.grid_columnconfigure(0, weight=1)
        self.kill_fields_frame = kill_frame

        # Create kill statistics labels and entries dynamically
        self.kill_fields_label_widgets = {}  # Store label references
        self.kill_field_keys = []  # Store keys for iteration
        self.kill_fields_labels = {}  # Store entry references
        row = 0
        trans = self.translations[self.current_language]
        from EDFSaveEditorLogic import KILL_FIELDS
        for offset, size, key in KILL_FIELDS[:len(KILL_FIELDS)-1]:  # Adjust range as needed
            label_text = trans.get(key, key.replace("_", " ").title()) + ":"
            l = ctk.CTkLabel(kill_frame, text=label_text, width=200, anchor="w", font=("Arial", 10))
            l.translation_key = key
            l.grid(row=row, column=0, sticky="w", pady=2)
            value_entry = ctk.CTkEntry(kill_frame, state="readonly", width=80, font=("Arial", 10))
            value_entry.grid(row=row, column=1, sticky="e", pady=2)
            self.kill_fields_labels[key] = value_entry
            self.kill_fields_label_widgets[key] = l
            row += 1

        # Update kill statistics with current data
        self.update_kill_fields()

        # Initialize kills_box_label if not already set
        if not hasattr(self, 'kills_box_label'):
            self.kills_box_label = ctk.CTkLabel(kill_frame, text=trans.get('kills_box_label', 'Kill Statistics (Read only)'), font=("Arial", 12, "bold"))
            self.kills_box_label.grid(row=-1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        return container

    def on_translation_lang_change(self, lang):
        self.current_language = lang  # sync app language with selection
        self.translation_lang_var.set(lang)
        try:
            self.language_dropdown.set(lang)
        except Exception:
            pass
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
            except Exception:
                pass
        # Refresh translation editor view last
        self.update_translation_tab()

    def add_new_language(self):
        new_code = tk.simpledialog.askstring("New Language Code", "Enter new language code (e.g. 'fr'):")
        if not new_code or new_code in self.translations:
            return
        new_name = tk.simpledialog.askstring("New Language Name", "Enter display name for this language:")
        if not new_name:
            return
        # UI Strings clone
        self.translations[new_code] = self.translations.get('en', {}).copy()
        self.translations[new_code][new_code] = new_name
        # Weapon Names
        for game, langs in self.weapon_names_lang.items():
            if new_code not in langs:
                langs[new_code] = langs.get('en', {}).copy() if 'en' in langs else {}
        # Mission Names
        for game, langs in self.mission_names_data.items():
            if new_code not in langs:
                langs[new_code] = langs.get('en', {}).copy() if 'en' in langs else {}
        # Persist (skip if frozen)
        if not is_frozen():
            try:
                with open('languages.json', 'w', encoding='utf-8') as f: json.dump({'languages': self.translations}, f, ensure_ascii=False, indent=2)
                with open('WeaponNamesLang.json', 'w', encoding='utf-8') as f: json.dump(self.weapon_names_lang, f, ensure_ascii=False, indent=2)
                with open('MissionNames.json', 'w', encoding='utf-8') as f: json.dump(self.mission_names_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[WARN] Could not save new language files: {e}")
        # Update UI
        if hasattr(self, 'translation_lang_dropdown'):
            self.translation_lang_dropdown.configure(values=list(self.translations.keys()))
        self.translation_lang_var.set(new_code)
        self.current_language = new_code
        self.update_translation_tab()
        self.update_ui_text()

    def update_translation_tab(self, selected=None):
        for widget in self.translation_frame.winfo_children():
            widget.destroy()
        lang = self.translation_lang_var.get()
        tab = self.translation_tab_var.get()
        label = ctk.CTkLabel(self.translation_frame, text=f"Editing: {tab} ({lang})", font=("Arial", 12, "bold"))
        label.pack(anchor="w", pady=(0, 5))
        self.translation_textbox = ctk.CTkTextbox(self.translation_frame, height=300, font=("Consolas", 11))
        self.translation_textbox.pack(fill="both", expand=True)
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
        save_btn = ctk.CTkButton(self.translation_frame, text=self.translations.get(self.current_language, {}).get('save_translation_button', 'Save Translation'), command=self.save_translation)
        save_btn.pack(pady=5, anchor="e")

    def on_game_change(self, new_game):
        if new_game == getattr(self, 'previous_game', None):
            return
        meta = self.games_metadata.get(new_game, {})
        coming = meta.get('coming_soon', False)
        if coming:
            messagebox.showinfo("Coming Soon", f"{new_game} support is coming soon.")
            self.game_var.set(self.previous_game)
            return
        self.current_game = new_game
        self.previous_game = new_game
        self.missionlist_key = meta.get('missionlist') or new_game.replace(" ", "").replace("Offline", "").replace("Online", "")
        self.total_missions = meta.get('total_missions', self.total_missions)
        self.total_pages = (self.total_missions + self.missions_per_page - 1) // self.missions_per_page if self.total_missions > 0 else 1
        self.current_page = 1
        for i in range(4):
            if len(self.mission_arrays[i]) < self.total_missions:
                self.mission_arrays[i].extend(bytearray(self.total_missions - len(self.mission_arrays[i])))
        # Reload mission names for the new game before refreshing table
        self.reload_mission_names()
        if hasattr(self, 'page_label'):
            trans = self.translations.get(self.current_language, self.translations.get('en', {}))
            self.page_label.configure(text=trans.get('page_label', 'Page {current}/{total}').format(current=self.current_page, total=self.total_pages))
        self.update_completion()
        self.update_weapon_table_names()
        self.update_loadout_names()
        self.update_ui_text()
        # If translation tab is showing weapon or mission names, refresh it to reflect new game/mission key
        if hasattr(self, 'translation_tab_var') and self.translation_tab_var.get() in ("Weapon Names", "Mission Names"):
            self.update_translation_tab()
        # After updating current_game etc., recompute default save dir
        try: self.update_default_save_dir()
        except Exception: pass

    def update_armor_display(self):
        """Wrapper around update_displays to keep translated prefixes for armor labels."""
        try:
            update_displays(self)  # external logic updates numeric values
        except Exception:
            pass
        trans = self.translations.get(self.current_language, {})
        # Re-apply translated templates while preserving numeric values
        for lbl in self.base_gain_labels:
            try:
                # Extract numeric (everything after last ':')
                value_part = lbl.cget('text').split(':')[-1].strip()
                # If value_part may contain spaces (e.g., numbers), keep as-is
                template = trans.get('base_gain_label', 'Base Game Gain: {value}')
                # Remove trailing localized prefix before substitution
                lbl.configure(text=template.format(value=value_part))
            except Exception:
                continue
        for lbl in self.modded_gain_labels:
            try:
                value_part = lbl.cget('text').split(':')[-1].strip()
                template = trans.get('modded_gain_label', 'Modded Armor Gain: {value}')
                lbl.configure(text=template.format(value=value_part))
            except Exception:
                continue
        # Also refresh armor label (Air Raider fix) if needed
        self.refresh_armor_labels()

    def on_save_clicked(self):
        prev_cwd = os.getcwd()
        try:
            if hasattr(self, 'default_save_dir') and os.path.isdir(self.default_save_dir):
                os.chdir(self.default_save_dir)
            save_save_data(self)
        finally:
            try: os.chdir(prev_cwd)
            except Exception: pass
            self.after_save_load_refresh()

    def on_load_clicked(self):
        prev_cwd = os.getcwd()
        try:
            if hasattr(self, 'default_save_dir') and os.path.isdir(self.default_save_dir):
                os.chdir(self.default_save_dir)
            load_save_data(self)
        finally:
            try: os.chdir(prev_cwd)
            except Exception: pass
            self.after_save_load_refresh()

    def after_save_load_refresh(self):
        """Reapply localized armor/stat labels after external save/load handlers modify values."""
        try:
            self.update_armor_display()  # preserves translated prefixes
        except Exception:
            pass
        try:
            self.refresh_loadout_labels()
        except Exception:
            pass
        try:
            self.update_weapon_table_names()
        except Exception:
            pass
        # Re-run mission/achievement refresh if arrays changed
        if hasattr(self, 'update_mission_table'):
            try: self.update_mission_table()
            except Exception: pass
        if hasattr(self, 'update_completion'):
            try: self.update_completion()
            except Exception: pass
        if hasattr(self, 'update_achievement_table'):
            try: self.update_achievement_table()
            except Exception: pass

    def get_edf_save_dirs(self):
        """Return dictionary of default EDF save directories (user can copy)."""
        local = os.getenv('LOCALAPPDATA', '')
        docs = os.path.join(os.path.expanduser('~'), 'Documents')
        dirs = {
            'EDF6': os.path.join(local, 'EDF6', 'Saved', 'SaveGames'),
            'EDF5': os.path.join(docs, 'EARTH DEFENSE FORCE 5'),
            'EDF4.1': os.path.join(docs, 'My Games', 'EDF4.1')  # fallback example
        }
        return dirs

    def init_save_paths_section(self):  # type: ignore[override]
        trans = self.translations.get(self.current_language, self.translations.get('en', {}))
        info_label = ctk.CTkLabel(self.save_paths_section_content, text=trans.get('save_paths_info', 'Copy these EDF save directories (may adjust per install):'), font=("Arial", 11, "bold"))
        info_label.pack(anchor="w", padx=8, pady=(6, 2))
        # Active dir placeholder will be added after computing default
        self.save_paths_entries = {}
        # Standard detected roots
        dirs = self.get_edf_save_dirs()
        for game, path in dirs.items():
            row = ctk.CTkFrame(self.save_paths_section_content)
            row.pack(fill="x", padx=8, pady=2)
            lbl = ctk.CTkLabel(row, text=f"{game}:", width=70, anchor="w")
            lbl.pack(side="left")
            entry = ctk.CTkEntry(row)
            entry.pack(side="left", fill="x", expand=True, padx=5)
            entry.insert(0, path)
            entry.configure(state="readonly")
            self.save_paths_entries[game] = entry
            btn = ctk.CTkButton(row, text=trans.get('copy_button', 'Copy'), width=60, command=lambda p=path: self.copy_to_clipboard(p))
            btn.pack(side="left", padx=2)
        # Pattern examples
        patterns_label = ctk.CTkLabel(self.save_paths_section_content, text=trans.get('save_paths_patterns_label', 'Path Patterns (placeholders: {UserID}, Steam64ID):'), font=("Arial", 10, "bold"))
        patterns_label.pack(anchor="w", padx=8, pady=(8, 2))
        current_user = os.getenv('USERNAME', '{UserID}')
        patterns = {
            'EDF6 Pattern': r'C:\\Users\\{UserID}\\AppData\\Local\\(EDF6ModdedSaves||EarthDefenceForce6)\\SAVE_DATA\\Steam64ID\\',
            'EDF5/4.1 Pattern': r'C:\\Users\\{UserID}\\OneDrive\\Documents\\My Games\\(EDF5||EDF4.1)\\SAVE_DATA\\Steam64ID\\'
        }
        for label_text, pattern in patterns.items():
            row = ctk.CTkFrame(self.save_paths_section_content)
            row.pack(fill="x", padx=8, pady=2)
            lbl = ctk.CTkLabel(row, text=f"{label_text}:", width=120, anchor="w")
            lbl.pack(side="left")
            entry = ctk.CTkEntry(row)
            entry.pack(side="left", fill="x", expand=True, padx=5)
            entry.insert(0, pattern)
            entry.configure(state="readonly")
            btn = ctk.CTkButton(row, text=trans.get('copy_button', 'Copy'), width=60, command=lambda p=pattern: self.copy_to_clipboard(p))
            btn.pack(side="left", padx=2)
            example = pattern.replace('{UserID}', current_user)
            example_row = ctk.CTkFrame(self.save_paths_section_content)
            example_row.pack(fill="x", padx=32, pady=(0,2))
            ex_label = ctk.CTkLabel(example_row, text=trans.get('save_paths_example_prefix', 'Example:') + " ")
            ex_label.pack(side="left")
            ex_entry = ctk.CTkEntry(example_row)
            ex_entry.pack(side="left", fill="x", expand=True, padx=5)
            ex_entry.insert(0, example)
            ex_entry.configure(state="readonly")
            ex_btn = ctk.CTkButton(example_row, text=trans.get('copy_button', 'Copy'), width=60, command=lambda p=example: self.copy_to_clipboard(p))
            ex_btn.pack(side="left", padx=2)
        # Finally add active save dir row
        try: self.update_default_save_dir()
        except Exception: pass

    def copy_to_clipboard(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()  # keep on some platforms
        except Exception:
            pass

    def update_default_save_dir(self):
        """Determine and store the default save directory for current game selection."""
        user_home = os.path.expanduser('~')
        username = os.getenv('USERNAME', '{UserID}')
        local = os.getenv('LOCALAPPDATA', '')
        docs_root_candidates = []
        # Prefer OneDrive Documents if present for EDF5 / EDF4.1
        onedrive = os.getenv('OneDrive')
        if onedrive:
            docs_root_candidates.append(os.path.join(onedrive, 'Documents'))
        docs_root_candidates.append(os.path.join(user_home, 'Documents'))
        game = getattr(self, 'current_game', 'EDF6')
        steam_id = self.detect_steam_id()
        save_dir = ''
        if game.startswith('EDF6'):
            candidates = [os.path.join(local, 'EDF6ModdedSaves', 'SAVE_DATA'), os.path.join(local, 'EarthDefenceForce6', 'SAVE_DATA')]
            for base in candidates:
                if os.path.isdir(base):
                    save_dir = base; break
            if not save_dir:
                save_dir = candidates[0]
        elif game.startswith('EDF5'):
            # EDF5 documents path (JP release sometimes different, keep generic)
            for docs_root in docs_root_candidates:
                base = os.path.join(docs_root, 'My Games', 'EDF5', 'SAVE_DATA')
                if os.path.isdir(base):
                    save_dir = base; break
            if not save_dir:
                save_dir = os.path.join(docs_root_candidates[-1], 'My Games', 'EDF5', 'SAVE_DATA')
        elif game.startswith('EDF4.1') or game.startswith('EDF4'):
            for docs_root in docs_root_candidates:
                base = os.path.join(docs_root, 'My Games', 'EDF4.1', 'SAVE_DATA')
                if os.path.isdir(base):
                    save_dir = base; break
            if not save_dir:
                save_dir = os.path.join(docs_root_candidates[-1], 'My Games', 'EDF4.1', 'SAVE_DATA')
        else:
            # Fallback to local dir
            save_dir = os.getcwd()
        # Append SteamID if detected
        if steam_id and os.path.isdir(os.path.join(save_dir, steam_id)):
            save_dir_full = os.path.join(save_dir, steam_id)
        else:
            save_dir_full = save_dir
        self.default_save_dir = save_dir_full
        # Reflect in debug tab if present
        try: self.update_save_paths_debug()
        except Exception: pass

    def detect_steam_id(self):
        """Attempt to detect a Steam64ID folder inside expected save directories."""
        # Look for 17-digit directory names inside common bases
        candidates = []
        local = os.getenv('LOCALAPPDATA', '')
        candidates += [os.path.join(local, 'EDF6ModdedSaves', 'SAVE_DATA'), os.path.join(local, 'EarthDefenceForce6', 'SAVE_DATA')]
        user_home = os.path.expanduser('~')
        docs_roots = []
        onedrive = os.getenv('OneDrive')
        if onedrive: docs_roots.append(os.path.join(onedrive, 'Documents'))
        docs_roots.append(os.path.join(user_home, 'Documents'))
        for dr in docs_roots:
            candidates.append(os.path.join(dr, 'My Games', 'EDF5', 'SAVE_DATA'))
            candidates.append(os.path.join(dr, 'My Games', 'EDF4.1', 'SAVE_DATA'))
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
        """Update / create the Active Save Dir row in save paths debug section."""
        if not hasattr(self, 'save_paths_section_content'):
            return
        existing = getattr(self, 'active_save_dir_entry', None)
        trans = self.translations.get(self.current_language, self.translations.get('en', {}))
        label_text = trans.get('active_save_dir_label', 'Active Save Dir:')
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
            except Exception: pass
        else:
            # Insert at top after info label (index 1)
            try:
                row = ctk.CTkFrame(self.save_paths_section_content)
                # Pack below info label (use before other game rows by repacking) – simplest just pack now
                row.pack(fill='x', padx=8, pady=(4,2))
                lbl = ctk.CTkLabel(row, text=label_text, width=110, anchor='w')
                lbl.pack(side='left')
                entry = ctk.CTkEntry(row)
                entry.pack(side='left', fill='x', expand=True, padx=5)
                entry.insert(0, getattr(self, 'default_save_dir', ''))
                entry.configure(state='readonly')
                btn = ctk.CTkButton(row, text=trans.get('copy_button', 'Copy'), width=60, command=lambda: self.copy_to_clipboard(getattr(self, 'default_save_dir', '')))
                btn.pack(side='left', padx=2)
                self.active_save_dir_entry = entry
            except Exception:
                pass

if __name__ == "__main__":
    app = SaveEditor()
    app.mainloop()