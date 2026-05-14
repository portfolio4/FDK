The FPGA echoes bytes received over UART back over TX. The host program sends
`Hello world!`, prints the echoed bytes, waits one second, and repeats.

With Vivado on PATH and the Basys3 connected through its PROG USB port,
run from the repository root:

```sh
python build.py --platform fpga --directory examples/basys3/uart_echo_bytes
python run.py --platform fpga --directory examples/basys3/uart_echo_bytes
```

Press the center button to reset and start the example.

Build the host receiver, then run it explicitly (replace the serial device path as needed):

```sh
python build.py --platform host --target basys3_uart_echo_bytes
python run.py --platform host --target basys3_uart_echo_bytes -- /dev/ttyUSB1
```

Activate the Python environment before building. CMake defaults to `g++-16`;
no compiler environment variable is required. See the root README for
prerequisites, output overrides, and test commands. Rebuild before programming
after source changes; running an artifact does not build it implicitly.
