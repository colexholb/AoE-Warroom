"""Minimal reader for the lobby info in an AoE2:DE .aoe2record header.

The full `mgz` parser breaks on every game patch that shifts the header layout,
so this reader only targets the few fields we need, which have been stable for years.

Start of the decompressed header:

    "VER 9.4\\0" | f32 | u32 | build u32 | start_timestamp u32 | 12 bytes
    | dlc_count u32 | dlc_ids u32[count] | u32 | map_dimension u32 | map_id u32 | u32 | u32
    | victory u32 | resources u32 | starting_age u32 | ending_age u32

Player blocks, a little further in:

    dlc_id u32 | color_id i32 | 1 byte | 1 byte | team u8 | game data crc (8 bytes) | 1 byte
    | civ_id u32 | civ_pool_count u32 | civ_pool u32[count]
    | de_string | 1 byte | ai_name de_string | censored_name de_string | name de_string
    | type u32 | profile_id u32 | 4 bytes | number i32

A de_string is b"\\x60\\x0a" + u16 length + utf-8 bytes. Rather than walk the whole
header (and break on the next patch), we scan for byte offsets where a player block
with that shape validates.
"""

from __future__ import annotations

import json
import struct
import zlib
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

DE_STRING_MARKER = b"\x60\x0a"
# The player blocks sit within the first couple of KB of the decompressed header.
SCAN_BYTES = 8 * 1024
HUMAN_TYPE = 2
NO_TEAM = 1  # team byte 1 is the "-" option in the lobby; 2..5 are teams 1..4
DARK_AGE_START = 2  # starting_age value for a normal Dark Age start (same code as the API)
# aoe2companion slugs that don't follow lowercase-name-without-spaces.
SLUG_OVERRIDES = {"Maya": "mayans"}


@dataclass
class HeaderPlayer:
    number: int  # player number as shown in game (1-8)
    name: str
    profile_id: int | None
    color_id: int  # 0 blue, 1 red, 2 green, 3 yellow, 4 cyan, 5 purple, 6 grey, 7 orange
    team: int | None  # None when the player is not on a team
    civ_id: int
    civ: str
    civ_slug: str
    is_ai: bool


@dataclass
class RecordInfo:
    path: str
    started: datetime | None
    map_id: int | None
    map_name: str | None
    starting_age: int | None = None
    players: list[HeaderPlayer] = field(default_factory=list)

    @property
    def standard_start(self) -> bool:
        """Dark Age start, so openings mean something (not Empire Wars / Death Match)."""
        return self.starting_age == DARK_AGE_START

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started"] = self.started.isoformat() if self.started else None
        return d


@lru_cache(maxsize=1)
def _dataset() -> dict:
    import aocref

    path = Path(aocref.__file__).parent / "data" / "datasets" / "100.json"
    return json.loads(path.read_text(encoding="utf-8"))


def civ_name(civ_id: int) -> str:
    civ = _dataset()["civilizations"].get(str(civ_id))
    return civ["name"] if civ else f"Civ #{civ_id}"


def civ_slug(name: str) -> str:
    return SLUG_OVERRIDES.get(name, name.lower().replace(" ", ""))


def object_name(object_id: int) -> str | None:
    return _dataset()["objects"].get(str(object_id))


def map_name(map_id: int) -> str | None:
    return _dataset()["maps"].get(str(map_id))


def read_header(path: str | Path) -> bytes:
    """Return the start of the decompressed header of a recording."""
    with open(path, "rb") as f:
        # Only the first chunk of the compressed stream is needed for SCAN_BYTES of output.
        return decompress_header(f.read(512 * 1024))


def decompress_header(raw: bytes) -> bytes:
    if len(raw) < 8:
        raise ValueError("file too short to contain a header")
    header_len = struct.unpack_from("<I", raw, 0)[0]
    compressed = raw[8:min(header_len, len(raw))]
    return zlib.decompressobj(-15).decompress(compressed, SCAN_BYTES)


