from pathlib import Path
import subprocess
import struct

import pytest

import tests.integration
import build_tools.common
import fpga.rtl.channel
import fpga.rtl.fifo
import fpga.rtl.message
import fpga.rtl.platforms.basys3
import fpga.rtl.uart
import tests.fpga.rtl
from tests.fpga.rtl.channel.util import ChannelUtil


@pytest.mark.parametrize("payload_bytes", [8, 10, 12, 16])
def test_streaming_uart_echo(sim_build_dir: Path, payload_bytes: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[
            fpga.rtl.platforms.basys3.LIBRARY, fpga.rtl.message.LIBRARY,
            fpga.rtl.uart.LIBRARY, fpga.rtl.channel.LIBRARY, fpga.rtl.fifo.LIBRARY,
        ],
        rtl_files=[
            build_tools.common.REPO_ROOT / "examples/basys3/uart_echo_channels/request_handler.sv",
            build_tools.common.REPO_ROOT / "examples/basys3/uart_echo_channels/uart_echo_channels.sv",
        ],
        hdl_toplevel="uart_echo_channels",
        parameters={
            "CLK_FREQ_HZ": 16_000_000, "BAUD_RATE": 1_000_000,
            "CHANNEL_PAYLOAD_BYTES": payload_bytes,
        },
        build_dir=sim_build_dir / f"uart_echo_channels_{payload_bytes}",
        test_module="tests.examples.basys3.uart_echo_channels.test_uart_echo_channels",
    ).run()


def test_uart_echo_channels_exchanges_echo_messages_on_channel_5(host_build_dir: Path) -> None:
    build_tools.common.build_host(host_build_dir, ["basys3_uart_echo_channels"])
    executable = host_build_dir / "bin" / "basys3_uart_echo_channels"
    with tests.integration.MockFdEndpoint() as serial:
        with subprocess.Popen(
            [str(executable), serial.slave_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) as client:
            try:
                assert client.stdout is not None
                log = tests.integration.FdTailer(client.stdout.fileno())
                channel_id = 5
                payload_bytes = 8
                message_header = struct.Struct("<HIIH")
                message_size = message_header.size + 128
                util = ChannelUtil(payload_bytes)
                for index in range(2):
                    frames = []
                    while True:
                        frame = util.decode_frames(serial.read_exact(payload_bytes + 2))[0]
                        assert frame.channel_id == channel_id
                        assert frame.out_sop == (len(frames) == 0)
                        frames.append(frame)
                        if frame.out_eop:
                            break
                    request = b"".join(frame.out_data.to_bytes(payload_bytes, "big") for frame in frames)
                    size, seq, ack_seq, msg_type = message_header.unpack_from(request)
                    assert size == message_size
                    assert seq == index * message_size
                    assert ack_seq == 0
                    assert msg_type == 1  # EchoRequest
                    greeting = f"Hello World {index}!"
                    assert request[message_header.size:size] == greeting.encode().ljust(128, b"\x00")

                    response_seq = index * message_size
                    response = (message_header.pack(message_size, response_seq, seq, 2)
                                + request[message_header.size:size])
                    serial.send(b"".join(
                        util.make_frame(
                            channel_id, response[offset:offset + payload_bytes].ljust(payload_bytes, b"\x00"),
                            sop=offset == 0, eop=offset + payload_bytes >= len(response),
                        )
                        for offset in range(0, len(response), payload_bytes)
                    ))
                    log.expect_str(
                        f"EchoResponse channel={channel_id} seq={response_seq} ack={seq}: {greeting}\n"
                    )
            finally:
                client.kill()
                client.wait(timeout=5)
