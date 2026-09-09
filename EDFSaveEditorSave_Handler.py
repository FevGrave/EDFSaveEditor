# EDFSaveEditorSave_Handler.py
import os
import re
import struct
import hashlib
import zlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# EDF 4.1 fixed AES-128 key/IV. Confirmed via Ghidra RE of EDF41.exe's key-setup routine (RVA
# 0x0D5360; RTTI confirms CryptoPP Rijndael with CTR_ModePolicy + Weak1::MD5). Derivation - a real
# bug in the game's own code, not ours: it measures the seed string in *characters* but copies it
# as *bytes*, so only the first len(s) BYTES of the UTF-16LE buffer get hashed (chopping the last
# character in half for an odd-length seed), then the digest is hashed a second time:
#   key = MD5(MD5(utf16le("edf4.1_save")[:11 bytes]))   (seed is 11 chars -> odd -> truncated mid-char)
#   iv  = MD5(MD5(utf16le("edf4.1")[:6 bytes]))          (seed is 6 chars, even, so no truncation here)
# The filename is NOT part of the derivation - every file in an EDF4.1 SAVE_DATA folder (MAIN.GST,
# every *.MST, COMMON.CFG, TROPHY.DAT) shares this one fixed key/IV, unlike EDF5/6's per-filename
# scheme in generate_key_iv() below.
# Kept as hardcoded constants (not computed via the formula above every call) so a future edit that
# "simplifies" the truncation trick - it looks like a bug at a glance - can't silently break EDF4.1
# decryption; _verify_edf41_seed_derivation() below re-derives them at import time purely to prove
# this comment is still accurate, and is not on the actual decrypt path.
_EDF41_KEY = bytes.fromhex("DBD394C9E09C52CE77467D6A9F913C81")
_EDF41_IV  = bytes.fromhex("F5A9402744EE8C270B2E6D97A9C430CA")

def _edf41_seed(text: str) -> bytes:
    """Reference implementation of the derivation documented above - reproduces _EDF41_KEY/_EDF41_IV
    exactly when called with "edf4.1_save"/"edf4.1". Not used on the hot decrypt path; exists so the
    comment above is a checkable claim, not just prose, and so anyone re-deriving this for a related
    EDF title has a working reference."""
    truncated = text.encode("utf-16le")[:len(text)]
    return hashlib.md5(hashlib.md5(truncated).digest()).digest()

def _verify_edf41_seed_derivation() -> None:
    """Runs once at import time: if this ever fails, either the hardcoded constants above or this
    module's understanding of the derivation has drifted - investigate before trusting EDF4.1 saves."""
    assert _edf41_seed("edf4.1_save") == _EDF41_KEY, "EDF4.1 key derivation no longer matches _EDF41_KEY"
    assert _edf41_seed("edf4.1") == _EDF41_IV, "EDF4.1 IV derivation no longer matches _EDF41_IV"

_verify_edf41_seed_derivation()

# Related finding, 2026-09-08 (not used by this module - documented here since it's the same scheme):
# EDF4.1's DLC "addon:/Config.sgo"/"addon:/Config2.sgo" files (which list what weapons/vehicles each
# Steam DLC unlocks) use this exact same fixed-key AES-128-CTR scheme, just a different key seed:
#   dlc_key = _edf41_seed("edf4.1_dlc")   iv = _edf41_seed("edf4.1")   (same IV seed as the save key)
# Confirmed via Ghidra RE of EDF41.exe FUN_1400d2360 (resolves the addon:/Config[2].sgo path) and
# FUN_1400d5360 (the shared key/iv setup call - same function the save path above calls with
# "edf4.1_save"/"edf4.1"), then verified by decrypting 16 real single-weapon-DLC Config.sgo files
# from D:\EDF_GhidraRE_Documents\Real Files\dlc\ - every one produced a readable "OGS" binary struct
# with plaintext strings ("unlock_weapon", "app_id", "version", weapon sgo names), and every weapon
# name found matches an entry already in EDFSaveEditorLogic.EDF41_DLC_WEAPON_INDICES.
# The 2 mission-pack DLCs (appid 410780 = MP01, 411380 = MP02) were resolved without needing this at
# all: their unpacked dlc.cpk trees were already on disk with decoded Config2.json/PACKAGE.json
# siblings. PACKAGE.sgo's WeaponTable points at the base game's own _WeaponTable.sgo and SoldierInit
# only lists the vanilla starter loadout - neither mission pack defines an unlock_weapon list, so
# there's nothing for EDF41_PROTECTED_RANGES to hold. See EDFSaveEditorMain.py's comment there.

