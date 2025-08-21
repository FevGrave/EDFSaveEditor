# Python remake of EDFDecrypt.cpp functionality.
# Supports:
#  - Decrypt all files in ./EDF5_Encrypted -> ./EDF5_Decrypted (EDF5)
#  - Decrypt all files in ./EDF6_Encrypted -> ./EDF6_Decrypted (EDF6)
#  - Encode (re-encrypt + recompute checksum) all files in ./EDF6_Decrypted -> ./EDF6_Encrypted (EDF6 only, like original C++)
# Prints per-file diagnostic info similar to the C++ version.
# NOTE: Key/IV generation mimics the C++ logic exactly: using the raw filename (with its existing extension) then appending .sav / .stm.
beans = '''
@kittopiacreator I made a sub tool to force all the save files to be decrypted for  edf 5 and 6  as well DLC too, I will need help on finding for 4.1 save IV and keys, for the save files and I will be sleeping'''

import os
import sys
import hashlib
import zlib
# Determine script directory for relative save folders
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
from dataclasses import dataclass, asdict
from typing import List, Optional

SetCurrentGame = None  # Changed: decode all games so DLC MST files (EDF5) appear in log

# Added: mapping for game -> digit (now includes EDF4.1)
GAME_DIGIT_MAP = {
    'EDF6': '6',
    'EDF5': '5',
    'EDF4.1': '4',  # Assumed digit for EDF 4.1 (uses '4')
}

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("cryptography package required. Install via: pip install cryptography")
    sys.exit(1)

# ----------------- Data Classes -----------------
@dataclass
class FileReport:
    game: str               # EDF5 / EDF6
    operation: str          # decode / encode
    filename: str
    header_ok: Optional[bool] = None
    original_checksum: Optional[int] = None
    computed_checksum: Optional[int] = None
    status: str = "OK"
    error: Optional[str] = None
    checksum_algo: Optional[str] = None  # Added: which strategy matched
    alt_strategy: Optional[str] = None   # Which alternate key strategy succeeded
    bruteforce_algo: Optional[str] = None  # Added: brute-force discovered algorithm
    dlc: Optional[bool] = None             # Added: DLC heuristic flag

# ----------------- Core Helpers -----------------
POLY_CRC32C = 0x82F63B78

# Added MST debug helpers
_def_mst_debug = True

def _safe_ascii(b: bytes):
    return ''.join(chr(x) if 32 <= x < 127 else '.' for x in b)

def _print_mst_debug(fname: str, plain: bytes):
    if not _def_mst_debug:
        return
    size = len(plain)
    head = plain[:32]
    print(f"  MST debug: size={size} first32={head.hex()} ascii='{_safe_ascii(head)}'")
    if size > 64:
        nxt = plain[32:64]
        print(f"             next32={nxt.hex()} ascii='{_safe_ascii(nxt)}'")

def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ POLY_CRC32C
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF

