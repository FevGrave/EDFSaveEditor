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
# WeaponNamesLang.json        : Consolidated per-game weapon data (2026-08-14 restructure). Under each game's
#                               top-level key ("EDF6" etc.):
#                                 "languages"   - display name mappings per language (id -> name), as before.
#                                 "level float" - id -> exact-precision level_req (P4), unrounded straight from
#                                                 WEAPONTABLE.json's raw doubles (e.g. 0.05000000074505806, not a
#                                                 rounded 0.05 -- rounding here could shift a weapon across a
#                                                 level-band boundary).
#                                 "weapon_meta" - id -> {name, sgo, category, drop_weight, availability,
#                                                 tag_count, item_class, pack}, the rest of P0-P8.
#                                                 availability (P5, wiki-confirmed) is 0=COLLECT, 1=STARTER ITEM,
#                                                 3=SINGLE DLC. item_class (P7) is the raw value only, 0 or 1 --
#                                                 an earlier pass incorrectly forced a 3rd value (2) onto this
#                                                 field for the SINGLE DLC promo items; that classification
#                                                 already lives in availability==3 and the override was reverted.
#                                 "category_names" - category id (P2) -> internal enum name (e.g. "0" ->
#                                                 "Weapon_AssaultRifle"), verified 59/59 against the community
#                                                 wiki's own "WEAPON TABLE" section.
#                                 "EDF6" / "EDF6 DLC1" / "EDF6 DLC2" (sub-keys, one per mode) - the drop-level-band
#                                                 curve: {<difficulty>: {min_endpoint, max_endpoint, band_width}}.
#                                                 14 of 15 cells populated from the community wiki's
#                                                 {{{WeaponDrops}}} field; EDF6 DLC2/Normal stays null due to a
#                                                 genuine 3-way conflict in the wiki's own source table.
#                               WeaponDropData_EDF6.json / WeaponLevelFloat_EDF6.json / WeaponDropCurves_EDF6.json
#                               are DEPRECATED -- their content lives here now, EDFWeaponFarming.py no longer
#                               reads them, safe to delete.
# MissionNames.json           : Mission name mappings per game/DLC & language.
# EDFWeaponFarming.py         : Weapon Farming Helper logic (weapon table panel, EDF6 only so far). RE-verified
#                               formula (WeaponDropLevelBand_Compute/_ReadDifficultyCurve, Ghidra RE session
#                               2026-08-14) for the REAL gameplay drop-level band, distinct from the online-room
#                               "Weapon Level Limit" display value. Reads everything from WeaponNamesLang.json.
# BACKUP/                     : Auto-created backup folders for save snapshots (logic to expand still pending).
# log.txt                     : Runtime diagnostic / error logging target (extend usage for debugging).
# LICENSE.txt                 : Project license (currently CC0 public domain dedication).
# ------------------------------------------------------------------
# Notes:
# - Many auxiliary scripts (parser, generator, checker) are optional developer tools not required at runtime.
# - Refactor goal: move more logic from Main into Logic module or new modules (e.g., save_paths, translations, ui_widgets).
# - Keep this overview updated when adding new significant files.

WhErE iS OuR EDF MULTI MOD LOADER?????????????

Well, it been delayed due DLC mission pack saves not being created in data just the file, and needing to patch a small loop hole to REMOVE ALL Modded mission pack Online lobbies from being listed in game, BUT WHERE IS THE CODE, ALSO THIS GUI IS MADE WITH AI (GPT, Grok), IS ALSO NOT CODE SIGNED SO YOUR OS WILL complain IT'S UNSAFE, even though it is open source and you can build it yourself. and I am putting this out so we can finnally get a mod loader out there.

Just pushed WHATEVER I have for that GUI to here
https://github.com/FevGrave/EDFMultiModLoader

NEW WILL NEED EDF 4.1 and 5 support and DLCs for them and for 6,
https://github.com/FevGrave/EDFSaveEditor/releases


%AppData%\Local\EarthDefenceForce6\SAVE_DATA\{Your Steam 64 ID}\saveslot0X


Unfortunate News










Title: Save File Loophole: Bypassing Room Type Restrictions, Empty New Mission Table in Modded Packs, and Expanding Save File Limits

1. Save File Loophole: Bypassing "Room Type" Restrictions for Online Listing
When users create or load save files with specific byte values at designated offsets, they can bypass intended "Room Type" restrictions, allowing rooms to appear in public online listings despite being set to private, invite-only, or RoomNameOnly. This loophole affects both modded and vanilla users, with vanilla clients experiencing crashes when joining modded rooms due to desyncs or invalid data.

Key Offsets and Byte Patterns:

Offset 0x1498 (4 bytes): Controls "Room ID" or visibility settings.

Values:

0 = Everyone (public)
1 = Friends of Participants / Invite Only
1 = Invite Only (possible duplicate or alias)
2 = Password
3 = RoomNameOnly


Bypass Behavior: Specific byte patterns (e.g., setting to 0) force the room to list publicly, ignoring the intended privacy setting.


Offset 0x14A8 (4 bytes): Secondary "Room ID" or Security Level flag.

Values:

0 = Everyone
2 = Friends of Participants / Invite Only
3 = Invite Only
0 = Password (overlap with Everyone?)
0 = RoomNameOnly (overlap?)


Bypass Behavior: Precreated saves will still have rooms listed on the public list that will still harm vanilla users.

Stricter Validation in EDF6ModPlugin: Implement checks in the mod plugin to sanitize 0x1498 and 0x14A8 during save creation/loading. Override into "Friends of Participants / Invite Only" if detected.

Weapon Desync Mitigation is also a potenial issue, as modded weapons may not be recognized by vanilla clients, leading to crashes. so total enablement of this tools function is recommended for all modded users only.

2. New Mission Table Is Empty in Modded Mission Packs
When loading modded mission packs, a .MST file (e.g., ExampleModName.MST) is generated successfully, but it contains no data, resulting in an empty mission table. This prevents modded missions from appearing or loading, often followed by a crash to desktop (CTD).

Root Cause Hypothesis: The write process has a unhandled creation logic.

3. Expanding Save Table File Limits
Current save file structures impose hard limits that could be quickly fill up with modded content, particularly for missions and weapons. Expanding these would enable larger mod packs without corruption or truncation.

Mission Count Cap:
512 bytes for the mission table per class on mission pack. Each Byte is a mission that has additive values for mission completion status per diff. but I really dont this this is a need to edit to increase but would be a nice increase.

Total Weapon Count Limitation:
Needing Expansion: With 476 slots left, we're ~80% full (18,864 / 24,576 ≈ 0.768). Pushing beyond this risks overwriting data beyond what is expected within the EDF.dll's assembly.
4096, would be a good cap.

4. Player Custom Color System / full save file data funtions (Bonus Investigation)
If feasible, understanding and implementing the custom color system could enhance save editing for player customization.

Key Functionality from Librarian.py that has documented bytes of the save files:

class_color_sets acts as a dictionary or list-based table that points to predefined color palettes or dynamic RGBA mappings.
It parses and annotates color-related structures during save decryption (using integrated tools like EDFDecrypt for GST/CFG files).
For prime colors (pure R=255/G=0/B=0/A=0), the 1.5x multiplier is applied during write-back: e.g., input value * 1.5 (clamped to 255), which may explain over-brightening in mods.
Mixed colors undergo compression: Values are quantized (e.g., divided by a factor like 1.5 or bit-shifted) to fit into 4-byte RGBA storage, reducing precision for blends (e.g., RGB(128,64,32,0) might compress to ~85,42,21,0).
