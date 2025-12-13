# EDFSaveEditorSave_Handler.py
import os
import struct
import hashlib
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

def load_save(file_path: str) -> bytes:
    with open(file_path, 'rb') as f:
        ciphertext = f.read()
    key, iv = generate_key_iv(file_path)
    data = aes_ctr_decrypt(ciphertext, key, iv)
    if data[:4] != b'MDB0':
        raise ValueError("Invalid header after decryption")
    return data

def save_save(file_path: str, data: bytearray):
    crc = crc32c(data[0x14:])
    checksum = ~crc & 0xFFFFFFFF
    struct.pack_into("<I", data, 0x0C, checksum)
    key, iv = generate_key_iv(file_path)
    ciphertext = aes_ctr_encrypt(bytes(data), key, iv)
    with open(file_path, 'wb') as f:
        f.write(ciphertext)

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