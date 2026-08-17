# EDFSaveEditorSave_Handler.py
import os
import struct
import hashlib
import zlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

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

def generate_key_iv(filename: str) -> tuple[bytes, bytes]:
    base_name = os.path.basename(filename).rsplit('.sav', 1)[0]
    if base_name.endswith('.DAT'):
        base_name = 'GAMESTATE'  # Use same key for all DAT files as GST
    str1 = f"edf6{base_name}.sav"
    str2 = f"edf6{base_name}.stm"
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

# --- EDF 4.1 ----------------------------------------------------------------
# 4.1 uses the same MDB0 container and AES-CTR, but the key schedule is not the
# edf<N><filename>.sav scheme of 5/6, so the variant search above can never find
# it. Two differences:
#
#   * the filename is not part of the derivation at all, so every file in a
#     SAVE_DATA folder (MAIN.GST, *.MST, *.CFG, TROPHY.DAT) shares one keystream
#   * the game measures the seed string in characters but copies it as bytes, so
#     only the first len(s) bytes of the UTF-16 buffer are hashed, and the digest
#     is then hashed a second time
#
#       key = MD5(MD5(utf16le("edf4.1_save")[:11]))   -> AES-128
#       iv  = MD5(MD5(utf16le("edf4.1")[:6]))
#
# The checksum is a plain CRC-32 (zlib polynomial) over the body from 0x18 to
# the end of the file, stored at 0x0C. Verified against every file of a real
# save: MAIN.GST, DEFP_M00/M01.MST, MP01/MP02_M00.MST, COMMON.CFG, TROPHY.DAT,
# SYSTEM.CFG and SYSTEMWIN32.CFG.

def _edf41_seed(text: str) -> bytes:
    truncated = text.encode("utf-16le")[:len(text)]
    return hashlib.md5(hashlib.md5(truncated).digest()).digest()

EDF41_KEY = _edf41_seed("edf4.1_save")
EDF41_IV = _edf41_seed("edf4.1")

def generate_key_iv_41(filename: str = "") -> tuple[bytes, bytes]:
    return EDF41_KEY, EDF41_IV

def _checksum_41(data: bytes) -> int:
    return zlib.crc32(bytes(data[0x18:])) & 0xFFFFFFFF

def _checksum_6(data: bytes) -> int:
    return ~crc32c(bytes(data[0x14:])) & 0xFFFFFFFF

# name, key/iv factory, checksum function. 4.1 is tried first because both its
# header and its checksum can be verified, so a false positive is not possible.
PROFILES = (
    ("edf4.1", generate_key_iv_41, _checksum_41),
    ("edf6", generate_key_iv, _checksum_6),
)

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

def detect_profile(file_path: str):
    """Return (profile_name, plaintext) for a save file, or (None, None).

    A profile is accepted when the decrypted header is MDB0. When the stored
    checksum also matches, the match is exact and the search stops immediately.
    """
    with open(file_path, 'rb') as f:
        ciphertext = f.read()
    fallback = (None, None)
    for name, keyiv, checksum in PROFILES:
        key, iv = keyiv(file_path)
        try:
            plain = aes_ctr_decrypt(ciphertext, key, iv)
        except Exception:
            continue
        if plain[:4] != b'MDB0':
            continue
        stored = struct.unpack_from("<I", plain, 0x0C)[0]
        if checksum(plain) == stored:
            return name, plain
        if fallback[0] is None:
            fallback = (name, plain)
    return fallback

def load_save(file_path: str) -> bytes:
    name, data = detect_profile(file_path)
    if name is None:
        raise ValueError("Invalid header after decryption")
    return data

def save_save(file_path: str, data: bytearray, profile: str = None):
    if profile is None:
        # keep the format the file already had; new files default to edf6
        profile = "edf6"
        if os.path.exists(file_path):
            detected, _ = detect_profile(file_path)
            if detected is not None:
                profile = detected
    for name, keyiv, checksum in PROFILES:
        if name != profile:
            continue
        struct.pack_into("<I", data, 0x0C, checksum(data))
        key, iv = keyiv(file_path)
        with open(file_path, 'wb') as f:
            f.write(aes_ctr_encrypt(bytes(data), key, iv))
        return
    raise ValueError(f"Unknown save profile: {profile}")

_DEF_MST_HEADER_HINTS = [b'MDB', b'MST', b'EFDP']

def decrypt_mst(file_path: str) -> tuple[bytes, str]:
    # 4.1 keys the MST exactly like every other file, so try that first
    name, plain = detect_profile(file_path)
    if name == "edf4.1":
        return plain, name
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

# EDF 4.1 keeps its files under their real names instead of the .sav wrapper
# EDF 6 uses, so a plain SAVE_DATA folder contains these extensions.
_PLAIN_EXTS = ('.gst', '.cfg', '.dat')

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
        elif lower.endswith(_PLAIN_EXTS):
            try:
                name, data = detect_profile(file_path)
                if name is None:
                    raise ValueError("Invalid header after decryption")
                output_path = os.path.join(decrypted_dir, filename)
                with open(output_path, 'wb') as f:
                    f.write(data)
                print(f"Decrypted {filename} (key={name})")
            except Exception as e:
                print(f"Error decrypting {filename}: {e}")

def encrypt_directory(decrypted_dir: str, encrypted_dir: str):
    if not os.path.exists(decrypted_dir):
        raise ValueError(f"Decrypted directory not found: {decrypted_dir}")
    os.makedirs(encrypted_dir, exist_ok=True)
    for filename in os.listdir(decrypted_dir):
        file_path = os.path.join(decrypted_dir, filename)
        if not os.path.isfile(file_path):
            continue
        lower = filename.lower()
        if lower.endswith('.mst') or lower.endswith(_PLAIN_EXTS):
            # 4.1 files keep their own name and are re-encrypted in place
            try:
                with open(file_path, 'rb') as f:
                    data = bytearray(f.read())
                if data[:4] != b'MDB0':
                    continue
                output_path = os.path.join(encrypted_dir, filename)
                save_save(output_path, data, profile="edf4.1")
                print(f"Encrypted {filename}")
            except Exception as e:
                print(f"Error encrypting {filename}: {e}")
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
