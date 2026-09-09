# EDF6 Save Format Notes

Byte-level reference for the four MDB0 save files (`MAIN.GST`, `COMMON.CFG`, `TROPHY.DAT`,
`DEFP_M00.MST`). Compiled from: ImHex `.hexbm` bookmark files in `EDF6_Decrypted/` (hands-on
testing, may be imperfect), real decrypted `*.GSTr`/`.CFGr`/`.DATr`/`.MSTr` reference files
in the same folder, and GhidraMCP static analysis of `EDF6.exe`. Where the three disagree,
the DLL wins. Anything not empirically confirmed is marked as such - do not assume.

All four files share the same outer envelope, confirmed identical across all of them:

| Offset | Size | Field | Notes |
|---|---|---|---|
| `0x00` | 4 | Magic | `"MDB0"` |
| `0x04` | 4 | File version | `3` in every sample seen |
| `0x08` | 4 | **Body length** | uint32 = `file_size - 0x14`. Confirmed exact in both `MAIN.GSTr` (56572 - 20 = 0xDCE8) and `COMMON.CFGr` (21664 - 20 = 0x548C). Previously undocumented/labeled "unknown" in the hexbm files. Not currently read or written anywhere in the tool - fine as-is since the tool never changes a file's total size, but flag this if that ever changes (e.g. adding weapon slots), since a stale value here may be rejected by the game. |
| `0x0C` | 4 | CRC32C checksum | Already implemented (`crc32c()` in `EDFSaveEditorSave_Handler.py`), computed over `data[0x14:]`, bit-inverted, little-endian. |
| `0x10` | 4 | **"Save generation ID"** - actively enforced, this is the field behind the game's "Slot Corrupted" check | UPGRADED 2026-09-01: previously characterized (save-side only, `FUN_1807c1cb0`) as an inert per-save-job context handle, "not worth exposing." Found the LOAD-side counterpart this pass - `FUN_1807c1670` (traced by following other callers of the CRC32C routine `FUN_1807c1270`, same method used for EDF5's `FUN_140481b80`). Its decompiled check, after magic/version/body-length/checksum all pass: `*(int*)(job+0xa0) == header[0x10]` - a mismatch sets the load status to `0xfffffff6`, the exact code `FUN_1808ca8a0` (the UI display function) maps to "Slot Corrupted" (only `-3`/`-4` mean "New/empty" there; everything else is corrupt). So this field IS meaningfully checked, not inert - it's the EDF6 half of the same mechanism confirmed end-to-end for EDF4.1 via real in-game splice testing (see `EDFSaveEditorSave_Handler.py`'s `SaveGenerationID_ForgeryShenanigan()` and its big preceding comment block for the full cross-game writeup, including the same checksum zero-bypass `(stored_crc==0) \|\| (computed==stored)` also present in this function). Source of `job+0xa0`'s expected value not yet traced - `FUN_1807c1670` is reached only via an indirect/vtable call site (same "impractical without a live debugger" wall as the Player-2 `GameDataMgr` trace below), so it's unconfirmed for EDF6 whether this needs to match ACROSS every file in a slot (EDF4.1's confirmed behavior) or is a per-file-type expected value (the `0x69`/`0x00` file-to-file difference observed here is consistent with either). `SaveGenerationID_ForgeryShenanigan()` can normalize it either way (point `reference_file_path` at a same-named file from the destination account) - flagged as strong-hypothesis, not yet real-in-game-confirmed for EDF6 the way EDF4.1 is. |
| `0x14`+ | - | Body | File-specific, CRC'd region. |

## MAIN.GST

Reference file: 56572 bytes. Correction from earlier in this project: the real Player-1
"current color swatch" region starts at **`0x15C`**, not `0x9C` as previously assumed - `0x9C`
is actually the tail end of the loadout struct (Fencer Reinforced Parts IDs), which happens
to have "Color ID" in its bookmark label but is an equipped-part ID, not an RGB value.

| Offset | Size | Field | Status |
|---|---|---|---|
| `0x14`-`0x24` | 16 | Armor **current** (Ranger/Wingdiver/AirRaider/Fencer, 4 bytes each) | Implemented: `ARMOR_CURRENT_OFFSETS` |
| `0x24`-`0x28` | 4 | Unknown | Zero in reference save |
| `0x28`-`0x3C` | 20 | Spacer | Zero-filled |
| `0x3C` | 1 | **Current Player Class** (0=Ranger..3=Fencer, matches `PLAYER_CLASS_MAP`) | Not read/exposed by the tool yet |
| `0x3D`-`0x40` | 3 | Spacer | |
| `0x40`-`0x44` | 4 | **Current Player Skin ID** | `0xFFFFFFFF` (none selected) in reference save. Not read/exposed by the tool yet |
| `0x44`-`0xA4` | 96 | Loadout (24 fields) | Implemented: `LOADOUT_STRUCTURE` |
| `0xA4`-`0xA8` | 4 | Unknown, revised | `0xFFFFFFFF` in reference save - initially guessed as a 7th "Unused Fencer Slot" completing `LOADOUT_STRUCTURE`'s symmetry with the other three classes, but the newly-decoded `0x3E98` default-weapon-ID table (below) shows all 6 of Fencer's own loadout slots are populated with real IDs and `LOADOUT_STRUCTURE` documents no unused Fencer field - so that hypothesis doesn't hold. Still unidentified. |
| `0xA8`-`0x134` | 140 | Spacer | Confirmed genuinely all `0xFF` bytes in reference save |
| `0x134`-`0x144` | 16 | Armor **max** (same class order) | Implemented: `ARMOR_STRUCTURE` |
| `0x144`-`0x15C` | 24 | Spacer | |
| `0x15C`-`0x19DC` | 6272 | **Real** current color swatches: 4 classes x 4 costume tiers (Civilian/Soldier/Devastation/Up-and-Coming) x Primary/Secondary, each group = 12 palettes x 16 bytes (RGBA float32) + 4-byte "current swatch ID" = 196 bytes | **Implemented**: `COLOR_CLASSES`/`COLOR_TIERS`/`load_all_color_groups()` + the "Color Customization" panel |
| `0x19DC`-`0x3E98` | 9404 | "Unused Color Pallets" - byte-verified as a uniform `(0,0,0,1.0f)` RGBA-float template throughout | See Player 2 note below |
| `0x3E98`-`0x3FBC` | 292 | **CONFIRMED**: default/starting weapon IDs per class. 73 x uint32, `0xFFFFFFFF` = no default in that slot. Indices 3-26 (24 entries = 6 slots x 4 classes, same per-class field count/order as `LOADOUT_STRUCTURE`) hold the real IDs; indices 0-2 look like a small sub-header; 27-62 (36 slots) are all `-1` (reserved/unused); 63-72 are literal `0` (a different sub-field). Every non-sentinel value found (165,225,305,384,462,597,654,1041,1174,1206,1124,1262,747,771,747,715,866,867) is a member of `protected_ids` in `mass_edit_weapon_stats` (`EDFSaveEditorMain.py`) - confirms that constant is (at least in large part) sourced from this table, i.e. the game's own default-loadout list, which is why the mass-edit code is right to protect those IDs from being zeroed out. | Verified by direct byte comparison, not yet wired into any code |
| `0x3FBC`-`0x7CF8` | 15676 | "Default Settings for all Classes Color Pallets" - mixed real + template data | See Player 2 note below |
| `0x7CFC`-EOF | 24576 | Weapon table, 2048 x 12-byte entries | Implemented, fully verified (see code comments in `load_save_data`/`save_save_data`) |

**Player 2 (local co-op) hypothesis, EXPERIMENTAL:** GhidraMCP tracing of `EDF6.exe`'s real
boot sequence (`entry -> CPP_OnBoot -> Boot -> Application::Application -> GameDataMgr`)
found a constructor with a loop that runs exactly twice, laying out an identical per-player
block (loadout-style `-1` sentinels + ~80 groups of 12-color RGBA-float swatches defaulting
to `(0,0,0,1.0f)`), stride 0x3E60 bytes. That default pattern is a byte-for-byte match for
the `0x19DC`-`0x3E98` and `0x3FBC`-`0x7CF8` regions above - meaning those are most likely
genuine reserved Player 2 storage, not inert template data as first assumed, just sitting at
constructor defaults because the reference save has never had local co-op played on it. Full
writeup and the `PLAYER2_COLOR_BLOCK_OFFSET`/`SIZE` constants are in `EDFSaveEditorLogic.py`.
**Not** covered by this: armor/loadout (`0x14`-`0x24`, `0x134`-`0x144`, `0x44`-`0xA4`) show no
evidence of Player 2 duplication anywhere found so far.

## TROPHY.DAT

Reference file: 1020 bytes. `KILL_FIELDS` in `EDFSaveEditorLogic.py` covers the kill counters
(`0x104`-`0x224`), plus - wired in 2026-09-07, previously documented here but never actually added
to the table - the 8 fields below (`0xEC`-`0x244`), all verified against `TROPHY.DATr` and giving
plausible non-template values:

| Offset | Field | Reference value |
|---|---|---|
| `0x14`-`0x34` | **CONFIRMED**: 32 Conquest-% progress achievements, one plain byte each (`0`/`1` = locked/unlocked), in ascending order (5%,10%,...60%,62%,...100%) - exactly what `EDFSaveEditorMain.py`'s `achievement_data`/`load`/`save` code already assumes. Real save: first 5 bytes `1`, rest `0`. Despite the hexbm label's "for not unlocked X% unlocked" phrasing, it's a simple boolean array, not bit-packed or percentage-valued. | verified, matches existing code |
| `0x34`-`0x3C` | **CONFIRMED**: same encoding, 7 "other" achievements (Rescue/Super Rescue/Medic/Master Ranger/Diver/AirRaider/Fencer) + 1 padding byte. Real save: first 4 bytes `1`, rest `0`. | verified, matches existing code |

**3-game audit finding, 2026-09-07 - NOT verified for EDF5 or EDF4.1:** `EDFSaveEditorLogic.py`'s
`achievement_edf5_shift` (used both loading and saving) asserts EDF5 shifts this whole region +0xC
"like the rest of its body," but unlike every other EDF5 offset in this file, there's no real-save
byte-diff backing that specific claim - it's an assumption carried over from the pattern elsewhere,
not a finding. EDF4.1 falls through to `achievement_edf5_shift=0`, i.e. it reuses EDF6's exact
0x14-0x34/0x34-0x3C offsets with zero adjustment, and there is no EDF4.1 confirmation for this
region anywhere. Given EDF4.1's TROPHY.DAT layout is demonstrably NOT a simple EDF6 offset match
elsewhere (its armor lives at 0x19C/0x1D4/0xE4/0x128 vs EDF6's 0x134-0x140, nothing lines up), the
Achievements tab's 39 Conquest%/Rescue/Master-class toggles are likely reading the wrong bytes for
any EDF4.1 save, and possibly for EDF5 too. Needs the same sentinel-value byte-ID pass used to
resolve `EDF41_KILL_FIELDS`' contested offsets (write distinct values into candidate bytes, check
which Achievement/Battle-History row lights up in-game, **game fully closed** before restoring -
see the caveat further down about why) before this can be trusted for either game.

**Update, same day - disproven for EDF4.1 by real save data, 3 real TROPHY.DAT files (saveslot00,
saveslot01, saveslot03 - progress levels clearly differ across them: different playtime/mission/kill
data confirmed elsewhere in this doc):** decrypted and compared bytes `0x14`-`0x3C` across all three.
- `0x16` reads `16` (0x10) in **all three** saves. A real locked/unlocked achievement byte should
  only ever be `0` or `1` (per the CONFIRMED EDF6 encoding above) - `16` on its own disproves the
  "this is EDF6's achievement array, unshifted" hypothesis for at least that byte.
- `0x14`-`0x17` (`1, 0, 16, 1`) is **byte-for-byte identical** across all three independently-played
  saves despite their clearly different progress. Real per-save achievement flags coincidentally
  matching exactly across 3 different playthroughs, byte for byte, is implausible - this reads much
  more like a fixed structural/version constant than unlock flags.
- Diffing the *entire* file across all three saves (excluding the confirmed `EDF41_KILL_FIELDS`
  region and the header) turned up exactly **one** byte in the whole file that behaves like a boolean
  achievement flag would: `0x28` is `0` in saveslot00/01 and `1` in saveslot03. Every other byte in
  the current code's assumed 39-byte achievement range is flatly `0` in all three saves - consistent
  with "not yet unlocked," but also consistent with "this isn't where achievements live at all,"
  especially alongside the `0x16` counter-evidence above.
- Open question this doesn't resolve: does EDF4.1 even use the same achievement *list* as EDF6
  (Conquest-%/Rescue/Master-class), or a different one entirely? EDF4.1 is a separate game with its
  own Steam achievement set, not confirmed to match EDF6's. Needs someone to actually open EDF4.1's
  in-game Achievements/Trophy list (not Battle History - a different screen) and report which ones
  saveslot03 has unlocked, so the real bytes can be correlated against real unlock state instead of
  guessed at from a byte-diff alone.

**Update, 2026-09-08 - full-file diff across all 3 saves (not just 0x14-0x3C), plus a Ghidra RE
attempt that hit a real tool-access wall:**

- Extended the byte-diff to the entire 1024-byte decrypted TROPHY.DAT, all three saves. Every byte
  from `0x1F8` through `0x3FF` (the last ~55% of the file) is `0x00` in all three saves - real
  content only occupies roughly `0x18`-`0x1F7`, not the whole file. `0x18`-`0x1F` is `0x00` in all
  three too (padding/reserved after the header's confirmed 0x00-0x17 fields).
- Real per-save variation starts at `0x20` (a single `0x01` byte in saveslot03 only, `0x00` in the
  other two) then resumes heavily from `0xE0` onward, in a pattern that looks like grouped
  4/8/16-byte records (runs of 4 zero bytes alternating with runs of clearly-varying bytes), not a
  flat array of single-byte booleans - structurally different from EDF6's confirmed `0x14`-`0x3C`
  layout, reinforcing that EDF4.1 doesn't share EDF6's Achievement encoding at all, not just at a
  shifted offset.
- One recurring 4-byte sequence (`03 17 38 3C`, = 1/89 as a little-endian float32) shows up at
  multiple offsets in saveslot01/03 but at irregular strides (68/80/36/56 bytes apart) - not a fixed
  record stride, more likely a coincidental shared ratio value than a structural marker. Not pursued
  further; noted in case it's meaningful once more of the format is understood.
- Ghidra RE attempt (EDF41.exe, same session as the DLC-config/weapon-table work above): found the
  3 functions that reference the "TROPHY.DAT" string (`FUN_1403ed9d0`/`edb10`/`ede70`), but all three
  are just async job-dispatch plumbing (`JobSaveDataLoad` vtable setup + enqueue) - they hand off to
  a virtual `Run()`/completion callback that actually populates the buffer, and that callback isn't
  reachable through this toolset's string/address xref search (`get_xrefs_to` on every
  JobSaveDataLoad-related debug string and on the class's own vtable data address returned zero
  results - the code that calls them exists, but isn't in Ghidra's auto-analyzed call graph this
  toolset can walk). The EDF6 WeaponTable 2048-cap bounty hit the same category of wall on a
  different function and only got past it with the human opening Ghidra's own GUI Symbol Tree
  directly - same fix likely needed here. **NEEDS HUMAN HELP**: either (a) open `0x1403edb10` (or
  its vtable's `Run` slot) in the Ghidra GUI directly and report what calls/derives from it, or
  (b) do an in-game sentinel-byte pass (write a distinct value into each candidate offset in
  `0x18`-`0x1F7`, boot the game, see which Achievement/Battle-History row changes, exactly like
  `EDF41_KILL_FIELDS` was originally resolved) - both are more reliable than further static guessing
  from this toolset alone.
- The Achievements tab now shows a standing UI warning (`achievement_panel_warning` in
  `languages.json`, all 5 languages) telling the user EDF4.1's values here are unreliable, rather
  than presenting confirmed-wrong data silently.

**Update, 2026-09-08 - wall cleared: found the real deserializer without GUI access, structure
confirmed against all 3 real saves.**

- The earlier wall was from starting the xref search at the "TROPHY.DAT" *string* and at the
  `JobSaveDataLoad` vtable *data* address, both of which are genuinely unreferenced in Ghidra's
  auto-analysis. Switching to xrefs-**to the three loader functions themselves**
  (`FUN_1403ed9d0`/`edb10`/`ede70`) found real callers this toolset had not tried yet:
  `FUN_1404e8ba0` (`UiLoad_Main`'s init - the master job-dispatch orchestrator for every save
  component: COMMON.CFG, MAIN.GST slots, and TROPHY.DAT alike, gated by a bitmask at `param_1+0x3e`)
  and `FUN_1404eb270` (a second, similar dispatcher). TROPHY.DAT specifically is bits `0x100`
  (single call to `edb10`) and `0x200/0x400/0x800/0x1000` (four calls to `ede70` with an index
  param 0-3) - so the master file is loaded as up to 5 separate async jobs, not 1.
- Each job's completion callback is the shared `FUN_1404e9870` (`JobSaveDataLoad`-typed via
  `__RTDynamicCast`). It's generic - just `memcpy`s the raw loaded file bytes into a
  caller-supplied destination pointer, for any file type. But it also carries a per-job flag: if
  `(job_flags & 0x100) != 0`, it additionally calls `FUN_1404ea100(dest_buffer, job)`.
- `FUN_1404ea100` copies the loaded bytes onto the stack and calls
  `FUN_1400cfcf0(&DAT_140cc84a0[0x6650], stack_buffer)` - **this is the real deserializer**.
  `DAT_140cc84a0` is the engine's big global game-state singleton; `+0x6650` off it is (almost
  certainly) the achievement/stat tracking map.