def _crc32_ieee(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF

# Extra possible key suffixes for legacy versions (EDF4.1 unknown exact; we try several plausible strings)
LEGACY_SUFFIX_CANDIDATES = [
    b"Edf5.*_Steam_Ver",      # current assumption
    b"Edf4.*_Steam_Ver",      # alternate digit
    b"Edf4._Steam_Ver",       # missing asterisk variant
    b"EDF4.*_Steam_Ver",      # upper-case EDF
]

# Helper: find first offset whose inverted CRC32C matches stored
def find_checksum_match(data: bytes, stored: int, offsets=(0x0F,0x14,0x20)):
    for off in offsets:
        if len(data) > off:
            crc = crc32c(data[off:])
            inv = (~crc) & 0xFFFFFFFF
            if inv == stored:
                return off, inv
    return None, None

def generate_key_iv_variants(game: str, file_name: str):
    """Produce (tag,key,iv) tuples trying different digits / suffixes / name forms.
    Ensures no placeholder comments remain that break Python parsing."""
    digit_primary = GAME_DIGIT_MAP.get(game, '5')
    base, _ext = os.path.splitext(file_name)
    variants = []

    # Suffix selection
    if game == 'EDF4.1':
        suffixes = LEGACY_SUFFIX_CANDIDATES
    else:
        primary_suffix = f"Edf{digit_primary}.*_Steam_Ver".encode('ascii')
        suffixes = [primary_suffix]
        # Ensure EDF6 always also tries Edf5 suffix (legacy tools) but prioritizes its own
        if game == 'EDF6' and b"Edf5.*_Steam_Ver" not in suffixes:
            suffixes.append(b"Edf5.*_Steam_Ver")
        if game == 'EDF5' and b"Edf6.*_Steam_Ver" not in suffixes:
            suffixes.append(b"Edf6.*_Steam_Ver")

    # Name / prefix forms
    if game == 'EDF4.1':
        prefixes = [f"edf{digit_primary}", f"EDF{digit_primary}"]
        name_forms = [file_name, base, file_name.upper(), base.upper()]
    else:
        prefixes = [f"edf{digit_primary}"]
        name_forms = [file_name, base]

    def build(prefix: str, fname_for_hash: str, suffix: bytes):
        s1 = (prefix + fname_for_hash + ".sav").encode('utf-16le')
        s2 = (prefix + fname_for_hash + ".stm").encode('utf-16le')
        md5_1 = hashlib.md5(s1).digest()
        md5_2 = hashlib.md5(s2).digest()
        key = md5_1 + suffix
        if len(key) != 32:
            return None
        return key, md5_2

    # Primary digit / suffix variants
    for suffix in suffixes:
        for prefix in prefixes:
            for nf in name_forms:
                kv = build(prefix, nf, suffix)
                if kv:
                    tag = f"{prefix}_{nf}_{suffix.decode('latin1','ignore')}"
                    variants.append((tag, kv[0], kv[1]))

    # Cross-digit tries (exclude primary)
    for d in (d for d in ['4','5','6'] if d != digit_primary):
        cd_prefixes = [f"edf{d}"]
        if game == 'EDF4.1':
            cd_prefixes.append(f"EDF{d}")
        for suffix in suffixes:
            for prefix in cd_prefixes:
                for nf in name_forms:
                    kv = build(prefix, nf, suffix)
                    if kv:
                        tag = f"{prefix}_{nf}_{suffix.decode('latin1','ignore')}"
                        variants.append((tag, kv[0], kv[1]))

    # DLC heuristic ordering for EDF5 (prefer digit6)* and EDF6 (prefer its own digit first already)
    if game == 'EDF5' and file_name.upper().startswith('DEFP_DLC'):
        variants.sort(key=lambda v: (0 if '_Edf6.*_Steam_Ver' in v[0] else 1))
    if game == 'EDF6' and file_name.upper().startswith('DEFP_DLC'):
        variants.sort(key=lambda v: (0 if '_Edf6.*_Steam_Ver' in v[0] else 1))

    return variants

def aes_ctr(data: bytes, key: bytes, iv: bytes, encrypt: bool) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv), backend=default_backend())
    ctx = cipher.encryptor() if encrypt else cipher.decryptor()
    return ctx.update(data) + ctx.finalize()

# ----------------- Operations -----------------

CHECKSUM_OFFSET = 0x0C  # location where 4-byte inverted CRC32C is stored
CRC_REGION_OFFSET = 0x0F  # region over which CRC32C is computed (from this offset to end) per C++ example

def evaluate_checksum_strategies(game: str, data: bytes, stored: int):
    # Strategies: (name, region_start, algo, invert)
    strategies = []
    # Candidate region starts (observed 0x0F, 0x14)
    for start in (0x0F, 0x14):
        if len(data) <= start:
            continue
        payload = data[start:]
        # CRC32C
        c_crc32c = crc32c(payload)
        strategies.append((f"CRC32C@0x{start:X}", (~c_crc32c) & 0xFFFFFFFF, c_crc32c))
        strategies.append((f"CRC32C_noInvert@0x{start:X}", c_crc32c, c_crc32c))
        # Standard CRC32 (IEEE)
        c_crc32 = _crc32_ieee(payload)
        strategies.append((f"CRC32@0x{start:X}", (~c_crc32) & 0xFFFFFFFF, c_crc32))
        strategies.append((f"CRC32_noInvert@0x{start:X}", c_crc32, c_crc32))
    for name, candidate, raw in strategies:
        if candidate == stored:
            return name, candidate
    # Return best guess (first strategy) for reporting if none match
    if strategies:
        first_name, first_candidate, _ = strategies[0]
        return first_name + " (mismatch)", first_candidate
    return None, None