def _make_edf41_cipher() -> Cipher:
    """
    EDF 4.1 cipher using fixed key/IV.
    EDF4.1 appears to use CTR (ciphertext not multiple of block size).
    """
    return Cipher(algorithms.AES(_EDF41_KEY), modes.CTR(_EDF41_IV), backend=default_backend())

def edf41_decrypt(ciphertext: bytes) -> bytes:
    cipher = _make_edf41_cipher()
    decryptor = cipher.decryptor()
    # CTR: no padding, arbitrary length
    return decryptor.update(ciphertext) + decryptor.finalize()

def edf41_encrypt(plaintext: bytes) -> bytes:
    # CTR: no padding, arbitrary length
    cipher = _make_edf41_cipher()
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()

def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    poly = 0x82F63B78
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF

_SUFFIXES = [b"Edf6.*_Steam_Ver", b"Edf5.*_Steam_Ver"]

def _md5_utf16le(s: str) -> bytes:
    return hashlib.md5(s.encode("utf-16le")).digest()

def generate_key_iv(filename: str, game: str = "EDF6") -> tuple[bytes, bytes]:
    """Derive the AES-256-CTR key/iv EDF5/EDF6 use for GST/DAT/CFG/MST save files: `prefix + <literal on-disk filename> + ".sav"/".stm"`, prefix being 'edf5' or 'edf6'. `game` defaults to "EDF6"; pass a string starting with "EDF5" for the EDF5 prefix."""
    base_name = os.path.basename(filename).rsplit('.sav', 1)[0]
    prefix = "edf5" if str(game).upper().startswith("EDF5") else "edf6"
    str1 = f"{prefix}{base_name}.sav"
    str2 = f"{prefix}{base_name}.stm"
    digest1 = _md5_utf16le(str1)
    key = digest1 + b"Edf5.*_Steam_Ver"
    iv = _md5_utf16le(str2)
    return key, iv

def generate_mst_key_iv_variants(filename: str):
    raw = os.path.basename(filename)
    variants = []
    for digit in ("6", "5"):
        for suffix in _SUFFIXES:
            str1 = f"edf{digit}{raw}.sav"
            str2 = f"edf{digit}{raw}.stm"
            k_part = _md5_utf16le(str1)
            if len(suffix) != 16:
                continue
            key = k_part + suffix
            iv = _md5_utf16le(str2)
            variants.append((f"edf{digit}+{suffix.decode('ascii', 'ignore')}", key, iv))
    seen = set()
    uniq = []
    for tag, k, iv in variants:
        if k not in seen:
            seen.add(k)
            uniq.append((tag, k, iv))
    return uniq

def generate_dat_key_iv_variants(dat_file_path: str, related_gst_path: str = None):
    """Yield (tag, key, iv) AES-CTR candidates for decrypting a DAT-style file, in priority order: the related GST's own derived key first, then a digit/base-name brute force, then generate_mst_key_iv_variants()'s own candidates. Does NOT include the EDF4.1 fixed-key scheme - callers needing EDF4.1 should try edf41_decrypt() separately."""
    candidates = []
    if related_gst_path:
        try:
            gst_key, gst_iv = generate_key_iv(related_gst_path)
            candidates.append(("gst_key", gst_key, gst_iv))
        except Exception:
            pass
    base_name = os.path.splitext(os.path.basename(dat_file_path))[0]
    suffix = b"Edf5.*_Steam_Ver"
    for digit in ("6", "5"):
        for base in (base_name, "GAMESTATE"):
            str1 = f"edf{digit}{base}.sav"
            str2 = f"edf{digit}{base}.stm"
            key = _md5_utf16le(str1) + suffix
            iv = _md5_utf16le(str2)
            candidates.append((f"edf{digit}+{base}", key, iv))
    candidates.extend(generate_mst_key_iv_variants(dat_file_path))
    return candidates

