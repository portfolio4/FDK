"""Reaction storage, metadata publication, and streamed read flow control."""

from dataclasses import dataclass

import cocotb
from cocotb.triggers import Timer

from tests.apps.afk.fpga.message_helpers import MAX_REACTION_MESSAGE_SIZE


@dataclass
class StoreData:
    reaction_id: int
    word_index: int
    data: bytes
    reaction_len: int


@dataclass
class LoadData:
    reaction_id: int
    request_id: int = 0
    condition_id: int = 0


@dataclass
class LoadResultData:
    valid: bool
    sop: bool
    eop: bool
    data: bytes


def decode_out_load(value: int, payload_bytes: int) -> LoadResultData:
    data_bits = payload_bytes * 8
    return LoadResultData(
        valid=bool((value >> (data_bits + 2)) & 1),
        sop=bool((value >> (data_bits + 1)) & 1),
        eop=bool((value >> data_bits) & 1),
        data=(value & ((1 << data_bits) - 1)).to_bytes(payload_bytes, "big"),
    )


def pack_fields(*fields):
    value = 0
    for field, width in fields:
        assert 0 <= field < (1 << width)
        value = (value << width) | int(field)
    return value


class Driver:
    def __init__(self, dut):
        self.dut = dut
        self.width = int(dut.CHANNEL_PAYLOAD_BYTES.value)
        self.reactions = int(dut.MAX_REACTIONS.value)
        self.words = (MAX_REACTION_MESSAGE_SIZE + self.width - 1) // self.width
        self.index_bits = max(1, (self.words - 1).bit_length())
        self.responses: list[LoadResultData] = []
        self.stalled = None

    async def tick(self, *, store: StoreData | None = None,
                   load: LoadData | None = None, ready=True, reset=False):
        d = self.dut
        d.clk.value = 0
        d.rst.value = reset
        store_fields = store if store is not None else StoreData(reaction_id=0, word_index=0, data=b"", reaction_len=0)
        r = load if load is not None else LoadData(reaction_id=0)
        d.in_store.value = pack_fields(
            (store is not None, 1), (store_fields.reaction_id, 8),
            (store_fields.reaction_len, 8), (store_fields.word_index, self.index_bits),
            (int.from_bytes(store_fields.data.ljust(self.width, b"\0"), "big"), self.width * 8),
        )
        d.in_load.value = pack_fields(
            (load is not None, 1), (r.reaction_id, 8), (r.condition_id, 8), (r.request_id, 64),
        )
        d.out_load_ready.value = ready
        await Timer(time=5, unit="ns")
        accepted = (store is not None and bool(d.store_ready.value),
                    load is not None and bool(d.load_ready.value))
        response = decode_out_load(value=int(d.out_load.value), payload_bytes=self.width)
        if reset:
            self.stalled = None
            assert not response.valid
            assert not any((d.store_ready.value, d.load_ready.value))
            assert int(d.reaction_enabled.value) == 0
        else:
            if self.stalled is not None:
                assert response == self.stalled
            self.stalled = response if response.valid and not ready else None
            if response.valid and ready:
                self.responses.append(response)
        d.clk.value = 1
        await Timer(time=5, unit="ns")
        return accepted

    async def reset(self):
        await self.tick(reset=True)
        await self.tick()
        self.responses.clear()

    def make_random_payload(self, reaction_id):
        # Nonzero tail bytes must not leak into loads beyond reaction_len.
        return bytes((reaction_id * 29 + i * 17 + 1) % 256 for i in range(MAX_REACTION_MESSAGE_SIZE))

    def expected_word(self, payload, index):
        return payload[index*self.width:(index+1)*self.width].ljust(self.width, b"\0")

    async def store_payload(self, reaction_id, payload, reaction_len):
        assert len(payload) == MAX_REACTION_MESSAGE_SIZE
        for index in range(self.num_load_words(reaction_len=reaction_len)):
            await self.store_word(reaction_id=reaction_id, payload=payload, reaction_len=reaction_len, index=index)

    async def store_word(self, reaction_id, payload, reaction_len, index):
        # Deliberately supply nonzero padding; loads must still zero unused lanes.
        word = payload[index*self.width:(index+1)*self.width].ljust(self.width, b"\xa5")
        store = StoreData(reaction_id=reaction_id, word_index=index, data=word, reaction_len=reaction_len)
        for _ in range(self.words + 4):
            stored, _ = await self.tick(store=store)
            if stored:
                return
        raise AssertionError("Reaction store did not accept word")

    def num_load_words(self, reaction_len):
        return max(1, (reaction_len + self.width - 1) // self.width)

    async def load_payload(self, reaction_id, *, request_id=0, condition_id=0):
        _, accepted = await self.tick(load=LoadData(reaction_id=reaction_id, request_id=request_id, condition_id=condition_id))
        assert accepted
        await self.finish_load()

    async def wait_for_output(self):
        for _ in range(self.words + 4):
            if decode_out_load(int(self.dut.out_load.value), self.width).valid:
                return
            await self.tick(ready=False)
        raise AssertionError("Reaction load did not produce output")

    async def finish_load(self):
        # Complete only when the stream's final beat transfers.
        for _ in range(self.words + 1):
            response_count = len(self.responses)
            await self.tick()
            if len(self.responses) > response_count and self.responses[-1].eop:
                return
        raise AssertionError("Reaction load did not produce EOP")

    def expected_payload(self, payload, length, *, request_id=0, condition_id=0):
        message = bytearray(payload[:length])
        for index, value in enumerate(request_id.to_bytes(8, "little") + bytes([condition_id]), start=8):
            if index < len(message):
                message[index] = value
        return [LoadResultData(valid=True, sop=index == 0, eop=index == self.num_load_words(reaction_len=length)-1,
                               data=self.expected_word(payload=message, index=index))
                for index in range(self.num_load_words(reaction_len=length))]


@cocotb.test()
async def reaction_entries_are_isolated(dut):
    t = Driver(dut=dut)
    await t.reset()
    for reaction in range(t.reactions):
        await t.store_payload(reaction_id=reaction, payload=t.make_random_payload(reaction_id=reaction), reaction_len=19)
    for reaction in reversed(range(t.reactions)):
        t.responses.clear()
        await t.load_payload(reaction_id=reaction)
        assert t.responses == t.expected_payload(payload=t.make_random_payload(reaction_id=reaction), length=19)


@cocotb.test()
async def full_length_reaction_can_be_loaded(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=MAX_REACTION_MESSAGE_SIZE)
    await t.load_payload(reaction_id=0)
    assert t.responses == t.expected_payload(payload=payload, length=MAX_REACTION_MESSAGE_SIZE)


@cocotb.test()
async def unprogrammed_reaction_returns_one_zero_beat(dut):
    t = Driver(dut=dut)
    await t.reset()
    await t.load_payload(reaction_id=0)
    assert t.responses == [LoadResultData(valid=True, sop=True, eop=True, data=b"\x00" * t.width)]


@cocotb.test()
async def zero_length_reaction_returns_one_zero_beat(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=17)
    # ensure reaction_len=0 clears out the old reaction_len=17
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=0)
    await t.load_payload(reaction_id=0)
    assert t.responses == [
        LoadResultData(valid=True, sop=True, eop=True, data=b"\x00" * t.width)
    ]