- `FUN_1400cfcf0` walks an in-memory `std::map`-style red-black tree (already populated elsewhere,
  presumably at game init, with one node per tracked achievement/stat) **in sorted-key order**
  (standard in-order RB-tree traversal - left subtree, node, right subtree) and, for each node in
  turn, copies one 4-byte value from `raw_buffer + 200` (`0xC8`) sequentially into that node's
  `+0x44` field. In other words: TROPHY.DAT's real achievement/stat payload is a **flat array of
  raw 4-byte slots starting at file offset `0xC8`**, one slot per tracked stat, in a fixed order
  that matches whatever order the engine registers stats in (not yet recovered - a separate
  function, not chased down this session).
- **Verified against all 3 real decrypted saves** (AES-CTR with the existing `_EDF41_KEY`/`_EDF41_IV`,
  no new key needed - TROPHY.DAT uses the plain save key, unlike DLC Config.sgo): every byte from
  `0x1F8` to `0x3FF` is `0x00` in all three (matches the earlier full-file diff), and the *nonzero*
  region ends at exactly `0x1F7` in all three - i.e. the real payload is exactly `0x1F8 - 0xC8 =
  0x130` bytes = **76 four-byte slots** (`0xC8` through `0x1F4`), then zero padding to EOF. That the
  boundary lands on a clean slot count in all three independently-played saves is strong structural
  confirmation this is the right region and the right slot size.
- Interpreting those 76 slots as mixed int32/float32 (the field is `undefined4` in the decompile -
  the engine doesn't type it, each stat's real type is whatever code originally wrote it) shows
  plausible achievement/stat data: e.g. slot 7 (`0xE4`) reads as float32 ≈ 200/209/201 across the
  three saves (looks like a percentage-style stat capped near 200-210); slot 12/29 (`0xF8`/`0x13C`)
  is a recurring `0.011236` float in two of three saves (`= 1/89`, the same ratio flagged in the
  prior update - now explained as a real per-stat value, not a coincidence); several slots are small
  plain integers (10, 15, 67, 97, 108, 118, 657, 2077, 4666, 11774...) consistent with raw kill/use
  counts. saveslot03 (the most-played file) has far more nonzero slots than saveslot00/01, as
  expected for more unlocked/progressed stats.
- **Still open**: which of the 76 slots is which named achievement/stat. That requires either
  finding the map's key-registration code (where the 76 keys get inserted, in the same order this
  parser reads them) or an in-game sentinel test (change one in-game stat, re-save, diff which slot
  moved) - genuinely the next step, not a tool-access wall this time, just unmapped-but-now-tractable
  work. The GUI Symbol Tree detour is no longer needed - this was fully resolved via the MCP xref
  tool alone, just by pivoting the search from strings/data to the loader functions' own callers.