def _de_string(buf: bytes, off: int) -> tuple[str, int] | None:
    if buf[off:off + 2] != DE_STRING_MARKER or off + 4 > len(buf):
        return None
    (length,) = struct.unpack_from("<H", buf, off + 2)
    end = off + 4 + length
    if length > 256 or end > len(buf):
        return None
    try:
        return buf[off + 4:end].decode("utf-8"), end
    except UnicodeDecodeError:
        return None


def _try_block(buf: bytes, off: int) -> HeaderPlayer | None:
    try:
        dlc_id, color_id = struct.unpack_from("<Ii", buf, off)
        team = buf[off + 10]
        civ_id, pool_count = struct.unpack_from("<II", buf, off + 20)
    except (struct.error, IndexError):
        return None
    if dlc_id > 10_000 or not -1 <= color_id <= 15 or team > 8 or civ_id > 500 or pool_count > 100:
        return None
    pos = off + 28 + 4 * pool_count
    strings = []
    for i in range(4):
        parsed = _de_string(buf, pos)
        if parsed is None:
            return None
        value, pos = parsed
        strings.append(value)
        if i == 0:
            pos += 1  # unknown byte after the first string
    _, ai_name, _censored, name = strings
    try:
        ptype, profile_id, number = struct.unpack_from("<II4xi", buf, pos)
    except struct.error:
        return None
    if ptype > 10 or not -1 <= number <= 8:
        return None
    if not name and not ai_name:
        return None  # empty slot
    is_ai = ptype != HUMAN_TYPE or profile_id in (0, 0xFFFFFFFF)
    civ = civ_name(civ_id)
    return HeaderPlayer(
        number=number,
        name=name or ai_name,
        profile_id=None if is_ai else profile_id,
        color_id=color_id,
        team=None if team <= NO_TEAM else team - 1,
        civ_id=civ_id,
        civ=civ,
        civ_slug=civ_slug(civ),
        is_ai=is_ai,
    )


def _parse_players(buf: bytes) -> list[HeaderPlayer]:
    # Byte soup occasionally validates as a block a few bytes before a real one, so
    # collect every candidate and keep the ones sharing the game data CRC (bytes 11-15
    # of a block), which is identical for every real player in a match.
    candidates: list[tuple[bytes, HeaderPlayer]] = []
    for off in range(len(buf) - 40):
        player = _try_block(buf, off)
        if player is not None:
            candidates.append((buf[off + 11:off + 15], player))
    if not candidates:
        return []
    crc = Counter(c for c, _ in candidates).most_common(1)[0][0]
    by_number: dict[int, HeaderPlayer] = {}
    for c, player in candidates:
        if c == crc:
            by_number.setdefault(player.number, player)
    return sorted(by_number.values(), key=lambda p: p.number)


def _parse_settings(buf: bytes) -> tuple[datetime | None, int | None, int | None]:
    try:
        (timestamp,) = struct.unpack_from("<I", buf, 20)
        (dlc_count,) = struct.unpack_from("<I", buf, 36)
        if dlc_count > 200:
            return None, None, None
        settings = struct.unpack_from("<9I", buf, 40 + 4 * dlc_count)
    except struct.error:
        return None, None, None
    map_id, starting_age = settings[2], settings[7]
    started = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp > 1_500_000_000 else None
    return started, map_id, starting_age


def parse_players(path: str | Path) -> list[HeaderPlayer]:
    return _parse_players(read_header(path))


def parse_record(path: str | Path) -> RecordInfo:
    return _record_from_header(read_header(path), str(path))


def parse_record_bytes(raw: bytes, path: str = "") -> RecordInfo:
    return _record_from_header(decompress_header(raw), path)


def _record_from_header(buf: bytes, path: str) -> RecordInfo:
    started, map_id, starting_age = _parse_settings(buf)
    return RecordInfo(
        path=path,
        started=started,
        map_id=map_id,
        map_name=map_name(map_id) if map_id is not None else None,
        starting_age=starting_age,
        players=_parse_players(buf),
    )


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        info = parse_record(arg)
        print(Path(arg).name, info.started, info.map_name)
        for p in info.players:
            print("  ", p)