def try_decrypt_variants(ciphertext: bytes, candidates, header_check=None):
    """Try decrypting ciphertext with each (tag, key, iv) AES-CTR candidate until header_check(plaintext) returns True (defaults to checking for the MDB0 magic). Returns (plaintext, tag, key, iv) on the first match, or None."""
    if header_check is None:
        header_check = lambda data: data[:4] == b'MDB0'
    for tag, key, iv in candidates:
        try:
            plain = aes_ctr_decrypt(ciphertext, key, iv)
        except Exception:
            continue
        if header_check(plain):
            return plain, tag, key, iv
    return None

def aes_ctr_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    backend = default_backend()
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv), backend=backend)
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()

def aes_ctr_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    backend = default_backend()
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv), backend=backend)
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()

def load_save(file_path: str, game: str = "EDF6") -> bytes:
    """Load+decrypt a GST/DAT/CFG/MST save file. `game` defaults to "EDF6"; pass a string starting with "EDF5" for an EDF5 file, since the two games use different key prefixes."""
    with open(file_path, 'rb') as f:
        ciphertext = f.read()
    key, iv = generate_key_iv(file_path, game=game)
    data = aes_ctr_decrypt(ciphertext, key, iv)
    if data[:4] != b'MDB0':
        raise ValueError("Invalid header after decryption")
    return data

_CRC32C_BODY_START = {"EDF5": 0x20, "EDF6": 0x14}  # see save_save()'s docstring below

def save_save(file_path: str, data: bytearray, game: str = "EDF6"):
    """Re-encrypt+write a GST/DAT/CFG/MST save file. `game` must match the file's actual game or it will be rejected as corrupt. The CRC32C checksum body-start offset differs by game: EDF6 checksums data[0x14:], EDF5 checksums data[0x20:] (12 extra header bytes)."""
    crc = crc32c(data[_CRC32C_BODY_START.get(str(game).upper()[:4], 0x14):])
    checksum = ~crc & 0xFFFFFFFF
    struct.pack_into("<I", data, 0x0C, checksum)
    key, iv = generate_key_iv(file_path, game=game)
    ciphertext = aes_ctr_encrypt(bytes(data), key, iv)
    with open(file_path, 'wb') as f:
        f.write(ciphertext)

# ===== EDF 4.1 save handling using fixed key/IV =====

def load_save_edf41(file_path: str) -> bytes:
    with open(file_path, 'rb') as f:
        cipher = f.read()
    data = edf41_decrypt(cipher)
    # EDF4.1 uses the same MDB0 magic header as EDF5/6 but NOT the same checksum scheme (see save_save_edf41()); this function only checks the magic, not the checksum.
    if data[:4] != b'MDB0':
        raise ValueError("Invalid header after decryption (EDF4.1)")
    return data

def save_save_edf41(file_path: str, data: bytearray):
    """EDF4.1's checksum scheme differs from EDF5/6's: standard CRC-32 (zlib.crc32, no extra bitwise inversion needed) over data[0x18:], not CRC32C over data[0x14:]. Header layout: 0x00 "MDB0" magic, 0x04 format version, 0x08 body length, 0x0C this checksum, 0x10-0x13 the per-slot "save generation ID" (see SaveGenerationID_ForgeryShenanigan), 0x14-0x17 a constant tail (`01 00 10 01`), then the body from 0x18 onward. Confirmed via Ghidra RE cross-checked against 4 real EDF4.1 save files."""
    checksum = zlib.crc32(bytes(data[0x18:])) & 0xFFFFFFFF
    struct.pack_into("<I", data, 0x0C, checksum)
    cipher = edf41_encrypt(bytes(data))
    with open(file_path, 'wb') as f:
        f.write(cipher)

