"""Shared message test types and frame generation."""

from dataclasses import dataclass

from tests.fpga.rtl.channel.util import ChannelFrame, ChannelUtil

HEADER_BYTES = 12


@dataclass(frozen=True)
class MessageBeat:
    msg_size: int
    seq: int
    ack_seq: int
    msg_type: int
    sop: bool
    eop: bool
    data: int
    data_len: int | None = None  # this is the message_tx input byte count; RX always emits full beats.


class MessageUtil:
    def __init__(self, channel_util: ChannelUtil) -> None:
        self.channel_util = channel_util

    def encode_channel_frames(
        self, payload: bytes, *, seq: int = 0x12345678,
        ack_seq: int = 0x90ABCDEF, msg_type: int = 0xA5B6, padding: int = 0,
    ) -> list[ChannelFrame]:
        width = self.channel_util.num_payload_bytes_per_channel_frame
        message = ((HEADER_BYTES + len(payload)).to_bytes(2, "little") +
                   seq.to_bytes(4, "little") + ack_seq.to_bytes(4, "little") +
                   msg_type.to_bytes(2, "little") + payload)
        channel_payload = message + bytes((padding,)) * (-len(message) % width)
        return [ChannelFrame(
            channel_id=5, out_sop=i == 0, out_eop=i + width == len(channel_payload),
            reserved=0, out_data=int.from_bytes(channel_payload[i:i + width], "big"),
        ) for i in range(0, len(channel_payload), width)]

    def encode_tx_message(
        self, payload: bytes, *, seq: int = 0x12345678,
        ack_seq: int = 0x90ABCDEF, msg_type: int = 0xA5B6,
    ) -> tuple[list[MessageBeat], list[ChannelFrame]]:
        width = self.channel_util.num_payload_bytes_per_channel_frame
        beats = [MessageBeat(
            msg_size=HEADER_BYTES + len(payload), seq=seq, ack_seq=ack_seq, msg_type=msg_type,
            sop=i == 0, eop=i + width >= len(payload),
            # Intentionally fill unused lanes with wrong bytes 0xAA: the DUT must ignore
            # them according to data_len and generate zero padding on its output.
            data=int.from_bytes(payload[i:i + width].ljust(width, b"\xaa"), "big"),
            data_len=len(payload[i:i + width]),
        ) for i in range(0, max(1, len(payload)), width)]
        frames = self.encode_channel_frames(payload, seq=seq, ack_seq=ack_seq, msg_type=msg_type, padding=0)
        return beats, frames

    def encode_rx_message(
        self, payload: bytes, *, seq: int = 0x12345678,
        ack_seq: int = 0x90ABCDEF, msg_type: int = 0xA5B6, padding: int = 0xA5,
    ) -> tuple[list[ChannelFrame], list[MessageBeat]]:
        width = self.channel_util.num_payload_bytes_per_channel_frame
        frames = self.encode_channel_frames(payload, seq=seq, ack_seq=ack_seq, msg_type=msg_type, padding=padding)
        channel_payload = b"".join(frame.out_data.to_bytes(width, "big") for frame in frames)
        # Input channel padding remains part of the opaque payload. Only the
        # receiver's own final output lanes are filled with additional zeros.
        body = channel_payload[HEADER_BYTES:]
        output_words = [body[i:i + width].ljust(width, b"\x00")
                        for i in range(0, len(body), width)] or [bytes(width)]
        expected = [MessageBeat(
            msg_size=HEADER_BYTES + len(payload), seq=seq, ack_seq=ack_seq, msg_type=msg_type,
            sop=i == 0, eop=i == len(output_words) - 1,
            data=int.from_bytes(word, "big"),
        ) for i, word in enumerate(output_words)]
        return frames, expected