def brute_force_checksum(data: bytes, stored: int, min_start=0x0F, max_start=0x120):
    # Broaden search window (especially for EDF4.1) up to 0x120 or file length.
    for start in range(min_start, min(max_start, len(data)-4)):
        payload = data[start:]
        c1 = crc32c(payload)
        inv1 = (~c1) & 0xFFFFFFFF
        if inv1 == stored:
            return f"CRC32C@0x{start:X}", inv1
        if c1 == stored:
            return f"CRC32C_noInvert@0x{start:X}", c1
        c2 = _crc32_ieee(payload)
        inv2 = (~c2) & 0xFFFFFFFF
        if inv2 == stored:
            return f"CRC32@0x{start:X}", inv2
        if c2 == stored:
            return f"CRC32_noInvert@0x{start:X}", c2
    return None, None

def decode_directory(game: str, reports: List[FileReport]):
    enc_dir = os.path.join(SCRIPT_DIR, f"{game}_Encrypted")
    dec_dir = os.path.join(SCRIPT_DIR, f"{game}_Decrypted")
    if not os.path.isdir(enc_dir):
        print(f"{game}: Input directory not found: {enc_dir}")
        return
    if not os.path.isdir(dec_dir):
        print(f"{game}: Output directory missing: {dec_dir}")
        return
    print(f"{game} Save files: Input directory found. Decrypting all files.")

    # Collect files (now recursive so DLC MST in subfolders are included)
    file_entries = []
    for root, _dirs, files in os.walk(enc_dir):
        for fn in files:
            if fn.lower() == 'steam_autocloud.vdf':
                continue
            file_entries.append((root, fn))
    if not file_entries:
        print(f"  No files found under {enc_dir}")

    # Track presence of expected DLC MST names
    expected_dlc_mst = {"DEFP_DLC1.MST", "DEFP_DLC2.MST"}
    seen_dlc_mst = set()

    count = 0
    header_ok_count = 0
    checksum_bad = 0
    for root, fname in file_entries:
        full_path = os.path.join(root, fname)
        rel_display = os.path.relpath(full_path, enc_dir)
        report = FileReport(game=game, operation='decode', filename=rel_display)
        try:
            print(rel_display)
            with open(full_path, 'rb') as f:
                cipher_bytes = f.read()
            variants = generate_key_iv_variants(game, os.path.basename(fname))
            upper_name = fname.upper()
            if upper_name in expected_dlc_mst:
                seen_dlc_mst.add(upper_name)
            is_dlc = (game in ('EDF5','EDF6') and upper_name.startswith('DEFP_DLC'))
            if is_dlc and game == 'EDF5':
                print("  Detected DLC file (EDF5).")
            if is_dlc and game == 'EDF6':
                print("  Detected DLC file (EDF6).")
            is_mst = fname.lower().endswith('.mst')
            if is_mst and not is_dlc:
                print("  MST file")

            # Variant selection
            chosen_plain = None
            chosen_strategy = None
            matched_offset = None
            first_mdb_plain = None
            first_mdb_strategy = None
            candidate_offsets = (0x0F, 0x14, 0x20)
            for strat, key, iv in variants:
                try:
                    test_plain = aes_ctr(cipher_bytes, key, iv, encrypt=False)
                except Exception:
                    continue
                has_mdb = test_plain[:3] == b'MDB' or (b'MDB' in test_plain[:16])
                if has_mdb and first_mdb_plain is None:
                    first_mdb_plain = test_plain
                    first_mdb_strategy = strat
                if game == 'EDF6' and has_mdb and len(test_plain) > CHECKSUM_OFFSET + 4:
                    stored = int.from_bytes(test_plain[CHECKSUM_OFFSET:CHECKSUM_OFFSET+4], 'little')
                    for off in candidate_offsets:
                        if len(test_plain) > off:
                            crc_try = crc32c(test_plain[off:])
                            comp_try = (~crc_try) & 0xFFFFFFFF
                            if comp_try == stored:
                                chosen_plain = test_plain
                                chosen_strategy = strat
                                matched_offset = off
                                break
                    if chosen_plain is not None:
                        break
                if game != 'EDF6' and has_mdb:
                    chosen_plain = test_plain
                    chosen_strategy = strat
                    break
            if chosen_plain is None:
                if first_mdb_plain is not None:
                    chosen_plain = first_mdb_plain
                    chosen_strategy = first_mdb_strategy
                elif variants:
                    try:
                        strat0, key0, iv0 = variants[0]
                        chosen_plain = aes_ctr(cipher_bytes, key0, iv0, encrypt=False)
                        chosen_strategy = strat0
                    except Exception:
                        chosen_plain = b''
                        chosen_strategy = None

            plain = chosen_plain if chosen_plain is not None else b''
            report.dlc = is_dlc or None
            report.alt_strategy = chosen_strategy
            header_ok = (plain[:3] == b'MDB') or (b'MDB' in plain[:16])
            report.header_ok = header_ok
            if header_ok:
                if matched_offset is not None:
                    print(f"  MDB header found. (strategy={chosen_strategy}, checksum offset=0x{matched_offset:X})")
                else:
                    print(f"  MDB header found. (strategy={chosen_strategy})")
                header_ok_count += 1
            else:
                print(f"  Header mismatch (strategy={chosen_strategy})")
            if is_mst:
                _print_mst_debug(fname, plain)
            if len(plain) >= CRC_REGION_OFFSET:
                if len(plain) > CHECKSUM_OFFSET + 4:
                    orig = int.from_bytes(plain[CHECKSUM_OFFSET:CHECKSUM_OFFSET+4], 'little')
                    report.original_checksum = orig
                    if game == 'EDF6':
                        if matched_offset is not None:
                            crc_ok = crc32c(plain[matched_offset:])
                            report.computed_checksum = (~crc_ok) & 0xFFFFFFFF
                            report.checksum_algo = f"CRC32C@0x{matched_offset:X}"
                            print(f"  ORIGINAL: 0x{orig:08X}  (checksum OK via CRC32C@0x{matched_offset:X})")
                        else:
                            off, val = find_checksum_match(plain, orig, candidate_offsets)
                            if off is not None:
                                report.computed_checksum = val
                                report.checksum_algo = f"CRC32C@0x{off:X}"
                                print(f"  ORIGINAL: 0x{orig:08X}  (checksum OK via CRC32C@0x{off:X})")
                            else:
                                if len(plain) > CRC_REGION_OFFSET:
                                    crc_def = crc32c(plain[CRC_REGION_OFFSET:])
                                    report.computed_checksum = (~crc_def) & 0xFFFFFFFF
                                print(f"  ORIGINAL: 0x{orig:08X}  (checksum mismatch; tried 0x0F,0x14,0x20)")
                                report.status = "BAD_CHECKSUM"
                                checksum_bad += 1
                    else:
                        algo_name, candidate = evaluate_checksum_strategies(game, plain, orig)
                        if algo_name:
                            report.checksum_algo = algo_name
                        if candidate is not None and candidate == orig:
                            report.computed_checksum = candidate
                            print(f"  ORIGINAL: 0x{orig:08X}  (checksum OK via {algo_name})")
                        else:
                            if candidate is not None:
                                report.computed_checksum = candidate
                                print(f"  ORIGINAL: 0x{orig:08X}  (checksum mismatch, best guess {algo_name} -> 0x{candidate:08X})")
                            bf_name, bf_val = brute_force_checksum(plain, orig)
                            if bf_name and bf_val == orig:
                                report.bruteforce_algo = bf_name
                                report.checksum_algo = bf_name
                                report.computed_checksum = bf_val
                                report.status = "OK"
                                print(f"  BRUTE FORCE MATCH: {bf_name} (overrides mismatch)")
                            else:
                                if bf_name:
                                    report.bruteforce_algo = bf_name
                                    report.computed_checksum = bf_val
                                    print(f"  BRUTE FORCE candidate differs: {bf_name} -> 0x{bf_val:08X}")
                                report.status = "BAD_CHECKSUM"
                                checksum_bad += 1
                                if candidate is None and not bf_name:
                                    print("  Unable to evaluate checksum strategies (file too small or no match)")
                else:
                    print("  File too small for checksum field (skipped checksum validation).")
            else:
                print("  File too small to contain CRC region (skipped checksum validation).")
            out_path = os.path.join(dec_dir, rel_display)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, 'wb') as f:
                f.write(plain)
            count += 1
        except Exception as e:
            report.status = "ERROR"
            report.error = str(e)
            print(f"  Error: {e}")
        reports.append(report)
    # Report missing expected DLC MST if any
    if game in ('EDF5','EDF6'):
        missing = sorted(expected_dlc_mst - seen_dlc_mst)
        if missing:
            print(f"  Missing expected DLC MST files: {', '.join(missing)}")
    print(f"{game} Save files: Processed {count} files. MDB_OK={header_ok_count} CHECKSUM_BAD={checksum_bad}")

