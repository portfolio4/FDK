from pathlib import Path
import subprocess

import tests.integration
import build_tools.common


def test_uart_echo_bytes_logs_fragmented_input(host_build_dir: Path) -> None:
    build_tools.common.build_host(host_build_dir, ["basys3_uart_echo_bytes"])
    executable = host_build_dir / "bin" / "basys3_uart_echo_bytes"
    greeting = b"Hello world!"
    with tests.integration.MockFdEndpoint() as serial:
        with subprocess.Popen(
            [str(executable), serial.slave_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) as client:
            try:
                assert client.stdout is not None
                log = tests.integration.FdTailer(client.stdout.fileno())
                assert serial.read_exact(len(greeting)) == greeting
                for fragment in (b"Hello ", b"world!"):
                    serial.send(fragment)
                    expected = "".join(f"Received: {chr(byte)}\n" for byte in fragment)
                    log.expect_str(expected)
                assert serial.read_exact(len(greeting)) == greeting
            finally:
                client.kill()
                client.wait(timeout=5)