- Functions involved, for reference: `FUN_1404e8ba0`/`FUN_1404eb270` (dispatch) ->
  `FUN_1403edb10`/`FUN_1403ede70` (job creation, unchanged from prior update) ->
  `FUN_1404e9870` (generic completion, `JobSaveDataLoad`-typed) -> `FUN_1404ea100` (TROPHY.DAT-
  specific post-process) -> `FUN_1400cfcf0` (the deserializer - writes `raw[0xC8:]` into
  `DAT_140cc84a0+0x6650`'s tree, in key order). None of these have been renamed in Ghidra yet
  (no byte-pattern-confirmed prototype/struct layout to promote them with per CLAUDE.md's hard
  stops) - this is a decompile-only finding pending that follow-up work.

**Update, 2026-09-08 (same day, cont'd) - the 76 slot names are recoverable from `Achievement.sgo`,
confirmed by a prior EDF6 investigation of the identical subsystem.**

- Chased a second lead from the same session: `AchievementUtility` (Steam sync glue -
  `SteamAPI_RegisterCallback` for `UserStatsReceived_t`/`UserAchievementStored_t`) turned out to be
  a dead end for names - it just relays already-resolved achievement-name strings from Steam's own
  callback payload, doesn't define them.
- The real source: strings in EDF4.1.exe reference `"APP:/ETC/Achievement.sgo"` twice, plus
  `"AchievementVariable"`/`"AchievementEvent"` (SGO section names) and
  `"AchievementAddCount"`/`"UpdateAchievementCounter"` (AngelScript-bound function signatures -
  mission scripts call these to bump named counters; consistent with the `AchievementVariable`/
  `AchievementEvent` split below).
- `D:\EDF_GhidraRE_Documents\Human Help Depot\GameState\functions\AchievementSystemInit_0x1800cdd30.md`
  is a **prior, already-VERIFIED investigation of the exact same subsystem in EDF6's `EDF.dll`**
  (function `FUN_1800cdd30`, called from `GameDataManagerInit`). It documents, byte-confirmed:
  `Achievement.sgo` has an `AchievementVariable` section (name + INT/FLOAT type per entry) and an
  `AchievementEvent` section (which script-facing event bumps which named variable, by what
  action - Add/Sub/Set/Max/Clear). Init inserts every variable into a wstring-keyed red-black
  tree, then does one in-order walk assigning sequential indices - **alphabetical order by
  variable name = slot order in TROPHY.DAT**. EDF6's serializer (`FUN_1800cfc50`) writes 200 such
  slots at payload offset `0x120`; EDF4.1's `FUN_1400cfcf0` (this session) writes 76 slots at
  file offset `0xC8` - same design, smaller table, consistent with EDF4.1 being the earlier/
  smaller game. The near-identical function addresses (`...cfc50` in EDF6 vs `...cfcf0` in
  EDF4.1) suggest this code path barely changed between versions.
- **This means the 76 EDF4.1 names are recoverable without any more Ghidra work**, the same way
  the DLC weapon-unlock lists were: extract EDF4.1's own `APP:/ETC/Achievement.sgo` from the base
  game's CPK (not the `dlc.cpk` files already sitting in `Real Files/dlc/` - those only hold
  DLC-specific `Config.sgo`, this needs the base game's own data), decode it with the same
  OGS/SGO JSON decoder already used for `_WeaponTable.sgo`/`Config.sgo`, pull the
  `AchievementVariable` name list, sort alphabetically (UTF-16 order), and slot 0..75 in that
  sorted order = TROPHY.DAT offset `0xC8 + slot*4`. **Not yet done this session** - checked every
  already-unpacked folder here (`Real Files/dlc/*`, `EDFSaveEditor/DUMP/dlc/*`) and EDF4.1's
  `Achievement.sgo` isn't among them; it needs pulling from the base game install, not the DLC
  packages.

**Update, 2026-09-08 (same day, cont'd 2) - `Achievement.sgo` found and decoded
(`D:\EDF_GhidraRE_Documents\Real Files\dlc\ACHIEVEMENT.json`). Fully resolved for 70 of the ~76-78
real slots; verified byte-exact against all 3 real saves.**

- The JSON has both sections `AchievementSystemInit` reads: `AchievementVariable` (70 entries -
  name, type `int`/`float`, default) and `AchievementEvent` (51 entries - achievement id, name,
  target variable, comparison op, threshold; e.g. `RangerNromalClear` unlocks when
  `RangerNormalClearRatio >= 1`). The Event list means real achievement **unlock status**, not
  just raw counters, is computable - not just "what's this byte" but "is this achievement
  actually earned."
- Sorted the 70 `AchievementVariable` names alphabetically (plain Python `sorted()` on the ASCII
  strings - equivalent to UTF-16 ordinal order for this data) and mapped index -> file offset
  `0xC8 + i*4`. **Verified byte-exact**: decrypted all 3 real saves and checked every slot -
  every single one matches real, plausible values (kill counts, play counts, clear ratios 0-1,
  armor totals matching in-game class equip totals), and the two lowest-sorting lowercase names
  (`elevation` at idx 68 = `0x1D8`, `max_elevation` at idx 69 = `0x1DC`) land exactly on the two
  float values independently spot-checked earlier this session (saveslot03: 0.4382 / 0.2697).
  Full 70-row table:

  | idx | offset | name | type |
  |---|---|---|---|
  | 0 | `0x0c8` | `4LegTankKillCount` | int |
  | 1 | `0x0cc` | `AirRaiderArmor` | float |
  | 2 | `0x0d0` | `AirRaiderEasyClearRatio` | float |
  | 3 | `0x0d4` | `AirRaiderHardClearRatio` | float |
  | 4 | `0x0d8` | `AirRaiderHardestClearRatio` | float |
  | 5 | `0x0dc` | `AirRaiderInfernoClearRatio` | float |
  | 6 | `0x0e0` | `AirRaiderNormalClearRatio` | float |
  | 7 | `0x0e4` | `AirRaiderPlayCount` | int |
  | 8 | `0x0e8` | `AlienTrailerKillCount` | int |
  | 9 | `0x0ec` | `AllClearRatio` | float |
  | 10 | `0x0f0` | `ArmorCount` | int |
  | 11 | `0x0f4` | `BigDragonKillCount` | int |
  | 12 | `0x0f8` | `BigGiantSpiderKillCount` | int |
  | 13 | `0x0fc` | `Carrier1KillCount` | int |
  | 14 | `0x100` | `Carrier2KillCount` | int |
  | 15 | `0x104` | `DeiroiKillCount` | int |
  | 16 | `0x108` | `DragonKillCount` | int |
  | 17 | `0x10c` | `EasyClearRatio` | float |
  | 18 | `0x110` | `FencerArmor` | float |
  | 19 | `0x114` | `FencerEasyClearRatio` | float |
  | 20 | `0x118` | `FencerHardClearRatio` | float |
  | 21 | `0x11c` | `FencerHardestClearRatio` | float |
  | 22 | `0x120` | `FencerInfernoClearRatio` | float |
  | 23 | `0x124` | `FencerNormalClearRatio` | float |
  | 24 | `0x128` | `FencerPlayCount` | int |
  | 25 | `0x12c` | `FrameCount` | int |
  | 26 | `0x130` | `GiantAntKillCount` | int |
  | 27 | `0x134` | `GiantAntQueenKillCount` | int |
  | 28 | `0x138` | `GiantBeeKillCount` | int |
  | 29 | `0x13c` | `GiantBeeQueenKillCount` | int |
  | 30 | `0x140` | `GiantSpiderKillCount` | int |
  | 31 | `0x144` | `GuardDamage` | float |
  | 32 | `0x148` | `HardClearRatio` | float |
  | 33 | `0x14c` | `HardestClearRatio` | float |
  | 34 | `0x150` | `HealDamage` | float |
  | 35 | `0x154` | `HectorKillCount` | int |
  | 36 | `0x158` | `HornetNestKillCount` | int |
  | 37 | `0x15c` | `InfernoClearRatio` | float |
  | 38 | `0x160` | `Monster501KillCount` | int |
  | 39 | `0x164` | `MotherShip301KillCount` | int |
  | 40 | `0x168` | `MotherShip401KillCount` | int |
  | 41 | `0x16c` | `NephilaKillCount` | int |
  | 42 | `0x170` | `NestKillCount` | int |
  | 43 | `0x174` | `NormalClearRatio` | float |
  | 44 | `0x178` | `OfflinePlayCount` | int |
  | 45 | `0x17c` | `OnlinePlayCount` | int |
  | 46 | `0x180` | `PlayCount` | int |
  | 47 | `0x184` | `RangerArmor` | float |
  | 48 | `0x188` | `RangerEasyClearRatio` | float |
  | 49 | `0x18c` | `RangerHardClearRatio` | float |
  | 50 | `0x190` | `RangerHardestClearRatio` | float |
  | 51 | `0x194` | `RangerInfernoClearRatio` | float |
  | 52 | `0x198` | `RangerNormalClearRatio` | float |
  | 53 | `0x19c` | `RangerPlayCount` | int |
  | 54 | `0x1a0` | `RescueCount` | int |
  | 55 | `0x1a4` | `UfoRoboKillCount` | int |
  | 56 | `0x1a8` | `UfoSmall301AceKillCount` | int |
  | 57 | `0x1ac` | `UfoSmall301KillCount` | int |
  | 58 | `0x1b0` | `UfoSmall401KillCount` | int |
  | 59 | `0x1b4` | `WeaponCount` | int |
  | 60 | `0x1b8` | `WeaponGetRatio` | float |
  | 61 | `0x1bc` | `WingDiverArmor` | float |
  | 62 | `0x1c0` | `WingDiverEasyClearRatio` | float |
  | 63 | `0x1c4` | `WingDiverHardClearRatio` | float |
  | 64 | `0x1c8` | `WingDiverHardestClearRatio` | float |
  | 65 | `0x1cc` | `WingDiverInfernoClearRatio` | float |
  | 66 | `0x1d0` | `WingDiverNormalClearRatio` | float |
  | 67 | `0x1d4` | `WingDiverPlayCount` | int |
  | 68 | `0x1d8` | `elevation` | float |
  | 69 | `0x1dc` | `max_elevation` | float |

- **Not fully resolved**: real nonzero data continues past idx 69 out to file offset `0x1F4`
  (roughly 6-8 more 4-byte slots, `0x1E0`-`0x1F4`), but this `ACHIEVEMENT.json` only has 70
  variables - it's very likely a slightly older/incomplete snapshot (it lives in the `dlc` Real
  Files folder, not confirmed to be the final/patched base-game version). Since sort order is
  alphabetical and `elevation`/`max_elevation` (idx 68/69, lowercase) are confirmed as the correct
  last two among these 70, any missing variables must also start with a lowercase letter (they'd
  sort after `max_elevation`) - unless they're an even-later addition altogether. **Needs a newer/
  more complete `Achievement.sgo` dump to close out the last ~6-8 slots** - not a Ghidra problem
  anymore, just a data-completeness one.
- `AchievementEvent` gives unlock formulas for named Steam achievements (51 of them, ids 1-51,
  first few: `RangerNromalClear`/`RangerHardClear`/`RangerHardestClear`/`RangerInfernoClear` each
  gated on the matching `RangerXClearRatio` variable `>= 1`, `GetWeapon10`/`50`/`100` on
  `WeaponGetRatio >= 0.1/0.5/1.0`, hunter achievements on kill-count thresholds, `MasterX` on
  armor totals, `Rescue`/`SuperRescue` on `RescueCount >= 5/50`, `Medic` on `HealDamage > 0`,
  `Elevation200` on `elevation > 200`) - this is the piece that would let the Achievements tab
  show real "X/Y unlocked" status per achievement, not just raw counter values.

**Update, 2026-09-08 (same day, cont'd 3) - the 70-vs-76 gap fully reconciled against the
already-verified `EDF41_KILL_FIELDS` table. Zero conflicts once corrected; safe to ship.**

- Cross-checked the new 70-name table against `EDF41_KILL_FIELDS` (the older, sentinel/byte-scan
  verified table already in `EDFSaveEditorLogic.py`) by semantically matching ~20 of its entries
  to `AchievementVariable` names (e.g. `armor_value_air_raider`~`AirRaiderArmor`,
  `gameplay_time_frames`~`FrameCount`, `deroys_defeated`~`DeiroiKillCount`,
  `weapon_acquisition_rate`~`WeaponGetRatio`, `max_height_meters`~`max_elevation`) and comparing
  each anchor's real, trusted offset against the naive alphabetical-sort offset. **19 of 20
  matches showed an identical +6 slot (+0x18 byte) gap**, from the very first checked entry to the
  very last - i.e. the true array is exactly my 70 names plus 6 additional unknown-named entries,
  all sorting alphabetically *before* `4LegTankKillCount` (consistent with digit-prefixed names
  not present in this `ACHIEVEMENT.json` snapshot). 6 (unknown) + 70 (known) = 76, matching the
  independently-confirmed total slot count exactly.
- Applied the flat +6 shift and re-checked **all 41** `EDF41_KILL_FIELDS` entries automatically
  (not just the 20 hand-picked anchors) against the shifted table: **zero type mismatches**. This
  also auto-resolved two things that were ambiguous by hand: `motherships_defeated` (0x17C) is
  `MotherShip301KillCount`, `brains_defeated` (0x180) is `MotherShip401KillCount` (not the other
  way around); and `missions_started`'s odd +4-instead-of-+6 gap turned out to be a wrong manual
  guess on my part (it's actually `OfflinePlayCount`, not `PlayCount` - `PlayCount` sits one slot
  later, previously unlisted). `shield_bearers_defeated` (0x100, no obvious old-table match) turned
  out to be `AlienTrailerKillCount` - EDF4.1's shield-generating UFO-carrier trailer enemy.
- **Final, reconciled 76-slot table** (`0xC8` to `0x1F4`, all offsets `EDF4.1 TROPHY.DAT` file-
  relative): slots 0-5 (`0xC8`-`0xDC`) remain unknown (missing from this `Achievement.sgo`
  snapshot - needs a newer/more complete dump to close out); slots 6-75 (`0xE0`-`0x1F4`) are the
  70 `AchievementVariable` names from `ACHIEVEMENT.json`, in alphabetical order, now cross-
  validated against the independently-derived, sentinel-tested `EDF41_KILL_FIELDS` table with zero
  conflicts. This supersedes `EDF41_KILL_FIELDS` as the authoritative EDF4.1 counter table (it's a
  strict superset: same offsets/values where they overlap, plus ~30 previously-unlisted fields -
  all class clear-ratios, generic overall ratios, per-class play counts, `HealDamage`/
  `GuardDamage`, `WeaponCount`, `ArmorCount`, `elevation`/`max_elevation`). Wired into
  `EDFSaveEditorLogic.py` as the new `EDF41_KILL_FIELDS` (replacing the old, smaller version) plus
  a new `EDF41_ACHIEVEMENT_EVENTS` table (the 51 unlock formulas) and a
  `compute_edf41_achievement_unlocks()` helper for the Achievements tab.

**Update, 2026-09-08 (same day, cont'd 4) - wired into the app; verified against all 3 real
saves.** EDF4.1's Achievements tab now shows the 51 real achievement names (typos in the game's
own data kept as-is, e.g. `RangerNromalClear`) with computed unlocked/locked status and live
progress (`No (150/500)`-style); read-only, since EDF4.1 has no separate stored "unlocked" bit -
status is always derived from the counters, same as Steam's own SetAchievement calls. The Kill
Statistics panel now shows all 70 named counters (previously ~39, with several wrong names) plus
the 6 still-unknown slots. Tested against saveslot00/01/03: playtime, unlock counts, and progress
values all plausible (saveslot03's 58h save has 10/51 unlocked incl. several Hunter achievements
and Master Wing Diver; the two 8-9.5h saves have 0-3). Write-back round-trips correctly through
the existing `write_kill_fields`/`extract_kill_fields` plumbing - no new write path needed.

**Update, 2026-09-08 (same day, cont'd 5) - same treatment applied to EDF6, cleaner result (zero
gaps, no live save needed).**

FevGrave supplied EDF6's own `APP:/ETC/Achievement.sgo`, decoded
(`F:\SteamLibrary\steamapps\common\EARTH DEFENSE FORCE 6\Root\ETC\ACHIEVEMENT.json`): 91
`AchievementVariable` entries, 39 `AchievementEvent` unlock formulas (the same
Conquest5-100/Master-class/Rescue/Medic set the app's existing byte-flag Achievements panel
already tracks). Sorted alphabetically and cross-checked against the existing `KILL_FIELDS` table
(wired 2026-09-07 from an earlier ImHex/hexbm pass) using the same semantic-anchor technique that
worked for EDF4.1: **17 independent anchors, zero exceptions, all agreeing on base offset `0xDC`**
(not the `0x134` the older `AchievementSystemInit_0x1800cdd30.md` doc had estimated - that
turns out to have been imprecise; the "200 slots" in that doc was the serializer's hardcoded array
*cap*, not the real variable count, which is 91). Every one of the old table's 53 entries falls
cleanly inside the new 91-slot range with no contradictions, and several genuinely correct wrong
guesses: `mobile_base_mothership_kills` (0x15C, previously hexbm-flagged uncertain) is really
`FortressKillCount`; the whole `android_kills`/`super_android_kills`/etc. family maps cleanly onto
EDF6's real `BerserkerA/B/C/D/Large/Middle` enemy names. `KILL_FIELDS` (EDF6's table) replaced with
the full 91-entry version - same offsets/values where old and new overlap, correct names
throughout, ~39 previously-unlisted fields added (all class clear-ratios, PlayCounts, `FrameCount`,
`HealDamage`/`GuardDamage`, `WeaponCount`/`WeaponGetRatio`, and ~15 more named enemy kill-counts).
EDF6's Achievements panel (the independently-verified `0x14`/`0x34` byte-flag system) was left
untouched - it already works, no reason to touch it; `EDF6_ACHIEVEMENT_EVENTS` is logged for
reference/future cross-validation only, not wired into the UI. Not yet verified against a live
decrypted EDF6 save (unlike EDF4.1's, which was checked against 3 real files) - the semantic
cross-validation is unusually strong (17/17 unanimous) but an actual save-based check is still the
better bar; worth doing if/when a real EDF6 TROPHY.DAT turns up.

**EDF5 still needs the same treatment** - no EDF5 game files, executable, or Achievement.sgo are
available in this project yet.

| `0xEC` | "Game's Player has started" (bool-like) | `0` in reference save |
| `0xF4` | **Missions Played as Air Raider** | 127 |
| `0xFC` | **Teleport Device Kills** | 32 |
| `0x100` | **Total Armor Points Acquired** | 10579 |
| `0x158` | **Missions Played as Fencer** | 0 |
| `0x15C` | Mobile Base / Mothership Kills (hexbm marks this uncertain) | 2 |
| `0x160` | Total playtime, ticks (60/sec) | 17814764 -> ~82.5 hours. Already correctly read by `app.playtime_label` code - confirms the offset. |
| `0x1F4` | **Missions Played as Ranger** | 201 |
| `0x244` | **Missions Played as Wingdiver** | 19 |

Now in `KILL_FIELDS` as: `game_player_has_started` (`0xEC`), `missions_as_air_raider` (`0xF4`),
`teleport_device_kills` (`0xFC`), `total_armor_points_acquired` (`0x100`), `missions_as_fencer`
(`0x158`), `mobile_base_mothership_kills` (`0x15C`, still the one hexbm itself marks uncertain),
`missions_as_ranger` (`0x1F4`), `missions_as_wingdiver` (`0x244`). `0x160` (playtime) stays
handled separately via `get_playtime_offset()`, not duplicated into `KILL_FIELDS`.

Also noted: `extract_kill_fields()` always reads fields as 2 bytes (`struct... 'little'` over
`data[offset:offset+2]`) even though every `KILL_FIELDS` tuple declares a 4-byte size. In the
reference save every value fits comfortably under 65536 so this hasn't produced a visible bug,
but it means any counter that ever exceeds 65535 would silently read wrong. Flagging, not
fixing without a save that actually exercises it.

## COMMON.CFG

Reference file: 21664 bytes. Overwhelmingly keybind/control-mapping data, one block per class
(Ranger/Wingdiver/AirRaider/Fencer), each internally consistent and already well labeled by
the hexbm bookmarks (attack/jump/reload/vehicle/combat-frame/barga/depth-crawler/helicopter
controls). A few things worth flagging:

- `0x34`-`0xC4` (144 bytes): not labeled in the hexbm file at all. Byte-checked against
  `COMMON.CFGr` - it's not blank/template, it's two back-to-back 12-int sequences (values
  mostly 1-14, with repeats and gaps rather than a clean 1..N permutation) followed by a third
  block of larger, more varied values (0x12-0x58 range). Searched Ghidra for a settings/keybind
  loader by name (`ButtonIcon`/`InputConfig`/`KeyConfig`) - nothing survived stripping. Best
  read from the byte pattern alone: an action-ID ordering table for two control-scheme presets
  (matches sitting immediately before the named per-action keybind fields), used to drive
  button-icon/prompt display rather than raw keycodes. Exact per-slot mapping not decoded.
- `0x102C`-`0x2814`: six repeating `(200-byte header + 820-byte padding)` groups, each header
  containing the same "6,7,5,4,3,2,10,11,9,1,8..." integer sequence seen in the `0x34`-`0xC4`
  block above. Consistent with the hexbm's own guess ("Default Settings for all Classes
  Body") - likely default keybind-order templates, one per class or vehicle type. Not
  individually broken out. This is UI/config preference data, not save-progress data, so it's
  lower priority/lower risk either way.
- `0x5014` (32 bytes, UTF-16LE): **Save Profile Name**. Confirmed matches what
  `profile_name_label` already reads - `"Smileynator"` in the reference save. No bug, just
  cross-verified.
- `0x5038`-`0x5498`: Emote Wheel - 8 compass directions (N/NE/E/SE/S/SW/W/NW), each with a
  3-slot set-phrase selector (12 bytes) + a 64-byte custom-text value + spacer. Already fully
  labeled by the hexbm file, not touched by the tool.

## DEFP_M00.MST

Already the most solidly verified file (mission tables). Beyond `MISSION_TABLE_BASE_OFFSETS`
(`0x1C` = Player 1, `0xA1C` = Player 2, confirmed exact against real bytes), the rest of the
file is lobby/room metadata, not mission progress:

### Difficulty bit semantics (`DIFFICULTY_BITS = [0x01,0x02,0x04,0x08,0x10]`)

Each mission byte is an OR-accumulated bitmask (`arr[idx] |= bit` on completion, never cleared
by the game), confirmed empirically against a real EDF5 save (`DUMP/DEFP_M00.MST`, base `0x28`
for EDF5 P1 - see `get_mission_table_base_offsets`). The *relationship between the bits*,
however, is not the same in every game (per FevGrave, who plays these games - not yet
independently re-verified byte-side for EDF4.1/6, but matches every value observed in the real
EDF5 save with zero exceptions):

- **EDF5/EDF6:** Easy(`0x01`) < Normal(`0x02`) < Hard(`0x04`) cascade downward - completing a
  mission on a higher tier in that trio also flags every lower tier in the trio (e.g. clearing
  Hard writes `0x07`, not `0x04` alone). VeryHard(`0x08`) and Inferno(`0x10`) are **singles** -
  each is its own independent completion flag, cascading into nothing and cascaded into by
  nothing (not even each other).
  - Real-save proof: `0x07`, `0x03` appear repeatedly (clean cascade shapes); a lone `0x02` or
    `0x04` never appears anywhere in the file (0 occurrences across 127 nonzero bytes - a
    cascade violation would produce one). Meanwhile lone `0x08` and lone `0x10` are extremely
    common (Inferno-alone is the single most common nonzero value, 81/127 occurrences), and
    combinations that skip a cascade-trio member entirely appear cleanly, e.g. `0x19`
    (Easy+VeryHard+Inferno, Normal/Hard never touched) and `0x17`
    (Easy+Normal+Hard+Inferno, VeryHard never touched) - both impossible if VeryHard/Inferno
    cascaded from or into the Easy/Normal/Hard trio, both expected if they're standalone flags.
- **EDF4.1:** no cascade at all - every difficulty, every mission, every class must be played
  individually for its bit to be set. Not yet byte-verified (no real EDF4.1 save has been
  byte-diffed for this project); noted here so nobody assumes the EDF5/6 cascade rule applies.
  Partial real-world data point 2026-09-06 (FevGrave's saveslot03, EDF4.1 DLC1 Offline,
  `MP01_M00.MST`): a single freshly-played Wing Diver mission (mission #1, played on Easy)
  is the *only* nonzero byte in the entire file, raw value `0x01` - no other bits, no other
  missions/classes touched. Consistent with (not yet conclusive proof of) no-cascade, since it
  only tests "does playing the bottom tier leave everything else alone," not "does playing a
  higher tier leave lower tiers alone" (the direction that would actually distinguish the two
  schemes) - still open until a before/after diff exists for a Normal-or-higher EDF4.1 clear.

- **EDF4.1 Online mission table location CONFIRMED 2026-09-06**: `DEFP_M01.MST`, found
  alongside `DEFP_M00.MST`/`MP01_M00.MST` in the same real save slot (saveslot03) - EDF4.1
  reuses EDF5's `M00`=Offline/`M01`=Online numbering convention. Decrypted with EDF4.1's
  fixed AES-CTR key/IV (`_EDF41_KEY`/`_EDF41_IV` in `EDFSaveEditorSave_Handler.py`) and found
  real, non-template Wing Diver progress through mission 93 (Normal/Hard/VeryHard/Inferno bits
  populated, matching the same base-offset/class-block layout as `DEFP_M00.MST`). Previously
  `games_metadata['EDF4.1 Online']` pointed at `'Unknown.MST'` with `coming_soon: True`; now
  updated to `'DEFP_M01.MST'` / `coming_soon: False` in `EDFSaveEditorMain.py`.
  `total_missions: 98` is still the pre-existing unverified figure - highest nonzero index
  observed was 93, which is consistent with 94-98 simply being not-yet-played rather than the
  real count being lower, but re-check against a more complete save if one turns up.

- **M00=Offline/M01=Online extends to the MP0N DLC packs too - CONFIRMED for DLC1, 2026-09-06.**
  `MP01_M01.MST` did not exist in saveslot03 until FevGrave played EDF4.1 DLC1 online, then
  appeared alongside the pre-existing `MP01_M00.MST` - same 5928-byte size, valid `MDB0` header,
  same fixed AES-CTR key/IV, same layout, Wing Diver mission #1 = `0x01` (Easy) matching the
  Offline file exactly. `games_metadata['EDF4.1 Online DLC1']` updated to
  `missiontable: 'MP01_M01.MST'`, `coming_soon: False`. DLC2's `MP02_M01.MST` follows the same
  pattern by extension but hasn't actually appeared yet (DLC2 not yet played online) - stays
  `coming_soon: True` until it shows up and gets the same byte-check.

  **Update, same day:** `MP02_M01.MST` then appeared after DLC2 was played online too - now
  3-for-3 (`DEFP_M01.MST`, `MP01_M01.MST`, `MP02_M01.MST` all confirmed real, all created only
  on first online play of their pack). Valid `MDB0` header, same 5928-byte layout as
  `MP02_M00.MST`, Wing Diver mission #1 = `0x01` (Easy) - and notably *different* from the
  Offline file's mission #1 (`0x02`, Normal) in the same slot, which confirms Online/Offline
  are genuinely independently-tracked progress, not shared/duplicated data.
  `games_metadata['EDF4.1 Online DLC2']` updated to `coming_soon: False`. The full EDF4.1
  Online/Offline x base/DLC1/DLC2 mission-table matrix is now fully mapped and byte-confirmed.

This is a **display/gameplay semantic**, not a storage rule - the editor's own bit-punching
(`toggle_mission_cell`, `_punch_mission_bits`, "Unlock Boring Missions") already sets/clears
exactly one bit at a time with no cascade logic baked in, which is correct behavior for all
three games: it just means a hand-edited EDF5/6 save can end up in a combination the real game
would never produce on its own (e.g. Hard set without Normal), which is harmless for editing
purposes but worth knowing if a "looks weird in speedrun/trophy tools" report ever comes in.

| Offset | Field |
|---|---|
| `0x14` | Mission currently selected |
| `0x18` | Difficulty currently selected |
| `0x141C`-`0x1444` | Lobby name (UTF-16LE, 40 bytes) |
| `0x1446`-`0x1476` | Open-message input text (48 bytes) |
| `0x1478`-`0x1488` | Quick-chat "set phrase" category + 3 content slots |
| `0x1498`/`0x14A8` | Room visibility (Everyone / Friends-of-participants / Invite-only / Password / Room-name-only) |
| `0x149C` | Room password (8 bytes) |
| `0x16C8` | "TailFlagA" | observed `0x?` values, meaning not decoded |
| `0x16CE` | DLC variant marker - hexbm notes distinct values per DLC pack | not decoded |

None of this is mission-progress data, so it's out of scope for the mission editor as-is, but
worth knowing it's there if lobby/room-name editing is ever wanted.

## EDF4.1 TROPHY.DAT (`EDF41_KILL_FIELDS`)

Reference file: 1024 bytes, saveslot03 (FevGrave's real EDF4.1 save, non-template). Extended from
18 to 38 confirmed fields on 2026-09-06 via two passes:

1. **Byte-scan pass**: every value on saveslot03's in-game Battle History screen was searched for
   as a raw int32 across the whole decrypted file. 14 fields matched exactly and unambiguously
   (only one offset in the file held that value) and were added directly: `shield_bearers_defeated`
   (`0x100`), `king_spiders_defeated` (`0x110`), `transport_ships_destroyed` (`0x114`),
   `large_transport_ships_destroyed` (`0x118`), `deroys_defeated` (`0x11C`), `dragons_defeated`
   (`0x120`), `hectors_defeated` (`0x16C`), `underground_tunnel_exits_destroyed` (`0x188`),
   `missions_started` (`0x190`), `online_missions_started` (`0x194`), `rescues` (`0x1B8`),
   `red_drones_defeated` (`0x1C0`), `flying_drones_defeated` (`0x1C4`), `flying_vehicles_defeated`
   (`0x1C8`).

2. **Contested-bytes pass**: 6 fields tied on identical values in the byte-scan (four offsets all
   held `2`, two held `1`) and couldn't be told apart from values alone -
   `0x0E0`/`0x10C`/`0x170`/`0x1BC` (2 each) and `0x17C`/`0x180` (1 each). Resolved by writing
   distinct sentinel values (1001-1006) directly into those 6 offsets in saveslot03's TROPHY.DAT
   (checksum recomputed with EDF4.1's plain CRC-32-over-`data[0x18:]` scheme, re-encrypted with the
   fixed AES-CTR key/IV), having FevGrave load the save and read back which Battle History row
   showed which sentinel, then restoring the original bytes from a pre-edit backup. Result:
   `0x0E0`=`quadrupeds_defeated`, `0x10C`=`greater_wild_dragons_defeated`,
   `0x170`=`giant_flying_bug_nests_destroyed`, `0x1BC`=`argos_defeated`,
   `0x17C`=`motherships_defeated`, `0x180`=`brains_defeated`. Two of the six (`0x0E0`/`0x10C`)
   landed opposite a proximity-based guess floated earlier the same day - concrete confirmation
   that byte order does not track the Battle History screen's display order here, so this
   sentinel-value technique (rather than positional guessing) is the reliable way to resolve any
   future ties in this file.

**Update 2026-09-06 (FevGrave, confirmed):** the ~26 difficulty-completion-rate percentages Battle
History displays (5 difficulties x Overall + 4 classes, plus the all-difficulty/all-class rate)
are CALCULATED by the game at display time, not read from TROPHY.DAT - matching what the byte-scan
already suggested (only 3 small nonzero floats exist anywhere in the 1024-byte file at all: `0x104`,
`0x124`, `0x1D8`, nowhere near enough for 26 distinct stored rates). `easy_completion_rate_overall`/
`_fencer`/`_ranger` (`0x124`/`0x12C`/`0x1A0`) have been renamed to `unknown_float_0x124`/`0x12C`/
`0x1A0` in `EDFSaveEditorLogic.py` - they're still real, present float fields, just not what their
old names claimed, and not yet identified. (0x124's ~0.0109 on saveslot03 happening to round to
that save's real Very Hard Overall rate of 1% now reads as coincidence rather than a clue, now that
"these rates aren't stored" is the confirmed explanation rather than a mislabeling.) Resolving what
these 3 floats actually are needs the same sentinel-value technique used below for the contested
int fields. Also open: "Games Started: 47" on saveslot03 was not found anywhere as a raw int32 -
likely a computed sum (e.g. offline + online games started) rather than its own stored field.

**Second-save cross-check, same day (saveslot00, FevGrave's older reference save with a real
`TROPHY.DATr` decrypt already on hand):** Battle History reads Missions as Ranger = 5, Missions as
Fencer = 4 on this save (vs. 7/0 on saveslot03). Byte-scanned both the live encrypted `TROPHY.DAT`
and the pre-existing `TROPHY.DATr` reference decrypt (values matched between the two, as expected)
- `0x1B4 = 5` re-confirms `missions_as_ranger` across a second, independent save, and `0x140 = 4`
was a clean unambiguous match for the previously-unplaced `missions_as_fencer`, now added to
`EDF41_KILL_FIELDS`. Still need real values for Missions as Wing Diver/Air Raider from a save
where those aren't obscured on-screen to pin down their offsets the same way.

## Planned features (backlog)

- **Controls/keybind editor for COMMON.CFG.** The per-class "Operation Controls" fields
  (Attack, Jump, Reload, Sprint, vehicle/combat-frame/barga/depth-crawler/helicopter controls,
  one block each for Ranger/Wingdiver/AirRaider/Fencer) are already fully labeled by the
  hexbm bookmarks with exact offsets - see the COMMON.CFG section above. Not built yet;
  revisit when there's time for the UI work (a lot of individual fields to lay out).
- **Color customization panel** for the `0x15C`-`0x19DC` region - implemented. See
  `COLOR_CLASSES`/`COLOR_TIERS`/`load_all_color_groups()` in `EDFSaveEditorLogic.py` and the
  "Color Customization" section in `EDFSaveEditorMain.py`. Structure confirmed both by direct
  byte analysis and independently by the project owner's own recollection of the format (RGBA
  as 4x float32, 12 palettes split Primary/Secondary) before this was built.

## Open questions

Resolved this round (see sections above for detail): shared-header `0x10` (originally logged as
an inert job context value; UPGRADED 2026-09-01 - it's the "save generation ID" behind "Slot
Corrupted", load-side enforcement now traced, see its table row above and
`SaveGenerationID_ForgeryShenanigan()`), MAIN.GST `0xA4` (hypothesis revised, still
unidentified but no longer mislabeled as "probably unused Fencer slot"), the `0x3E98`
"Default Settings...Head" <-> `protected_ids` connection (confirmed - it's the default/starter
weapon-ID table), and the TROPHY.DAT achievement flags (confirmed simple boolean array,
matches existing code exactly).

Still open:

- MAIN.GST `0x24`-`0x28`: unidentified 4-byte field, zero in the one reference save - no
  further evidence found.
- Exact byte boundary of the Player 2 color/loadout block (candidates cluster around `0x3E98`,
  not pinned to the byte). Tried tracing the GST-specific load/save wrapper via Ghidra to
  nail this precisely; hit a wall - `GameDataMgr` has 600+ read xrefs across the codebase (it's
  the central live game-state hub), making the one relevant call site impractical to find by
  hand without a live debugger. The constructor-loop evidence in `EDFSaveEditorLogic.py`
  remains the best available estimate.
- COMMON.CFG `0x34`-`0xC4` and the six `0x102C`-`0x2814` header blocks: action-ID-ordering
  hypothesis, not decoded to individual fields. Low priority (config/UI data, not save
  progress).
- DEFP_M00.MST `0x16C8` "TailFlagA" and `0x16CE` DLC variant marker: not decoded.
- **RESOLVED - EDF5 Online vs Offline save data is two entirely separate `.MST` files per mission
  pack, not two tables in one file.** Confirmed by the project owner: EDF5 ships 6 `DEFP_M0N.MST`
  files (`N` = 0-5), laid out as **Offline, Online, in that order, x 3 mission packs** (base game,
  DLC1, DLC2):
  | File | Meaning |
  |---|---|
  | `DEFP_M00.MST` | EDF5 Offline (base) |
  | `DEFP_M01.MST` | EDF5 Online (base) |
  | `DEFP_M02.MST` | EDF5 Offline DLC1 |
  | `DEFP_M03.MST` | EDF5 Online DLC1 |
  | `DEFP_M04.MST` | EDF5 Offline DLC2 |
  | `DEFP_M05.MST` | EDF5 Online DLC2 |

  All 6 are byte-identical in format (same `5856`-byte size, same `MDB0` header, same body layout -
  see `EDF5_SAVE_FORMAT_NOTES.md` for the full field map) - only the actual progress bytes differ.
  **Modded mission packs follow the same convention**: a modded pack gets its own Offline/Online
  pair of `.MST` files, not a single file - worth keeping in mind since `config.json`'s
  `modded_mission_totals` (and `games_metadata`'s `'missiontable'` field in
  `EDFSaveEditorMain.py`) currently model one filename per game-mode entry, which already fits this
  shape naturally (each Offline/Online row just points at its own file), but wiring in a NEW modded
  pack will need two files created/tracked together, not one. `games_metadata`'s `'EDF5 Offline'`/
  `'EDF5 Online'`/`'...DLC1'`/`'...DLC2'` entries still say `'missiontable': 'Unknown.MST'` and
  `'coming_soon': True` - now that the real filenames are known (table above) those placeholders
  could be filled in, but the mission-table offsets they'd read are only byte-diff-confirmed for
  `DEFP_M00.MST`'s Player 1 table (`0x1C`-`0x21B` in EDF6-raw terms) - the rest of `EDF5`'s
  `MAIN.GST`/`TROPHY.DAT`/`COMMON.CFG` fields are a mix of CONFIRMED and HYPOTHESIS (see
  `EDF5_SAVE_FORMAT_NOTES.md`), so flip `coming_soon` off deliberately, not as a drive-by edit.

**Verification method going forward:** the gold standard remains byte-diffing a save file
before/after a specific real in-game action (the same method that nailed the mission table
and armor current/max offsets). Static analysis and hexbm bookmarks are good for narrowing
down where to look, not a substitute for that when the stakes are "this could corrupt a real
save."

## 2026-09-08 (same day, cont'd 4) - EDF5 Kill Statistics table reconciled via Achievement.sgo

Same treatment as EDF4.1 and EDF6 earlier this session, applied to EDF5. Source file:
`D:\EDF_GhidraRE_Documents\Real Files\Achievement.json` (a decoded `Achievement.sgo`, supplied by
FevGrave without an explicit game label - identity established empirically below, not assumed).
Contents: 39 `AchievementEvent` entries, 71 `AchievementVariable` entries (name, type ["int"/
"float"], default value).

**Game-identity proof.** The file carries no game field. Confirmed EDF5 (not EDF4.1, despite
Ghidra apparently having a `0x140000000`-based binary loaded when FevGrave pointed at a
same-shaped symbol - `0x140ec5810`, which sits in `.rdata` [`140c97000`-`1410e95ff`], not `.text`,
so it's a data/RTTI symbol, not a function; `get_function_by_address` returned nothing there, and
no further Ghidra work was needed once the reconciliation below made the identity certain another
way): the file's 71 variable names, sorted alphabetically and packed as sequential 4-byte slots,
reproduce EDF5's existing, independently-derived (~40 live-diff-tested) `EDF5_KILL_FIELDS` table's
offsets and types exactly, with zero conflicts. That match is only possible if this JSON's
variables are EDF5's own Achievement.sgo contents.

**Reconciliation.** Same technique as EDF4.1/EDF6: matched a handful of old semantic field names to
their obvious real-name equivalents, computed `implied_base = real_offset - alphabetical_index*4`
per anchor:

| old name (EDF5_KILL_FIELDS) | real name | old offset | alphabetical idx | implied base |
|---|---|---|---|---|
| armor_value_air_raider | AirRaiderArmor | 0xE8 | 0 | 0xE8 |
| missions_as_air_raider | AirRaiderPlayCount | 0x100 | 6 | 0xE8 |
| armor_value_fencer | FencerArmor | 0x130 | 18 | 0xE8 |
| missions_as_fencer | FencerPlayCount | 0x148 | 24 | 0xE8 |
| gameplay_time_frames | FrameCount | 0x150 | 26 | 0xE8 |
| armor_value_ranger | RangerArmor | 0x1B8 | 52 | 0xE8 |
| missions_as_ranger | RangerPlayCount | 0x1D0 | 58 | 0xE8 |
| rescues | RescueCount | 0x1D4 | 59 | 0xE8 |
| shield_bearers_defeated | ShieldBearerKillCount | 0x1D8 | 60 | 0xE8 |
| weapons_acquired | WeaponCount | 0x1E0 | 62 | 0xE8 |
| weapon_acquisition_rate | WeaponGetRatio | 0x1E4 | 63 | 0xE8 |
| armor_value_wingdiver | WingDiverArmor | 0x1E8 | 64 | 0xE8 |
| missions_as_wingdiver | WingDiverPlayCount | 0x200 | 70 | 0xE8 |

13/13 unanimous on base `0xE8`. A 14th candidate pairing (`teleportation_anchors_defeated` @
0x17C -> `TeleportionAnchorKillCount`) was tried and rejected: at base 0xE8,
`TeleportionAnchorKillCount` actually lands at 0x1DC - a slot the old 40-entry table simply never
had a name for (it wasn't among the ~40 live-diffed fields), not a conflicting shift. That gap
being real, previously-unlabeled data - rather than proof against 0xE8 - was confirmed by
re-validating ALL 40 old entries against base 0xE8: zero offset conflicts, zero type mismatches
(every old float/int type matches Achievement.sgo's declared type exactly), and the old table's
last known entry (`missions_as_wingdiver` @ 0x200) lands exactly on the new table's last slot -
same clean end-to-end boundary match EDF6 got.

About 30 of the 40 old entries also have strong-to-exact semantic correspondence to their real
names beyond just the anchors above: `motherships_defeated`->`MotherShipKillCount`,
`araneas_defeated`->`NephilaKillCount` (Nephila is a real-world giant-spider genus - EDF's own
Latin-esque codename), `deroys_defeated`->`DeiroiKillCount`, `hives_defeated`->
`HornetNestKillCount`, `teleportation_ships_defeated`->`Carrier1KillCount`,
`outpost_bases_defeated`->`FortressKillCount`, `mother_monsters_defeated`->
`GiantAntQueenKillCount`, `queens_defeated`->`GiantBeeQueenKillCount` (two different "queen" old
guesses correctly landing on the two different real Queen fields), `online_missions_started`->
`OnlinePlayCount`, `imperial_drones_defeated`->`ImperialUfoAceKillCount`, `armor_item_acquisition`
->`ArmorCount`, `armor_value_*`/`missions_as_*` above. The remaining ~10
(`teleportation_devices_defeated`->`AntHillKillCount`, `kings_defeated`->
`BigGiantSpiderKillCount`, `silver_man_defeated`->`BigGreyBossKillCount`,
`giant_tadpoles_defeated`/`tadpoles_defeated`->`DragonAceKillCount`/`DragonKillCount`,
`colonists_defeated`->`FrogKillCount`, `cosmonauts_defeated`->`GreyKillCount`,
`missions_started`->`OfflinePlayCount`, `teleportation_anchors_defeated`->`HardClearRatio`) are
just cases where the original live-diff session's semantic guess was wrong, unsurprising since
byte-diffing after an action doesn't reveal true meaning the way a real Achievement.sgo name does.

**Result:** `EDF5_KILL_FIELDS` in `EDFSaveEditorLogic.py` replaced with the full 71-entry table
(0xE8-0x200, gapless, zero unresolved slots - a cleaner result than EDF4.1's 6-slot gap, matching
EDF6's zero-gap outcome). Old 40-entry semantic-guess table's real names/types are fully
superseded; its offsets, all confirmed correct, are preserved unchanged under new names.
`EDF5_ACHIEVEMENT_VARIABLES` alias added (mirrors EDF4.1/EDF6 pattern).

**EDF5_ACHIEVEMENT_EVENTS** (39 entries) added for reference, same shape as EDF6's (32x
Conquest5-100 + MasterRanger/WingDiver/AirRaider/Fencer + Rescue/SuperRescue/Medic, identical
thresholds). NOT wired into the UI: EDF5 already has its own working (if unverified-shift) stored
byte-flag Achievements panel at `0x14+0xC`/`0x34+0xC` (see `EDFSaveEditorLogic.py`'s
`load_save_data`, the "3-game audit 2026-09-07" comment - the `+0xC` shift itself is still
unverified against a real EDF5 save, unlike everything else in this reconciliation, and remains
out of scope here since it's a separate byte-flag region, not the counter table). Useful
corroboration found along the way: the 39 events' exact Conquest-percentage sequence and 7-item
"other achievements" order match the panel's hardcoded `percentages` list and
`other_achievements_names` order exactly, which is independent evidence the panel's *shape*
assumption (32+7 = 39 achievements, same order) is right, even though the `+0xC` byte-offset
question is untouched.

Compiled clean; tested via the stubbed-tkinter harness (71-entry integrity, contiguous 4-byte
slots, no duplicate names, `get_kill_fields_table('EDF5')` routing, `extract_kill_fields`
round-trip write/read for every slot including the new `TeleportionAnchorKillCount` gap-fill,
`humanize_field_key` display formatting) - not yet checked against a real EDF5 TROPHY.DAT (none
available this session), same caveat as EDF6's reconciliation.

**Achievements tab warning banner removed.** With EDF4.1, EDF6, and now EDF5 all reconciled
against real Achievement.sgo data, the standing yellow "asserted from EDF6's layout... 6 of the 76
raw counter slots are still unidentified" disclaimer (added earlier this document, back when only
EDF4.1's counters were shaky) was stale and no longer described the app's actual state - removed
per FevGrave's request. Deleted `self.achievement_warning_label` and its pack call from
`EDFSaveEditorMain.py`, and the now-unused `achievement_panel_warning` key from all 5 languages in
`languages.json` (removed via a CRLF-preserving script, JSON validity and line-ending count
verified after). The real remaining caveats (EDF4.1's 6 still-unnamed slots at 0xC8-0xDC, EDF5's
achievement-panel `+0xC` shift being unverified against a real save) still exist and are documented
in this file, just no longer surfaced as an in-app banner.

## 2026-09-08 (same day, cont'd 5) - Kill Statistics ClearRatio fields read 0: found a real EDF6
## byte-alignment bug, fixed by computing ClearRatio from the Mission Table instead of raw bytes

FevGrave reported every `*ClearRatio` field in the EDF6 Kill Statistics panel reading 0 despite a
save with real playtime (Wing Diver Play Count 28, Weapon Count 1569). Checked against real
decrypted save data rather than guessing.

**Root cause 1 - confirmed the byte offsets are wrong, not just "not yet earned."** Decrypted
`DUMP/_previous/2026-09-03_13-21-11/TROPHY.DATr` (a real, played EDF6 save) and searched it for the
exact default armor floats from EDF6's own Achievement.sgo (`RangerArmor`/`AirRaiderArmor` = 200.0,
`FencerArmor` = 250.0). Found `200.0` at file offset `0xE4` and `250.0` at `0x128` - but this
session's earlier 91-entry `KILL_FIELDS` table (the "17/17 anchors unanimous, zero gaps" EDF6
reconciliation from earlier today) claims `AirRaiderArmor` lives at `0xDC` and `FencerArmor` at
`0x140`. The gap between the two real hits is `0x44` (17 slots); the table's gap between those same
two fields is `0x64` (25 slots) - not a uniform shift, meaning the whole alphabetical-index mapping
built earlier today has a real error, not just an offset-by-N problem. That reconciliation was pure
semantic-name-guessing (matched to an older, itself-unverified 52-entry table) and was never checked
against a live decrypted save, a caveat flagged at the time and now confirmed to matter. Further
scanning turned up more casualties in the same table: `PlayCount`/`OnlinePlayCount` reading in the
billions, `HornetNestSnallKillCount`/`MartianKillCount`/`BerserkerAKillCount` showing the
[big-float][tiny-int] pairing pattern typical of a struct-alignment error. **This part is still
unresolved** - see the new PROGRESS.md-equivalent task ("Re-verify EDF6 91-slot KILL_FIELDS table
against real save") - fixing it properly needs real Ghidra RE on EDF6.dll (base `0x180000000`) to
find the actual deserializer, the same method that nailed EDF4.1's layout, not further semantic
guessing. Ghidra wasn't reachable this session (`127.0.0.1:8080` connection refused).

**Root cause 2 - the deeper, actually-fixable issue: `*ClearRatio` fields were never reliable raw
bytes to begin with.** This mirrors EDF4.1's CONFIRMED 2026-09-06 finding: the Battle History
screen's difficulty-completion percentages are CALCULATED live from mission-table completion bits,
not stored - only 3 stray floats existed in that entire 1024-byte file, nowhere near enough for the
~26 distinct rates needed. All three games' Achievement.sgo declare the same ~26 `*ClearRatio`
AchievementVariable names (1 `AllClearRatio` + 5 difficulty-only + 4 classes x 5 difficulties),
identically spelled CamelCase across EDF4.1/EDF5/EDF6. Rather than keep chasing unreliable raw
bytes for exactly the field family with a confirmed compute-don't-read precedent, these are now
**always computed live from the Mission Table**, sidestepping the byte-offset question entirely for
these 26 fields regardless of whatever state the broader table verification is in.

**Fix implemented (`EDFSaveEditorLogic.py`):**
- `CLEAR_RATIO_DIFFICULTIES` (Easy=0x01/Normal=0x02/Hard=0x04/Hardest=0x08/Inferno=0x10, matching
  `DIFFICULTY_BITS` in `EDFSaveEditorMain.py`) and `CLEAR_RATIO_CLASSES` (Ranger/WingDiver/
  AirRaider/Fencer, matching `mission_arrays`' index order).
- `is_clear_ratio_key(key)` - true for any of the 26 field names.
- `compute_clear_ratios(mission_arrays, total_missions, game)` - same `cleared`/`total_missions*20`
  math `update_completion()` already uses for the overall %, extended per-class and per-difficulty.
  EDF4.1 scales as 0.0-1.0 float (its `AchievementEvent` thresholds use `>= 1`); EDF5/EDF6 scale as
  0-10000 int (thresholds use e.g. `Conquest100` `>= 10000`). Returns `{}` if `mission_arrays`/
  `total_missions` aren't populated yet (no save loaded).
- `save_save_data()`: before `write_kill_fields()`, merges `compute_clear_ratios(...)` over
  `app.kill_fields` so a Save writes the computed value, not whatever `extract_kill_fields()` read
  from the (unverified) byte offset.

**UI wiring (`EDFSaveEditorMain.py`):**
- `update_kill_fields()`: computes `clear_ratios` once per refresh and uses it in place of
  `kill_fields.get(key, 0)` for any of the 26 keys, same `mission_arrays`/`total_missions` inputs
  `update_completion()` already relies on, so it's always in sync with the Mission Table tab.
- `on_kill_cell_edit()`: rejects edits to `*ClearRatio` cells (reverts via `update_kill_fields()`)
  instead of committing them into `app.kill_fields` - editing a cell that doesn't correspond to a
  real writable byte would silently do nothing in-game and risk landing on whatever real field is
  actually at that (still-unverified) offset once EDF6's table gets properly re-derived.

**Tested:** `compute_clear_ratios()` against the same real save's decrypted `DEFP_M00.MSTr` (147
total EDF6 missions) now returns 26 nonzero-where-expected values (`AllClearRatio=10` i.e. 0.10%,
`EasyClearRatio=17`, `NormalClearRatio=34`, `RangerEasyClearRatio`/`RangerNormalClearRatio`/
`WingDiverNormalClearRatio=68` each) instead of all zero - consistent with a low-progress save where
only a couple of Easy/Normal missions have been cleared by Ranger/Wing Diver. `is_clear_ratio_key()`
correctly excludes non-ratio keys (`WeaponCount`, `FrameCount`, etc.). Compiled clean.

## 2026-09-08 (same day, cont'd 6) - Real Kill Statistics display names + ClearRatio % formatting

Two follow-ups once the ClearRatio fix above was confirmed live on a real save:

**1. `10000` reads as ten thousand kills, not 100.00%.** `*ClearRatio` cells were showing the raw
scaled value from `compute_clear_ratios()` (`10000` for 100%, `5850` for 58.50%) in the same "Count"
column as genuine kill counters, with no unit shown - easy to misread. Added
`format_clear_ratio_display(key, val, game)` in `EDFSaveEditorLogic.py`: converts the 0-10000
int (EDF5/EDF6) or 0.0-1.0 float (EDF4.1) into an `"NN.NN%"` string, and `update_kill_fields()` in
`EDFSaveEditorMain.py` now uses it for every `is_clear_ratio_key()` row instead of the bare number.
Verified: `RangerEasyClearRatio=68` (int, EDF6 scale) -> `"0.68%"`; the same value on EDF4.1's float
scale (`0.5825`) -> `"58.25%"`.

**2. Real in-game display names, not CamelCase-split guesses.** FevGrave asked to find the actual
text-string assets for the Kill Statistics field names, since `humanize_field_key()`'s
CamelCase-splitting (`'AntHillKillCount'` -> "Ant Hill Kill Count") is only ever a guess and
sometimes badly wrong - the real in-game label for that exact field is "Teleportation Devices
Defeated", nothing to do with an ant hill. Found the real source: EDF6's own shipped localization
asset, `F:\...\EARTH DEFENSE FORCE 6\Root\ETC\TEXTTABLE_STEAM.EN.TXT_SGO`, which already had a
decoded sibling `TEXTTABLE_STEAM.EN.TXT.json` sitting right next to it (same OGS-SGO typed-tree
JSON shape as `ACHIEVEMENT.json`). It contains a `StatusInfo_<FieldName>` -> English label entry
for every single stat the game's own Battle History screen displays - literally the exact strings
the shipped UI code looks up, not a reconstruction.

Extracted all 91 `StatusInfo_*` entries (stripped the trailing `:` the game appends itself) into
`EDF6_STATUS_INFO_NAMES` in `EDFSaveEditorLogic.py`. Cross-checked against `KILL_FIELDS`: 90/91
names match exactly key-for-key; the sole non-match is `GuardDamage`, which simply has no Battle
History row (Achievement.sgo-only, not a UI bug) - strong independent confirmation that this
session's Achievement.sgo-derived field *names* (as opposed to the still-unverified byte offsets,
see the entry above) are correct. Notable real-name surprises this turned up: `AntHillKillCount` =
"Teleportation Devices Defeated", `BigGiantSpiderKillCount` = "Kings Defeated", `BigGreyBossKillCount`
= "Silver Man Defeated", `GreyKillCount` = "Cosmonauts Defeated", `GiantAntQueenKillCount` = "Mother
Monsters Defeated" - the internal Achievement.sgo variable name and the shipped English label often
don't correspond at all, which is exactly why `humanize_field_key()` alone was never going to be
reliable for these.

Added `real_field_display_name(key, game)`: returns the real EDF6 name when known, else falls back
to `humanize_field_key()` (used as-is for EDF5/EDF4.1, and for EDF6 fields outside the 90, i.e. just
`GuardDamage`). Wired into `rebuild_kill_sheet_for_game()` in `EDFSaveEditorMain.py`, ahead of the
app's own translation dict lookup so real game text wins whenever available.

**Scope/caveat (superseded below):** English only, EDF6 only, at the time this was first written -
see the next entry for the full 5-language upgrade that followed within the same session.

## 2026-09-08 (same day, cont'd 7) - All 5 languages' real Kill Statistics names, via FevGrave's
## own AA-Master-Printer tool

FevGrave ran their own `AA-Master-Printer` utility (option 2, "(SGO) TO (JSON)") over EDF6's
`Root\ETC\` folder, which is the actual OGS-SGO decoder this project didn't have Windows access to
run itself (see the caveat above). That produced decoded siblings for all 5 of EDF6's shipped
`TEXTTABLE_STEAM.<LANG>.TXT_SGO` localization files, not just the EN one: `TEXTTABLE_STEAM.EN.TXT.json`,
`.JA.TXT.json`, `.KR.TXT.json`, `.SC.TXT.json`, `.CN.TXT.json`.

Parsed all 5 and confirmed each has the identical 90-key `StatusInfo_*` set (matching `KILL_FIELDS`
minus `GuardDamage`, as already established for EN). App language code mapping confirmed by content,
not just filename: the app's `cn` (Traditional) and `sc` (Simplified) sections correspond exactly to
the game's `CN.TXT_SGO` and `SC.TXT_SGO` respectively (e.g. `AntHillKillCount`: `cn` = "傳送裝置擊破數"
uses traditional 傳/擊, `sc` = "传送装置击破数" uses simplified 传/击).

**Where this landed:** not a second Python dict this time - inserted directly into `languages.json`'s
existing per-language translation sections (`en`/`ja`/`kr`/`cn`/`sc`), 90 new top-level keys per
language (450 total), keyed by the bare field name (e.g. `"AntHillKillCount"`) so the app's existing
`trans.get(key, ...)` lookup in `rebuild_kill_sheet_for_game()` picks them up automatically with zero
further code changes - real game text now wins over `real_field_display_name()`'s fallback in every
UI language, not just English. Verified no key collisions with any of the file's existing 354 keys
before inserting. Edited via the same CRLF-preserving script pattern used earlier this session
(`newline=""` on both read and write, matched brace-depth insertion point per language section,
verified after: CRLF count +455 - 450 new lines + 5 reindented closing braces - zero bare LF
introduced, JSON re-parses, and every inserted value reads back correctly per language).

**Known limitation, stated plainly rather than silently assumed:** these 90 names are sourced from
EDF6's own TEXTTABLE only. EDF5's `KILL_FIELDS` table uses the identical Achievement.sgo naming
scheme and shares many of the same enemy-type field names (both games' name sets were independently
derived from their own real Achievement.sgo dumps this session), so EDF5's Kill Statistics panel
inherits these same labels via the same shared `trans.get()` lookup - the ~20 generic fields (Armor/
PlayCount/ClearRatio/RescueCount/HealDamage/FrameCount/WeaponCount) are very likely identical wording
between the two games given the shared UI/engine convention, but the monster-specific KillCount
labels (e.g. `BigGreyBossKillCount` = "Silver Man Defeated") have NOT been confirmed against EDF5's
own TEXTTABLE - that file wasn't available this session (EDF5's install folder isn't mounted).
Re-verify against EDF5's own `TEXTTABLE_STEAM.<LANG>.TXT_SGO` (decoded the same way, via
AA-Master-Printer) if/when that install becomes available, in case any shared-name field's wording
actually differs between the two games. EDF4.1 doesn't share this scheme at all for its own field
set beyond a handful of identically-named generic fields, and still falls back to
`humanize_field_key()` entirely.

Compiled clean; spot-checked `trans.get('BigGreyBossKillCount', ...)` against all 5 languages'
in-memory dicts post-edit, matches the source TEXTTABLE values exactly.

## 2026-09-08 (same day, cont'd 8) - CORRECTION: real names needed per-game namespacing, not a
## shared flat key - caught before shipping, using EDF4.1's own TEXTTABLE as the counter-example

FevGrave pointed at `D:\EDF_GhidraRE_Documents\Real Files`, which turned out to hold EDF4.1's own
decoded TEXTTABLE files (`TEXTTABLE_STEAM_EN.TXT_.json`, `_CN.TXT.json`, `_JP.TXT.json` - EDF4.1
uses "JP" where EDF6 used "JA", same language). Parsing EN gave 70 `StatusInfo_*` entries, 69/70
matching `EDF41_KILL_FIELDS`' real names exactly (the miss, `elevation`, has no Battle History row -
same pattern as EDF6's `GuardDamage`).

**Caught a real bug in the previous entry's design before it shipped further.** Cross-checking
EDF4.1's 69 real names against the 90 already added for EDF6 (previous entry) found 55 overlapping
field names - i.e. the same internal Achievement.sgo variable name exists in both games' counter
tables - and **13 of those 55 have completely different real meanings per game**:

| field name | EDF6 real label | EDF4.1 real label |
|---|---|---|
| `DragonKillCount` | Tadpoles Defeated | Dragons Defeated |
| `BigGiantSpiderKillCount` | Kings Defeated | King Spiders Defeated |
| `Carrier1KillCount` | Teleportation Ships Defeated | Transport Ships Destroyed |
| `GiantAntKillCount` | Aggressive Alien Species \u03b1s Defeated | Ant-Type Bugs Defeated |
| `GiantAntQueenKillCount` | Mother Monsters Defeated | Queens Defeated |
| `GiantBeeKillCount` | Flying Aggressors Defeated | Flying-Type Bugs Defeated |
| `GiantBeeQueenKillCount` | Queens Defeated | Death Queens Defeated |
| `GiantSpiderKillCount` | Aggressive Alien Species \u03b2s Defeated | Spider-Type Bugs Defeated |
| `HardestClearRatio` | Hardest Difficulty Completion Rate | Very Hard Difficulty Completion Rate |
| `HornetNestKillCount` | Hives Defeated | Giant Flying-Type Bug Nests Destroyed |
| `NephilaKillCount` | Araneas Defeated | Retiarii Defeated |
| `ArmorCount` | Armor Item Acquisition | Armor Item Acquisition Rate |
| `WeaponCount` | Weapons Acquired | Acquired Weapons |

The previous entry's design (inserting these as bare, shared keys like `"DragonKillCount"` directly
into languages.json, read via a single flat `trans.get(key, ...)`) would have shown EDF6's label on
an EDF4.1 save (or vice versa) for all 13 of these - the exact same class of "wrong but confident-
looking" bug this whole effort was meant to fix, just moved from the byte-offset layer to the
display layer. This was caught and corrected before the app was reported as fixed, not discovered
by a user after the fact.

**Also caught:** `TEXTTABLE_STEAM_CN.TXT.json` and `TEXTTABLE_STEAM_JP.TXT.json` are byte-identical
(verified via `md5sum` - same hash, same file size, same mtime) - EDF4.1's "Chinese" decode is
actually just a copy of the Japanese one, not real Chinese text. Excluded entirely rather than
inserted as wrong data; EDF4.1 currently has real names for English and Japanese only.

**Fix - migrated to per-game key namespacing:**
- Removed the 450 bare keys inserted in the previous entry (exact-block removal, verified all 5
  found and removed, back to the original 354 keys/language).
- Re-inserted under a game-prefixed key instead: `EDF6_<FieldName>` (all 5 languages, 90 keys each,
  450 total) and `EDF41_<FieldName>` (en + ja only, 69 keys each, 138 total) - zero collisions
  possible between games now, by construction.
- `EDFSaveEditorLogic.py`: added `EDF41_STATUS_INFO_NAMES` (English fallback dict, same shape as
  `EDF6_STATUS_INFO_NAMES`) and `kill_stat_lang_prefix(game)` (`'EDF41_'`/`'EDF5_'`/`'EDF6_'`).
  Rewrote `real_field_display_name()` to pick the correct per-game dict (never blends the two).
- `EDFSaveEditorMain.py`'s `rebuild_kill_sheet_for_game()`: lookup is now
  `trans.get(f'{prefix}{key}', real_field_display_name(key, game))` - prefix computed once per game
  via `kill_stat_lang_prefix()`.
- EDF5 still has no real-name source of its own and was NOT given EDF6's data under any key,
  prefixed or not - the EDF4.1 counter-example proves a shared field name can easily mean something
  different per game, so EDF5 correctly falls through to `humanize_field_key()` for everything until
  its own TEXTTABLE can be pulled the same way (still needs its install folder mounted).

**Verified after the fix:** `EDF6_DragonKillCount` (en) = "Tadpoles Defeated";
`EDF41_DragonKillCount` (en) = "Dragons Defeated", (ja) = "\u30c9\u30e9\u30b4\u30f3\u6483\u7834\u6570"
- correctly disambiguated. `EDF5`'s lookup for the same field correctly falls through to
`humanize_field_key()` ("Dragon Kill Count") rather than inheriting either game's real text. CRLF
preserved throughout (removal + reinsertion both verified via exact CRLF/bare-LF counts), JSON valid,
compiled clean.