# Header offsets for the per-file "save generation ID" (offset 0x10, 4 bytes - same offset exists
# in all of EDF4.1/5/6, but DOES NOT mean the same thing in each - verified with real save files
# cross-checked against each game's own steam_autocloud.vdf, not assumed from one game to the next:
#   EDF4.1: 0x10-0x13 is genuinely the low 32 bits of the save's owning SteamID64, and 0x14-0x17
#     (the "tail", a fixed `01 00 10 01` in every EDF4.1 file checked) is simply the high 32 bits
#     every individual Steam64 ID shares (universe=1/type=1/instance=1 - constant across every
#     account). The game's "Slot Corrupted" screen (LoadSaveInfo_SlotCorrupt, traced via Ghidra to
#     UiSlotSelect_Main) refuses a slot whose owner id here doesn't match the locally signed-in
#     Steam account, independent of checksum/format validity - this is why a byte-perfect,
#     checksum-valid save from someone else still shows corrupted.
#   EDF5: 0x10-0x13/0x14-0x17 here are NOT SteamID-related - just small counters (observed in the
#     low hundreds). EDF5's real owner Steam64 ID lives whole (all 8 bytes) in
#     EDF5_SESSION_STAMP_OFFSET below, previously logged only as an opaque "session stamp" before
#     a real save file proved it's the account id.
#   EDF6: no embedded owner id was found anywhere in a real save (MAIN.GST/TROPHY.DAT/COMMON.CFG),
#     in any byte order - EDF6 appears to rely on Steam Cloud's own per-account isolation instead.
# See find_foreign_owner_mismatch() for the per-game logic this backs.
EDF_GEN_ID_OFFSET = 0x10
EDF_GEN_ID_SIZE = 4
EDF5_SESSION_STAMP_OFFSET = 0x18
EDF5_SESSION_STAMP_SIZE = 8

def get_save_generation_id(data: bytes) -> bytes:
    """Read the 4-byte field at header offset 0x10-0x13 from an already-decrypted file. For EDF4.1 this is the low 32 bits of the owning Steam64 ID; for EDF5 it's an unrelated small counter (the real owner id is EDF5_SESSION_STAMP_OFFSET instead) - see the block comment above. See SaveGenerationID_ForgeryShenanigan() and find_foreign_owner_mismatch()."""
    return bytes(data[EDF_GEN_ID_OFFSET:EDF_GEN_ID_OFFSET + EDF_GEN_ID_SIZE])

def derive_local_steamid64(folder: str):
    """EDF4.1/5/6 all sandbox saves under a folder literally named after the owning account's
    Steam64 ID (.../SAVE_DATA/<steamid64>/saveslotNN) - walk up from folder looking for that
    segment. Returns the int SteamID64, or None if no plausible segment is found."""
    for part in reversed(os.path.normpath(folder).split(os.sep)):
        if re.fullmatch(r"7656119\d{10}", part):  # SteamID64 individual-account range
            return int(part)
    return None