@cocotb.test()
async def reaction_is_enabled_only_after_final_store_word(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    words = t.num_load_words(reaction_len=17)
    for index in range(words):
        await t.store_word(reaction_id=0, payload=payload, reaction_len=17, index=index)
        assert int(dut.reaction_enabled.value) == (1 if index == words-1 else 0)


@cocotb.test()
async def replacement_disables_reaction_until_final_store_word(dut):
    t = Driver(dut=dut)
    await t.reset()
    await t.store_payload(reaction_id=0, payload=t.make_random_payload(reaction_id=0), reaction_len=17)
    replacement = b"z" * MAX_REACTION_MESSAGE_SIZE
    words = t.num_load_words(reaction_len=7)
    for index in range(words):
        await t.store_word(reaction_id=0, payload=replacement, reaction_len=7, index=index)
        assert int(dut.reaction_enabled.value) == (1 if index == words-1 else 0)


@cocotb.test()
async def replacement_updates_stored_bytes_and_length(dut):
    t = Driver(dut=dut)
    await t.reset()
    await t.store_payload(reaction_id=0, payload=t.make_random_payload(reaction_id=0), reaction_len=17)
    replacement = b"z" * MAX_REACTION_MESSAGE_SIZE
    await t.store_payload(reaction_id=0, payload=replacement, reaction_len=7)
    await t.load_payload(reaction_id=0)
    assert t.responses == t.expected_payload(payload=replacement, length=7)


@cocotb.test()
async def reset_disables_programmed_reactions(dut):
    t = Driver(dut=dut)
    await t.reset()
    for reaction in range(t.reactions):
        await t.store_payload(reaction_id=reaction, payload=t.make_random_payload(reaction_id=reaction), reaction_len=17)
    await t.reset()
    assert int(dut.reaction_enabled.value) == 0
    for reaction in range(t.reactions):
        t.responses.clear()
        await t.load_payload(reaction_id=reaction)
        assert t.responses == [LoadResultData(valid=True, sop=True, eop=True, data=b"\x00" * t.width)]


@cocotb.test()
async def reset_aborts_partial_store(dut):
    t = Driver(dut=dut)
    await t.reset()
    await t.store_word(reaction_id=0, payload=t.make_random_payload(reaction_id=0),
                       reaction_len=MAX_REACTION_MESSAGE_SIZE, index=0)
    await t.reset()
    await t.load_payload(reaction_id=0)
    assert t.responses == [LoadResultData(valid=True, sop=True, eop=True, data=b"\x00" * t.width)]
    # A fresh store must start at word zero after reset.
    payload = b"z" * MAX_REACTION_MESSAGE_SIZE
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=7)
    t.responses.clear()
    await t.load_payload(reaction_id=0)
    assert t.responses == t.expected_payload(payload=payload, length=7)


