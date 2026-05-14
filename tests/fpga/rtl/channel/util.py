"""Shared channel beat test types and wire-format helpers."""

from dataclasses import dataclass
import random


@dataclass
class ChannelFrame:
    channel_id: int
    out_sop: bool
    out_eop: bool
    reserved: int
    out_data: int


class ChannelUtil:
    def __init__(self, num_payload_bytes_per_channel_frame: int) -> None:
        if num_payload_bytes_per_channel_frame <= 0:
            raise ValueError("Channel frame payload size must be positive")
        self.num_payload_bytes_per_channel_frame = num_payload_bytes_per_channel_frame

    def make_frame(
        self, channel_id: int, payload: bytes, *, sop: bool, eop: bool, reserved: int = 0,
    ) -> bytes:
        assert len(payload) == self.num_payload_bytes_per_channel_frame
        assert 0 <= reserved < 64
        descriptor = (reserved << 2) | (int(eop) << 1) | int(sop)
        return bytes((channel_id, descriptor)) + payload

    def make_random_frames(self, count: int) -> bytes:
        rng = random.Random(42)
        frames = []
        sop = True
        for i in range(count):
            if sop:
                channel_id = rng.randrange(256)
            # Random packet lengths; always finish the final packet.
            eop = rng.random() < 0.3 or i == count - 1
            frames.append(self.make_frame(
                channel_id=channel_id,
                sop=sop,
                eop=eop,
                payload=rng.randbytes(self.num_payload_bytes_per_channel_frame),
            ))
            sop = eop
        return b"".join(frames)

    def pad_to_beat_size(self, data: bytes, input_width: int) -> bytes:
        """Zero-pad to whole input beats; input_width is measured in bits.

        Padding is valid stream data and may form additional channel frames.
        """
        if input_width <= 0 or input_width % 8 != 0:
            raise ValueError("Input width must be a positive multiple of 8 bits")
        input_bytes = input_width // 8
        return data + bytes(-len(data) % input_bytes)

    def decode_frames(self, data: bytes) -> list[ChannelFrame]:
        frame_bytes = self.num_payload_bytes_per_channel_frame + 2
        # An incomplete trailing frame must not produce an output beat.
        return [
            ChannelFrame(
                channel_id=data[i],
                out_sop=bool(data[i + 1] & 1),
                out_eop=bool(data[i + 1] & 2),
                reserved=data[i + 1] >> 2,
                out_data=int.from_bytes(data[i + 2:i + frame_bytes], "big"),
            )
            for i in range(0, len(data) - frame_bytes + 1, frame_bytes)
        ]
