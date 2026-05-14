"""Channel IDs and frame beats for AFK handler tests."""

from dataclasses import dataclass
from enum import IntEnum


class ChannelId(IntEnum):
    HEARTBEAT = 1
    ADMIN = 2
    PROGRAM_ACTIONS = 3
    TRIGGER = 4



@dataclass
class Beat:
    data: int
    sop: bool
    eop: bool


def make_channel_beats(message: bytes, width: int) -> list[Beat]:
    wire = message + b"\xa5" * (-len(message) % width)
    chunks = [wire[i:i + width] for i in range(0, len(wire), width)]
    return [Beat(int.from_bytes(chunk, "big"), i == 0, i == len(chunks) - 1)
            for i, chunk in enumerate(chunks)]