@cocotb.test()
async def reset_aborts_stalled_load(dut):
    t = Driver(dut=dut)
    await t.reset()
    await t.store_payload(reaction_id=0, payload=t.make_random_payload(reaction_id=0), reaction_len=MAX_REACTION_MESSAGE_SIZE)
    _, loaded = await t.tick(load=LoadData(reaction_id=0), ready=False)
    assert loaded
    await t.tick(ready=False)
    await t.reset()
    for _ in range(3):
        await t.tick()
    assert t.responses == []
    assert dut.load_ready.value
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=17)
    await t.load_payload(reaction_id=0)
    assert t.responses == t.expected_payload(payload=payload, length=17)


@cocotb.test()
async def active_load_blocks_stores_through_final_transfer(dut):
    t = Driver(dut=dut)
    await t.reset()
    await t.store_payload(reaction_id=0, payload=t.make_random_payload(reaction_id=0), reaction_len=MAX_REACTION_MESSAGE_SIZE)
    pending_store = StoreData(reaction_id=0, word_index=0, data=b"\x00" * t.width, reaction_len=1)
    _, loaded = await t.tick(load=LoadData(reaction_id=0), ready=False)
    assert loaded
    for index in range(t.words):
        # Include stalls on every beat, including the final beat.
        for _ in range(2):
            stored, _ = await t.tick(store=pending_store, ready=False)
            assert not stored
        stored, _ = await t.tick(store=pending_store)
        assert not stored
        assert t.responses[-1].eop == (index == t.words-1)
    for _ in range(t.words + 4):
        stored, _ = await t.tick(store=pending_store)
        if stored:
            break
    else:
        raise AssertionError("Reaction store remained blocked after load")


@cocotb.test()
async def busy_load_attempts_are_dropped(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=MAX_REACTION_MESSAGE_SIZE)
    _, loaded = await t.tick(load=LoadData(reaction_id=0))
    assert loaded
    await t.wait_for_output()
    for _ in range(t.words):
        _, loaded = await t.tick(load=LoadData(reaction_id=0, request_id=0xDEADBEEF, condition_id=255))
        assert not loaded
    assert t.responses == t.expected_payload(payload=payload, length=MAX_REACTION_MESSAGE_SIZE)
    for _ in range(3):
        await t.tick()
    assert len(t.responses) == t.words
    assert dut.load_ready.value


