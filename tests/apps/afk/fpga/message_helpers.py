"""AFK little-endian wire messages and internal entry builders."""

from dataclasses import dataclass
import struct


HEADER_BYTES = 12
MAX_REACTION_PAYLOAD_SIZE = 237
MAX_REACTION_MESSAGE_SIZE = 255
REACTION_HEADER_BYTES = 18
MAX_CONDITION_MSG_SIZE = 32


def make_message_header(seq: int, ack_seq: int, msg_type: int, body_size: int = 0) -> bytes:
    return struct.pack("<HIIH", HEADER_BYTES + body_size, seq, ack_seq, msg_type)


def make_test_request(seq: int, ack_seq: int) -> bytes:
    return make_message_header(seq, ack_seq, 2049)


def _echo_payload(payload: bytes) -> bytes:
    if len(payload) > 128:
        raise ValueError("Echo payload must not exceed 128 bytes")
    return payload.ljust(128, b"\x00")


def make_echo_request(seq: int, ack_seq: int, payload: bytes) -> bytes:
    return make_message_header(seq, ack_seq, 1, 128) + _echo_payload(payload)


def make_ack(seq: int, ack_seq: int) -> bytes:
    return make_message_header(seq, ack_seq, 2050)


def make_echo_response(seq: int, ack_seq: int, payload: bytes) -> bytes:
    return make_message_header(seq, ack_seq, 2, 128) + _echo_payload(payload)


def make_program_reaction(
    seq: int, ack_seq: int, reaction_id: int, payload: bytes,
    reaction_len: int | None = None,
) -> bytes:
    if len(payload) > MAX_REACTION_PAYLOAD_SIZE:
        raise ValueError(f"Reaction payload must not exceed {MAX_REACTION_PAYLOAD_SIZE} bytes")
    length = len(payload) if reaction_len is None else reaction_len
    return (make_message_header(seq, ack_seq, 2052, 2 + MAX_REACTION_PAYLOAD_SIZE)
            + bytes((reaction_id, length)) + payload.ljust(MAX_REACTION_PAYLOAD_SIZE, b"\x00"))


def make_program_condition(
    seq: int, ack_seq: int, condition_id: int, reaction_id: int,
    payload: bytes, pattern_len: int | None = None,
) -> bytes:
    if len(payload) > MAX_CONDITION_MSG_SIZE:
        raise ValueError(f"Condition payload must not exceed {MAX_CONDITION_MSG_SIZE} bytes")
    length = len(payload) if pattern_len is None else pattern_len
    return (make_message_header(seq, ack_seq, 2053, 3 + MAX_CONDITION_MSG_SIZE)
            + bytes((condition_id, reaction_id, length)) + payload.ljust(MAX_CONDITION_MSG_SIZE, b"\x00"))


def make_disable_condition(seq: int, ack_seq: int, condition_id: int) -> bytes:
    return make_message_header(seq, ack_seq, 2054, 1) + bytes([condition_id])


def make_reaction_entry(payload: bytes, length: int) -> int:
    return ((1 << (8 + MAX_REACTION_PAYLOAD_SIZE * 8)) | (length << (MAX_REACTION_PAYLOAD_SIZE * 8))
            | int.from_bytes(payload.ljust(MAX_REACTION_PAYLOAD_SIZE, b"\x00"), "big"))


def make_condition_entry(reaction_id: int, payload: bytes, length: int) -> int:
    return ((1 << (16 + MAX_CONDITION_MSG_SIZE * 8)) | (reaction_id << (8 + MAX_CONDITION_MSG_SIZE * 8))
            | (length << (MAX_CONDITION_MSG_SIZE * 8))
            | int.from_bytes(payload.ljust(MAX_CONDITION_MSG_SIZE, b"\x00"), "big"))


def make_stimulus(request_id: int, payload: bytes) -> bytes:
    return b"\xaa" * 7 + b"\xab" + struct.pack("<QH", request_id, len(payload)) + payload


def make_reaction(
    request_id: int, trigger_condition_id: int, payload: bytes,
    reaction_len: int | None = None,
) -> bytes:
    if len(payload) > MAX_REACTION_PAYLOAD_SIZE:
        raise ValueError(f"Reaction payload must not exceed {MAX_REACTION_PAYLOAD_SIZE} bytes")
    length = len(payload) if reaction_len is None else reaction_len
    if not 0 <= length <= len(payload):
        raise ValueError("Reaction length must fit the supplied payload")
    return (b"\xaa" * 7 + b"\xab" + struct.pack("<QBB", request_id, trigger_condition_id, length)
            + payload[:length])


@dataclass(frozen=True)
class Message:
    size: int
    seq: int
    ack_seq: int
    msg_type: int
    payload: bytes


def parse_message(message: bytes) -> Message:
    size, seq, ack_seq, msg_type = struct.unpack_from("<HIIH", message)
    return Message(
        size=size, seq=seq, ack_seq=ack_seq, msg_type=msg_type,
        payload=message[HEADER_BYTES:size],
    )
