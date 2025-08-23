# TODO for EDFSaveEditorMain.py
# ==============================
# 1. Mission Support:
#    - Add support for reading and editing more missions (EDF5, EDF4.1, DLCs, etc.).
#    - Improve mission name loading and allow dynamic mission table expansion.
#
# 2. Code Refactoring:
#    - Truncate and modularize large functions to reduce code line counts and improve maintainability.
#    - Move repeated UI update logic into helper methods.
#    - Separate logic and UI code where possible.
#
# 3. Quality of Life (QOL) Features:
#    - Add undo/redo support for edits.
#    - Add tooltips and inline help for fields.
#    - Implement auto-save and backup features. (BACKUP FOLDER ALREADY EXISTS) logic is needed
#    - Add keyboard shortcuts for common actions.
#    - Improve error handling and user feedback.
#    - Add game memory reading to fetch freshly saved data once a save is completed in-game.
#
# 4. Save File Data Coverage:
#    - Expose and allow editing of more information found in save files (e.g., player stats, settings, unlocks).
#    - Add support for additional save file formats or versions.
#
# 5. UI/UX Improvements:
#    - Make the UI more responsive and visually appealing.
#    - Add dark/light theme customization options.
#    - Allow resizing and reordering of table columns.
#
# 6. Localization:
#    - Expand translation coverage and allow community-contributed translations.
#    - Improve translation editor usability.
#
# 7. Testing & Documentation:
#    - Add unit tests for logic functions.
#    - Write developer and user documentation.
#
# 8. Miscellaneous:
#    - Add version checking and update notifications.
#    - Allow plugin or extension support for advanced users.
#
# ------------------------------------------------------------------
# File Overview (High-Level Roles)
# ------------------------------------------------------------------
# EDFSaveEditorMain.py        : Main application entry & GUI (CustomTkinter). Handles config, theme, language switching,
#                               mission/weapon tables, achievements, save path helpers, and orchestrates other modules.
# EDFSaveEditorLogic.py       : Pure / semi-pure logic helpers (data structures, armor formulae, resource path helpers).
# EDFSaveEditorSave_Handler.py: Low-level save encryption/decryption (AES-CTR) + checksum (WIP / partial implementation).
# TableParser.py              : Utility to parse raw weapon & mission text resources into normalized JSON structures.
# Generatemission.py          : Builder for default MST lobby/mission state binary blobs. (4.1 should have 2 mission tables for offline and online)
#                               {MODDED MISSION PACKS ARE CREATED AS A FILE WITH NO DATA CREATED AND WILL CRASH THE GAME IF PLAYED, MST FILES ARE NOT 100% FIGGURED OUT YET BUT >90% OF DATA IS UNDERSTOOD FOR 6}
# save checker.py             : Batch decrypt / (re)encrypt & diagnostic tool for EDF (4.1, 5, 6) save directories. (Using a python converted algorithm from the the EDFDecrypt.exe / C script)
# RequirmentsMAKER.py         : Scans project imports to auto-create a requirements.txt file (dependency helper, WIP).
# BuildEDFSE.bat              : PyInstaller build script (packs resources, version info, produces distributable exe).
# EDFSaveEditor.spec          : Auto-generated PyInstaller spec (can be manually tuned if needed).
# version_info.txt            : Windows version resource metadata embedded into the executable.
# languages.json              : UI string translations (root + per-language dictionaries).
# Librarian.py                : Developer analysis tool; copies/decrypts save slot files, parses GST/CFG/DAT/MST (Using the EDFDecrypt.exe / C script)
#                               structures with documented offsets, annotates armor/loadouts/weapons/missions, builds
#                               ImHex bookmark files, loads weapon names, logs coverage stats for reverse engineering the save files.
#                               Use this to help document save file structures. for 4.1 and 5 for revering data complexity. (LAST BEFORE OPENING ALL PARSED DATA IN ImHex, THERE IS A % OF BYTES UNDERSTOOD)
# WeaponNamesLang.json        : Weapon name mappings per game & language.
# MissionNames.json           : Mission name mappings per game/DLC & language.
# BACKUP/                     : Auto-created backup folders for save snapshots (logic to expand still pending).
# log.txt                     : Runtime diagnostic / error logging target (extend usage for debugging).
# LICENSE.txt                 : Project license (currently CC0 public domain dedication).
# ------------------------------------------------------------------
# Notes:
# - Many auxiliary scripts (parser, generator, checker) are optional developer tools not required at runtime.
# - Refactor goal: move more logic from Main into Logic module or new modules (e.g., save_paths, translations, ui_widgets).
# - Keep this overview updated when adding new significant files.