@cocotb.test()
async def active_store_blocks_loads_through_gaps_and_final_word(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    words = t.num_load_words(reaction_len=17)
    for index in range(words):
        word = payload[index*t.width:(index+1)*t.width].ljust(t.width, b"\xa5")
        for _ in range(t.words + 4):
            stored, loaded = await t.tick(
                store=StoreData(reaction_id=0, word_index=index, data=word, reaction_len=17),
                load=LoadData(reaction_id=0) if index > 0 else None,
            )
            assert not loaded
            if stored:
                break
        else:
            raise AssertionError("Reaction store did not accept word")
        if index != words-1:
            _, loaded = await t.tick(load=LoadData(reaction_id=0))
            assert not loaded
    assert t.responses == []
    await t.load_payload(reaction_id=0)
    assert t.responses == t.expected_payload(payload=payload, length=17)


@cocotb.test()
async def idle_prioritizes_load_over_store(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=17)
    stored, loaded = await t.tick(
        store=StoreData(reaction_id=0, word_index=0, data=b"\x00" * t.width, reaction_len=1), load=LoadData(reaction_id=0),
    )
    assert loaded and not stored
    await t.finish_load()
    assert t.responses == t.expected_payload(payload=payload, length=17)


@cocotb.test()
async def loads_stream_one_beat_per_cycle(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=MAX_REACTION_MESSAGE_SIZE)
    _, loaded = await t.tick(load=LoadData(reaction_id=0))
    assert loaded
    await t.wait_for_output()
    for index in range(t.words):
        await t.tick()
        assert len(t.responses) == index+1
    assert t.responses == t.expected_payload(payload=payload, length=MAX_REACTION_MESSAGE_SIZE)


@cocotb.test()
async def stalled_output_holds_the_same_beat(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=MAX_REACTION_MESSAGE_SIZE)
    _, loaded = await t.tick(load=LoadData(reaction_id=0))
    assert loaded
    for index in range(t.words):
        for _ in range(3):
            await t.tick(ready=False)
            assert len(t.responses) == index
        await t.tick()
        assert len(t.responses) == index+1
    assert t.responses == t.expected_payload(payload=payload, length=MAX_REACTION_MESSAGE_SIZE)


@cocotb.test()
async def loads_stop_at_stored_length(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    lengths = sorted({1, t.width-1, t.width, t.width+1, MAX_REACTION_MESSAGE_SIZE})
    for length in lengths:
        if not 0 < length <= MAX_REACTION_MESSAGE_SIZE:
            continue
        await t.store_payload(reaction_id=0, payload=payload, reaction_len=length)
        t.responses.clear()
        await t.load_payload(reaction_id=0)
        expected_beats = t.num_load_words(reaction_len=length)
        assert len(t.responses) == expected_beats
        assert [beat.sop for beat in t.responses] == [True] + [False] * (expected_beats-1)
        assert [beat.eop for beat in t.responses] == [False] * (expected_beats-1) + [True]
        for _ in range(3):
            await t.tick()
        assert len(t.responses) == expected_beats


@cocotb.test()
async def final_beat_unused_lanes_are_zero(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = b"\xa5" * MAX_REACTION_MESSAGE_SIZE
    lengths = sorted({1, t.width-1, t.width+1, MAX_REACTION_MESSAGE_SIZE})
    for length in lengths:
        if not 0 < length <= MAX_REACTION_MESSAGE_SIZE:
            continue
        await t.store_payload(reaction_id=0, payload=payload, reaction_len=length)
        t.responses.clear()
        await t.load_payload(reaction_id=0)
        used_lanes = length % t.width or t.width
        assert t.responses[-1].data[used_lanes:] == b"\x00" * (t.width-used_lanes)


@cocotb.test()
async def loads_set_stimulus_header(dut):
    t = Driver(dut=dut)
    await t.reset()
    payload = t.make_random_payload(reaction_id=0)
    await t.store_payload(reaction_id=0, payload=payload, reaction_len=MAX_REACTION_MESSAGE_SIZE)
    for request_id in (0x0123456789ABCDEF, 0xFEDCBA9876543210):
        for condition_id in (3, 255):
            t.responses.clear()
            await t.load_payload(
                reaction_id=0, request_id=request_id, condition_id=condition_id)
            assert t.responses == t.expected_payload(
                payload=payload, length=MAX_REACTION_MESSAGE_SIZE,
                request_id=request_id, condition_id=condition_id)