def find_foreign_owner_mismatch(file_paths, game: str, local_steamid64: int) -> dict | None:
    """Catches the case find_generation_id_mismatch() can't: a save slot copied in wholesale from
    someone else, where every file already agrees with every OTHER file (so no internal mismatch)
    but the baked-in owner ID doesn't match the Steam account actually running the game - the exact
    cause of a byte-perfect, checksum-valid save still showing "Slot Corrupted".

    The owner field is NOT in the same place for all 3 games - confirmed with real save files
    cross-checked against each game's own steam_autocloud.vdf (ground truth for the real account
    id) rather than assumed:
      EDF4.1: the low 32 bits of the owner Steam64 ID live in the "generation ID" field itself
        (0x10-0x13) - see get_save_generation_id()'s docstring.
      EDF5: the FULL 8-byte owner Steam64 ID lives in EDF5_SESSION_STAMP (0x18-0x1F), NOT the
        generation ID field - that one's own "generation ID"/tail bytes are small counters (observed
        in the low hundreds, not SteamID-shaped) unrelated to ownership, and are left alone here.
      EDF6: no embedded owner id was found anywhere in a real MAIN.GST/TROPHY.DAT/COMMON.CFG set
        (searched for the real account's raw id in every byte order - no match). EDF6 appears to
        rely on Steam Cloud's own per-account isolation instead of a redundant embedded check, so
        this always returns None for EDF6 rather than guessing at a field that isn't there.

    Returns None if every file already matches (or EDF6, where there's nothing to check), else a
    dict describing the mismatch."""
    game_u = str(game).upper()
    is_41 = game_u.startswith("EDF4")
    is_5 = game_u.startswith("EDF5")
    if not (is_41 or is_5):
        return None

    expected = (local_steamid64 & 0xFFFFFFFF).to_bytes(4, "little") if is_41 else local_steamid64.to_bytes(8, "little")
    mismatched = []
    for fp in file_paths:
        try:
            data = load_save_edf41(fp) if is_41 else load_save(fp, game=game)
        except Exception:
            continue
        actual = get_save_generation_id(data) if is_41 else bytes(data[EDF5_SESSION_STAMP_OFFSET:EDF5_SESSION_STAMP_OFFSET + EDF5_SESSION_STAMP_SIZE])
        if actual != expected:
            mismatched.append(fp)
    if not mismatched:
        return None
    return {"expected_owner_id": expected.hex(), "mismatched_files": mismatched}

