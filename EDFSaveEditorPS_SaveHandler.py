"""PS4/PS5 savedata CONTAINER layer: reads/patches param.sfo's ACCOUNT_ID field to a generic placeholder (Apollo Save Tool-style resigning) so a shared save doesn't leak the original account, and assembles a shareable package from the game's already-encrypted save bytes plus a real keystone/param.sfo (not fabricated here). Separate from EDFSaveEditorSave_Handler.py's game-internal file format."""

import os
import shutil
import struct

# --- param.sfo binary format (source: apollo-ps4's sfo.c/sfo.h, see module docstring) -------
SFO_MAGIC = 0x46535000
SFO_VERSION = 0x0101
SFO_ACCOUNT_ID_SIZE = 8   # bytes - ACCOUNT_ID param's value length (u64, little-endian)
SFO_PSID_SIZE = 16
SFO_DIRECTORY_SIZE = 32

# Generic/placeholder Account-ID used by the PS4 homebrew community for save sharing without exposing a real account. This is what resign_param_sfo() defaults to.
GENERIC_ACCOUNT_ID = 0x0000000000000000

_HEADER_FMT = '<5I'          # magic, version, key_table_offset, data_table_offset, num_entries
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)               # 20 bytes
_INDEX_FMT = '<HHIII'        # key_offset(u16), param_format(u16), param_length, param_max_length, data_offset
_INDEX_SIZE = struct.calcsize(_INDEX_FMT)                 # 16 bytes


def _align(n, a=8):
    return (n + a - 1) // a * a


def sfo_read(path):
    """Parse a param.sfo file into a list of param dicts (order preserved, matters for sfo_write to reproduce a byte-stable file), each {'key', 'format', 'length', 'max_length', 'value'}."""
    with open(path, 'rb') as f:
        data = f.read()

    if len(data) < _HEADER_SIZE:
        raise ValueError(f"{path}: too small to be a param.sfo ({len(data)} bytes)")

    magic, version, key_table_off, data_table_off, num_entries = struct.unpack_from(_HEADER_FMT, data, 0)
    if magic != SFO_MAGIC:
        raise ValueError(f"{path}: bad SFO magic 0x{magic:08X} (expected 0x{SFO_MAGIC:08X})")

    params = []
    for i in range(num_entries):
        idx_off = _HEADER_SIZE + i * _INDEX_SIZE
        key_offset, param_format, param_length, param_max_length, data_offset = struct.unpack_from(_INDEX_FMT, data, idx_off)

        key_start = key_table_off + key_offset
        key_end = data.index(b'\x00', key_start)
        key = data[key_start:key_end].decode('utf-8', errors='replace')

        val_start = data_table_off + data_offset
        value = bytes(data[val_start:val_start + param_max_length])

        params.append({
            'key': key,
            'format': param_format,
            'length': param_length,
            'max_length': param_max_length,
            'value': value,
        })

    return params


def sfo_write(path, params):
    """Rebuild a param.sfo file from a params list (same shape sfo_read returns) and write it to `path`, including the key-table padding that keeps the final file size 8-byte aligned."""
    num_params = len(params)
    key_table_size = sum(len(p['key']) + 1 for p in params)
    data_table_size = sum(len(p['value']) for p in params)

    sfo_size = _HEADER_SIZE + num_params * _INDEX_SIZE + key_table_size + data_table_size
    padded_size = _align(sfo_size, 8)
    key_table_size += padded_size - sfo_size   # extra padding folded into the key table, like the C code
    sfo_size = padded_size

    buf = bytearray(sfo_size)   # zero-filled, like the C code's malloc+memset(0)

    key_table_off = _HEADER_SIZE + num_params * _INDEX_SIZE
    data_table_off = key_table_off + key_table_size
    struct.pack_into(_HEADER_FMT, buf, 0, SFO_MAGIC, SFO_VERSION, key_table_off, data_table_off, num_params)

    key_offset = 0
    data_offset = 0
    for i, p in enumerate(params):
        idx_off = _HEADER_SIZE + i * _INDEX_SIZE
        struct.pack_into(_INDEX_FMT, buf, idx_off, key_offset, p['format'], p['length'], p['max_length'], data_offset)
        key_offset += len(p['key']) + 1
        data_offset += len(p['value'])

    key_offset = 0
    data_offset = 0
    for p in params:
        key_bytes = p['key'].encode('utf-8') + b'\x00'
        buf[key_table_off + key_offset: key_table_off + key_offset + len(key_bytes)] = key_bytes
        buf[data_table_off + data_offset: data_table_off + data_offset + len(p['value'])] = p['value']
        key_offset += len(key_bytes)
        data_offset += len(p['value'])

    with open(path, 'wb') as f:
        f.write(buf)