def encode_directory_edf6(reports: List[FileReport]):
    dec_dir = os.path.join(SCRIPT_DIR, "EDF6_Decrypted")
    enc_dir = os.path.join(SCRIPT_DIR, "EDF6_Encrypted")
    game = "EDF6"
    if not os.path.isdir(dec_dir):
        print(f"EDF6: Input directory not found: {dec_dir}")
        return
    if not os.path.isdir(enc_dir):
        print(f"EDF6: Output directory missing: {enc_dir}")
        return
    print("EDF 6 Save files: Input directory found. Decrypting all files.")  # Mirrors original wording

    count = 0
    for entry in os.scandir(dec_dir):
        if not entry.is_file():
            continue
        fname = entry.name
        report = FileReport(game=game, operation='encode', filename=fname)
        try:
            print(fname)
            # Use primary variant for encode (digit6_withExt for EDF6 is first in list)
            variants = generate_key_iv_variants(game, fname)
            if not variants:
                raise ValueError("No key variants produced")
            _, key, iv = variants[0]
            with open(entry.path, 'rb') as f:
                data = bytearray(f.read())
            if len(data) < CRC_REGION_OFFSET:
                raise ValueError("File too small for CRC region")
            if len(data) <= CHECKSUM_OFFSET + 4:
                raise ValueError("File too small for checksum field")
            orig = int.from_bytes(data[CHECKSUM_OFFSET:CHECKSUM_OFFSET+4], 'little')
            report.original_checksum = orig
            crc = crc32c(data[CRC_REGION_OFFSET:])
            computed = (~crc) & 0xFFFFFFFF
            chosen_start = CRC_REGION_OFFSET
            if fname.upper().startswith('DEFP_DLC'):
                off_match, val_match = find_checksum_match(data, orig, (0x0F,0x14,0x20))
                if off_match is not None:
                    chosen_start = off_match
                    computed = val_match
            else:
                off_match, val_match = find_checksum_match(data, orig, (0x0F,0x14,0x20))
                if off_match is not None:
                    chosen_start = off_match
                    computed = val_match
            report.computed_checksum = computed
            report.checksum_algo = f"CRC32C@0x{chosen_start:X}"
            if orig == computed:
                print(f"  Existing checksum OK (start=0x{chosen_start:X}): 0x{orig:08X}")
            else:
                print(f"  Replacing checksum 0x{orig:08X} -> 0x{computed:08X} (start=0x{chosen_start:X})")
            data[CHECKSUM_OFFSET:CHECKSUM_OFFSET+4] = computed.to_bytes(4, 'little')
            # Recompute with chosen start (already done); encrypt
            cipher_bytes = aes_ctr(bytes(data), key, iv, encrypt=True)
            if cipher_bytes[:3] == b'MDB':
                print("  (Encrypted output begins with 'MDB' bytes - unusual but noted)")
            out_path = os.path.join(enc_dir, fname)
            with open(out_path, 'wb') as f:
                f.write(cipher_bytes)
            count += 1
        except Exception as e:
            report.status = "ERROR"
            report.error = str(e)
            print(f"  Error: {e}")
        reports.append(report)
    print(f"EDF 6 Save files: Processed {count} files.")