def SaveGenerationID_ForgeryShenanigan(file_paths, game: str = "EDF6", reference_id: bytes = None,
                                        reference_file_path: str = None,
                                        reference_session_stamp: bytes = None) -> dict:
    """THE fix for "The save data in this slot is corrupted" (EDF4.1) / the equivalent "Slot Corrupted" state (EDF5/EDF6) when transplanting files from a different save into a slot. Works for EDF4.1, EDF5, and EDF6. Normalizes a group of on-disk save files (one slot's worth, same game) to a single shared reference owner-ID field (and EDF5's session stamp), re-encrypting and rewriting only the files that didn't already match. Pass either `reference_id`/`reference_session_stamp` or `reference_file_path`; if neither given, the first entry in `file_paths` is used as the reference - fine for "these files got mixed up," but NOT what you want for "this whole slot came from someone else" (every file already agrees with the others there, just on the wrong owner) - pass an explicit `reference_id` derived from the local account instead (see find_foreign_owner_mismatch/derive_local_steamid64).

    Args:
        file_paths: list of on-disk paths to save files (encrypted, as they sit in a save slot
            folder) that together make up one save slot to normalize. Must all be the same game.
        game: which game these files belong to - see generate_key_iv()/load_save() for accepted
            strings. Defaults to "EDF6".
        reference_id: optional explicit 4-byte generation ID to standardize on.
        reference_file_path: optional path to a file whose current generation ID (and, for EDF5,
            session stamp) should be used as the reference (ignored if reference_id is given).
        reference_session_stamp: optional explicit 8-byte EDF5 session stamp to standardize on
            (EDF5 only; ignored for EDF4.1/EDF6).

    Returns:
        dict with 'reference_id' (hex string), 'reference_session_stamp' (hex string or None),
        'patched_files' (paths that were rewritten), and 'already_matching' (paths that already
        matched the reference and were left untouched).
    """
    game_u = str(game).upper()
    is_41 = game_u.startswith("EDF4")
    is_5 = game_u.startswith("EDF5")

    def _load(fp):
        return bytearray(load_save_edf41(fp) if is_41 else load_save(fp, game=game))

    def _save(fp, data):
        if is_41:
            save_save_edf41(fp, data)
        else:
            save_save(fp, data, game=game)

    # gen_id (0x10-0x13) is only meant to be uniform across a slot's files for EDF4.1 - confirmed
    # with real saves that for EDF5/EDF6 it's a per-file-type counter (MAIN.GST carries a real
    # value, TROPHY.DAT/COMMON.CFG/*.MST just leave it 0 even in a normal working save), so it's
    # only read/written here when is_41. EDF5's real owner field is reference_session_stamp
    # instead; EDF6 has no confirmed owner field at all (see find_foreign_owner_mismatch).
    if is_41 and reference_id is None:
        ref_path = reference_file_path if reference_file_path is not None else file_paths[0]
        ref_data = _load(ref_path)
        reference_id = get_save_generation_id(ref_data)
    if is_5 and reference_session_stamp is None:
        ref_path = reference_file_path if reference_file_path is not None else file_paths[0]
        ref_data = _load(ref_path)
        reference_session_stamp = bytes(
            ref_data[EDF5_SESSION_STAMP_OFFSET:EDF5_SESSION_STAMP_OFFSET + EDF5_SESSION_STAMP_SIZE])
    if is_41 and len(reference_id) != EDF_GEN_ID_SIZE:
        raise ValueError(f"reference_id must be exactly {EDF_GEN_ID_SIZE} bytes")
    if is_5 and reference_session_stamp is not None and len(reference_session_stamp) != EDF5_SESSION_STAMP_SIZE:
        raise ValueError(f"reference_session_stamp must be exactly {EDF5_SESSION_STAMP_SIZE} bytes")

    patched, already_matching = [], []
    for fp in file_paths:
        data = _load(fp)
        changed = False
        if is_41 and bytes(data[EDF_GEN_ID_OFFSET:EDF_GEN_ID_OFFSET + EDF_GEN_ID_SIZE]) != reference_id:
            data[EDF_GEN_ID_OFFSET:EDF_GEN_ID_OFFSET + EDF_GEN_ID_SIZE] = reference_id
            changed = True
        if is_5 and reference_session_stamp is not None:
            stamp_slice = slice(EDF5_SESSION_STAMP_OFFSET, EDF5_SESSION_STAMP_OFFSET + EDF5_SESSION_STAMP_SIZE)
            if bytes(data[stamp_slice]) != reference_session_stamp:
                data[stamp_slice] = reference_session_stamp
                changed = True
        if changed:
            _save(fp, data)
            patched.append(fp)
        else:
            already_matching.append(fp)

    return {
        "reference_id": reference_id.hex() if reference_id else None,
        "reference_session_stamp": reference_session_stamp.hex() if reference_session_stamp else None,
        "patched_files": patched,
        "already_matching": already_matching,
    }

def find_generation_id_mismatch(file_paths, game: str = "EDF6") -> dict | None:
    """Read-only check: for EDF4.1, do every file in file_paths (one save slot's worth) already
    share the same owner-id field? For EDF5, do they share the same session stamp (the real owner
    field there)? Catches saves combined from different sources - e.g. a friend's save dropped
    straight into a save folder - before the game itself calls the slot corrupted.

    Deliberately does NOT compare EDF5/EDF6's own "generation ID" field (0x10-0x13) across files -
    confirmed with real saves that it's a per-file-type counter there (MAIN.GST carries a real
    value, other file types just leave it 0 even in a normal working save), so requiring it to
    match across files would false-positive on every valid EDF5/EDF6 save. EDF6 has no confirmed
    cross-file field to check at all, so this always returns None for EDF6.

    Returns None if everything already matches (or nothing to check), else a dict for
    SaveGenerationID_ForgeryShenanigan() to fix. Unreadable files are skipped, not flagged."""
    game_u = str(game).upper()
    is_41 = game_u.startswith("EDF4")
    is_5 = game_u.startswith("EDF5")
    if not (is_41 or is_5):
        return None

    values = {}
    for fp in file_paths:
        try:
            data = load_save_edf41(fp) if is_41 else load_save(fp, game=game)
        except Exception:
            continue
        values[fp] = get_save_generation_id(data) if is_41 else bytes(
            data[EDF5_SESSION_STAMP_OFFSET:EDF5_SESSION_STAMP_OFFSET + EDF5_SESSION_STAMP_SIZE])

    if len(values) < 2 or len(set(values.values())) <= 1:
        return None
    ref_fp = next(iter(values))
    return {
        "reference_file": ref_fp,
        "mismatched_files": [fp for fp in values if values[fp] != values[ref_fp]],
    }