def get_param(params, key):
    """First param dict matching `key`, or None."""
    for p in params:
        if p['key'] == key:
            return p
    return None


def get_account_id(params):
    """Current ACCOUNT_ID as a 16-hex-char string, or None if the param isn't present / isn't the expected 8-byte size."""
    p = get_param(params, 'ACCOUNT_ID')
    if p is None or len(p['value']) != SFO_ACCOUNT_ID_SIZE:
        return None
    return p['value'][::-1].hex()   # value is little-endian u64 bytes; hex display is big-endian-looking, matches the wiki's example format


def set_account_id(params, account_id):
    """Patch ACCOUNT_ID in place (modifies `params`). `account_id` may be an int or a 16-hex-char string. Raises if ACCOUNT_ID isn't present or isn't 8 bytes."""
    if isinstance(account_id, str):
        account_id = int(account_id.replace('0x', '').replace(' ', ''), 16)
    p = get_param(params, 'ACCOUNT_ID')
    if p is None:
        raise ValueError("param.sfo has no ACCOUNT_ID field - not a real savedata param.sfo?")
    if len(p['value']) != SFO_ACCOUNT_ID_SIZE:
        raise ValueError(f"ACCOUNT_ID field is {len(p['value'])} bytes, expected {SFO_ACCOUNT_ID_SIZE}")
    p['value'] = struct.pack('<Q', account_id & 0xFFFFFFFFFFFFFFFF)


def resign_param_sfo(path, account_id=GENERIC_ACCOUNT_ID, out_path=None):
    """Read `path`, patch ACCOUNT_ID to `account_id` (default: the generic all-zero placeholder
    used for save-sharing without exposing a real account), write to `out_path` (default:
    overwrite `path` in place). Returns the (old_account_id, new_account_id) hex strings."""
    params = sfo_read(path)
    old_id = get_account_id(params)
    set_account_id(params, account_id)
    sfo_write(out_path or path, params)
    return old_id, get_account_id(params)


# --- Sample discovery: gating helper letting the GUI know whether a real EDF4.1 PS4 sample (keystone + param.sfo) has actually shown up yet, rather than guessing or fabricating one. ---
# Default samples root, populated by DUMP/Waiter_PS.bat (one timestamped subfolder per contributor's sample) - not auto-created by Waiter.bat, which only pulls the PC save folder.
PS_SAMPLES_DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'DUMP', 'ps_samples')


def find_ps_samples(samples_root=None):
    """Scan `samples_root` (default PS_SAMPLES_DEFAULT_ROOT) for subfolders that look like a real PS4 savedata export (sce_sys/keystone + sce_sys/param.sfo alongside the save files), the layout DUMP/Waiter_PS.bat produces. Returns a list of {'save_files_dir', 'keystone_path', 'param_sfo_path', 'label'} dicts, newest first; empty if none exist yet."""
    root = samples_root or PS_SAMPLES_DEFAULT_ROOT
    found = []
    if not os.path.isdir(root):
        return found

    for name in sorted(os.listdir(root), reverse=True):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        keystone = os.path.join(folder, 'sce_sys', 'keystone')
        param_sfo = os.path.join(folder, 'sce_sys', 'param.sfo')
        if os.path.isfile(keystone) and os.path.isfile(param_sfo):
            found.append({
                'save_files_dir': folder,
                'keystone_path': keystone,
                'param_sfo_path': param_sfo,
                'label': name,
            })

    return found


