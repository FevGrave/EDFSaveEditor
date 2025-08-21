import argparse
import os
import sys
import zlib
from typing import Literal

# Total size = last offset 0x16D0 + size 0x08 = 0x16D8 (5848 bytes)
MST_TOTAL_SIZE = 0x16D8

DLC_VARIANTS = {
    "base": 0x9CC9,   # M00
    "dlc1": 0x7DFB,   # DLC1
    "dlc2": 0x2BF4,   # DLC2
}

def build_default_mst(
    lobby_name: str = "EDF Room",
    open_message: str = "",
    password: str = "",
    mission_current: int = 0,
    difficulty_current: int = 0,
    access_mode_a: int = 0,  # (0=Everyone,1=Friends/Invite,2=Password,3=RoomNameOnly) – per observed notes
    access_mode_b: int = 0,
    variant: Literal["base","dlc1","dlc2"] = "base",
) -> bytes:
    buf = bytearray(MST_TOTAL_SIZE)

    def write(offset: int, data: bytes):
        end = offset + len(data)
        buf[offset:end] = data

    def write_u32(offset: int, val: int):
        write(offset, val.to_bytes(4, "little", signed=False))

    def write_i32(offset: int, val: int):
        write(offset, val.to_bytes(4, "little", signed=True))

    def write_u16(offset: int, val: int):
        write(offset, val.to_bytes(2, "little", signed=False))

    def write_str_utf16le(offset: int, size: int, text: str):
        enc = text[: (size // 2)].encode("utf-16le")
        write(offset, enc.ljust(size, b"\x00"))

    def write_str_utf8(offset: int, size: int, text: str):
        enc = text[: size].encode("utf-8")
        write(offset, enc.ljust(size, b"\x00"))

    # Header
    write(0x00, b"MDB0")
    write_u32(0x04, 3)  # version guess
    # 0x08 unknown left 0
    # 0x0C CRC32 placeholder (fill later)
    # 0x10 spacer null
    write_u32(0x14, mission_current)
    write_u32(0x18, difficulty_current)

    # Mission Save Tables (4 * 0x200) – all zero (locked)
    # Offsets: 0x1C, 0x21C, 0x41C, 0x61C

    # Spacer 0x81C (0x200) already zero
    # Default Mission tables 0xA1C size 0x800 (leave zero)
    # Spacer 0x121C size 0x200 zero

    # Lobby Name (UTF-16LE, 0x28 bytes => 20 chars)
    write_str_utf16le(0x141C, 0x28, lobby_name)
    # Open Message (UTF-16LE, 0x30 bytes => 24 chars)
    write_str_utf16le(0x1446, 0x30, open_message)

    # Select Set Phrase categories/content (guessed zeros)
    # 0x1478 .. 0x1484 all zero

    # Defaults
    write_i32(0x1488, 1)
    write_i32(0x148C, 1)
    # 0x1490 unknown left zero
    write_i32(0x1494, 3)  # "Default 3?"
    write_i32(0x1498, access_mode_a)

    # Password (UTF-8, 0x8 bytes, spec says max 10 chars but field given 0x8)
    write_str_utf8(0x149C, 0x8, password)

    # 0x14A4 unknown
    write_i32(0x14A8, access_mode_b)
    write_i32(0x14AC, 2)  # "Default 2?"

    # Tail flags
    write_u32(0x16C8, 0x00000101)  # Sometimes 0x01 or 0x0101; writing combined
    write_u16(0x16CC, 0x0101)
    write_u16(0x16CE, DLC_VARIANTS[variant])

    # Compute CRC32 (commonly over entire file with CRC field zeroed)
    # Zero already at 0x0C..0x0F; compute over whole buffer
    crc = zlib.crc32(buf) & 0xFFFFFFFF
    write_u32(0x0C, crc)

    return bytes(buf)

def main():
    parser = argparse.ArgumentParser(description="Generate a default MST file if empty or missing.")
    parser.add_argument("path", help="Path to MST file")
    parser.add_argument("--variant", choices=["base","dlc1","dlc2"], default="base")
    parser.add_argument("--lobby", default="EDF Room")
    parser.add_argument("--message", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--mission", type=int, default=0)
    parser.add_argument("--difficulty", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true", help="Force overwrite even if file has data")
    args = parser.parse_args()

    target = args.path
    exists = os.path.isfile(target)
    size = os.path.getsize(target) if exists else 0

    if exists and size > 0 and not args.overwrite:
        print(f"File '{target}' already has data ({size} bytes). Use --overwrite to replace.")
        return

    data = build_default_mst(
        lobby_name=args.lobby,
        open_message=args.message,
        password=args.password,
        mission_current=args.mission,
        difficulty_current=args.difficulty,
        variant=args.variant,
    )

    with open(target, "wb") as f:
        f.write(data)

    print(f"Wrote MST file: {target} ({len(data)} bytes)")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)