_DEF_MST_HEADER_HINTS = [b'MDB', b'MST', b'EFDP']

def decrypt_mst(file_path: str) -> tuple[bytes, str]:
    with open(file_path, 'rb') as f:
        cipher = f.read()
    best = None
    for tag, key, iv in generate_mst_key_iv_variants(file_path):
        try:
            plain = aes_ctr_decrypt(cipher, key, iv)
        except Exception:
            continue
        head = plain[:64]
        if any(h in head for h in _DEF_MST_HEADER_HINTS):
            return plain, tag
        if best is None:
            if sum(c >= 32 and c < 127 for c in head) / max(1, len(head)) > 0.4:
                best = (plain, tag + "?heuristic")
    if best is not None:
        return best
    raise ValueError("Could not decrypt MST with known variants")

def decrypt_directory(encrypted_dir: str, decrypted_dir: str):
    if not os.path.exists(encrypted_dir):
        raise ValueError(f"Encrypted directory not found: {encrypted_dir}")
    os.makedirs(decrypted_dir, exist_ok=True)
    for filename in os.listdir(encrypted_dir):
        file_path = os.path.join(encrypted_dir, filename)
        if not os.path.isfile(file_path):
            continue
        lower = filename.lower()
        if lower.endswith('.sav'):
            try:
                data = load_save(file_path)
                output_filename = filename[:-4]
                output_path = os.path.join(decrypted_dir, output_filename)
                with open(output_path, 'wb') as f:
                    f.write(data)
                print(f"Decrypted {filename} -> {output_filename}")
            except Exception as e:
                print(f"Error decrypting {filename}: {e}")
        elif lower.endswith('.mst'):
            try:
                data, tag = decrypt_mst(file_path)
                output_path = os.path.join(decrypted_dir, filename)
                with open(output_path, 'wb') as f:
                    f.write(data)
                print(f"Decrypted MST {filename} (key={tag})")
            except Exception as e:
                print(f"Error decrypting MST {filename}: {e}")

def encrypt_directory(decrypted_dir: str, encrypted_dir: str):
    if not os.path.exists(decrypted_dir):
        raise ValueError(f"Decrypted directory not found: {decrypted_dir}")
    os.makedirs(encrypted_dir, exist_ok=True)
    for filename in os.listdir(decrypted_dir):
        file_path = os.path.join(decrypted_dir, filename)
        if not os.path.isfile(file_path):
            continue
        if filename.lower().endswith('.mst'):
            continue
        try:
            with open(file_path, 'rb') as f:
                data = bytearray(f.read())
            output_filename = f"{filename}.sav"
            output_path = os.path.join(encrypted_dir, output_filename)
            save_save(output_path, data)
            print(f"Encrypted {filename} -> {output_filename}")
        except Exception as e:
            print(f"Error encrypting {filename}: {e}")

# PS4 save format (CUSA03131) - findings only, no import path exists yet. A PS4 EDF4.1 save is a raw, still-sealed PS4 PFS container, needing the owning PSN account's AccountID as key material to unseal. This project does not have that and won't derive one for someone else's account; a future "Import PS4 Save" flow could prompt the current user for their own AccountID.