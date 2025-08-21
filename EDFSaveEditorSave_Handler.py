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

def generate_key_iv(filename: str) -> tuple[bytes, bytes]:
    base_name = os.path.basename(filename).rsplit('.sav', 1)[0]  # Strip .sav if present
    str1 = f"edf6{base_name}.sav"
    str2 = f"edf6{base_name}.stm"
    str1_bytes = str1.encode('utf-16le')
    str2_bytes = str2.encode('utf-16le')
    digest1 = hashlib.md5(str1_bytes).digest()
    key = digest1 + b"Edf5.*_Steam_Ver"
    iv = hashlib.md5(str2_bytes).digest()
    return key, iv

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
    # Optional: Verify header
    if data[:4] != b'MDB0':
        raise ValueError("Invalid header after decryption")
    return data

def save_save(file_path: str, data: bytearray):
    # Update checksum
    crc = crc32c(data[0x14:])
    checksum = ~crc & 0xFFFFFFFF
    struct.pack_into("<I", data, 0x0C, checksum)
    # Encrypt
    key, iv = generate_key_iv(file_path)
    ciphertext = aes_ctr_encrypt(bytes(data), key, iv)
    with open(file_path, 'wb') as f:
        f.write(ciphertext)

def decrypt_directory(encrypted_dir: str, decrypted_dir: str):
    if not os.path.exists(encrypted_dir):
        raise ValueError(f"Encrypted directory not found: {encrypted_dir}")
    os.makedirs(decrypted_dir, exist_ok=True)
    for filename in os.listdir(encrypted_dir):
        if not filename.endswith('.sav'):
            continue  # Skip non-.sav files; adjust if needed to copy others
        file_path = os.path.join(encrypted_dir, filename)
        try:
            data = load_save(file_path)
            output_filename = filename[:-4]  # Remove .sav
            output_path = os.path.join(decrypted_dir, output_filename)
            with open(output_path, 'wb') as f:
                f.write(data)
            print(f"Decrypted {filename} to {output_filename}")
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
        try:
            with open(file_path, 'rb') as f:
                data = bytearray(f.read())
            output_filename = f"{filename}.sav"
            output_path = os.path.join(encrypted_dir, output_filename)
            save_save(output_path, data)
            print(f"Encrypted {filename} to {output_filename}")
        except Exception as e:
            print(f"Error encrypting {filename}: {e}")