# ----------------- CLI -----------------

def _resolve_single_game(val):
    if val is None:
        return None
    if val in (6, '6'):
        return 'EDF6'
    if val in (5, '5'):
        return 'EDF5'
    if val in (4, '4', 41, '41'):
        return 'EDF4.1'
    return None

def main():
    print("Operation mode: encode(e) or decode(d)")
    mode = input().strip().lower()
    print()
    reports: List[FileReport] = []

    if mode in ("e", "encode"):
        # Only EDF6 encode implemented in original C++.
        encode_directory_edf6(reports)
    elif mode in ("d", "decode"):
        single = _resolve_single_game(SetCurrentGame)
        if single:
            decode_directory(single, reports)
        else:
            for g in ["EDF6", "EDF5", "EDF4.1"]:
                decode_directory(g, reports)
    else:
        print("Invalid Operation")
        return

    # Summary block (machine-readable) to allow programmatic reading if needed.
    print("\n=== Summary (JSON-like) ===")
    for r in reports:
        # Simple key=value line (avoid importing json for strict minimalism)
        d = asdict(r)
        parts = [f"{k}={d[k]}" for k in d]
        print("{" + ", ".join(parts) + "}")

    if os.name == 'nt':
        os.system('pause')

if __name__ == '__main__':
    main()