def describe_sfo(path):
    """Human-readable dump of every param in a param.sfo - key, format, length, and a best-effort decoded value. Useful for a quick `python EDFSaveEditorPS_SaveHandler.py inspect ...` look."""
    params = sfo_read(path)
    lines = []
    for p in params:
        val = p['value']
        fmt = p['format']
        if fmt in (0x0004, 0x0204):   # UTF-8 string (0x0204 = not null-terminated variant)
            decoded = val.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
        elif fmt == 0x0404 and len(val) == 4:
            decoded = str(struct.unpack('<I', val)[0])
        elif len(val) == 8:
            decoded = f"0x{struct.unpack('<Q', val)[0]:016X}"
        else:
            decoded = val.hex()
        lines.append(f"  {p['key']:<24} fmt=0x{fmt:04X} len={p['length']:<4} max={p['max_length']:<4} value={decoded}")
    return '\n'.join(lines)


# --- Sharing package assembly: builds the standard PS4/PS5 savedata folder layout (<save folder>/<game files> + <save folder>/sce_sys/{param.sfo, keystone, ...}) from files this project already has plus a real keystone/param.sfo. ---
def assemble_share_package(save_files_dir, keystone_path, param_sfo_path, out_dir,
                            account_id=GENERIC_ACCOUNT_ID, extra_sce_sys_files=None):
    """Build a ready-to-share PS4 savedata folder at `out_dir`: the save files copied as-is, sce_sys/keystone copied byte-for-byte (never patched), sce_sys/param.sfo copied with ACCOUNT_ID resigned to `account_id`, plus any extra_sce_sys_files. Returns the old/new ACCOUNT_ID hex strings. Raises FileNotFoundError if any input path doesn't exist - never invents placeholder data."""
    if not os.path.isdir(save_files_dir):
        raise FileNotFoundError(f"save_files_dir not found: {save_files_dir}")
    if not os.path.isfile(keystone_path):
        raise FileNotFoundError(f"keystone not found: {keystone_path}")
    if not os.path.isfile(param_sfo_path):
        raise FileNotFoundError(f"param.sfo not found: {param_sfo_path}")

    os.makedirs(out_dir, exist_ok=True)
    sce_sys_dir = os.path.join(out_dir, 'sce_sys')
    os.makedirs(sce_sys_dir, exist_ok=True)

    for name in os.listdir(save_files_dir):
        src = os.path.join(save_files_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(out_dir, name))

    shutil.copy2(keystone_path, os.path.join(sce_sys_dir, 'keystone'))

    out_sfo_path = os.path.join(sce_sys_dir, 'param.sfo')
    shutil.copy2(param_sfo_path, out_sfo_path)
    old_id, new_id = resign_param_sfo(out_sfo_path, account_id=account_id)

    for extra in (extra_sce_sys_files or []):
        if os.path.isfile(extra):
            shutil.copy2(extra, os.path.join(sce_sys_dir, os.path.basename(extra)))

    return old_id, new_id


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage:")
        print("  python EDFSaveEditorPS_SaveHandler.py inspect <param.sfo>")
        print("  python EDFSaveEditorPS_SaveHandler.py resign <param.sfo> [new_account_id_hex]")
        sys.exit(1)

    cmd, sfo_path = sys.argv[1], sys.argv[2]

    if cmd == 'inspect':
        print(f"{sfo_path}:")
        print(describe_sfo(sfo_path))
    elif cmd == 'resign':
        new_id = sys.argv[3] if len(sys.argv) > 3 else GENERIC_ACCOUNT_ID
        old, new = resign_param_sfo(sfo_path, account_id=new_id)
        print(f"ACCOUNT_ID: {old} -> {new}")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
