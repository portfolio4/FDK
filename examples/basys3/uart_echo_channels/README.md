The FPGA echoes messages received over UART on channel 5. The host program sends
`Hello World 0!`, `Hello World 1!`, and so on, prints each echoed response, and
repeats once per second.

With Vivado on PATH and the Basys3 connected through its PROG USB port,
run from the repository root:

```sh
python build.py --platform fpga --directory examples/basys3/uart_echo_channels
python run.py --platform fpga --directory examples/basys3/uart_echo_channels
```

Press the center button to reset and start the example.

Build the host client, then run it explicitly (replace the serial device path as needed):

```sh
python build.py --platform host --target basys3_uart_echo_channels
python run.py --platform host --target basys3_uart_echo_channels -- /dev/ttyUSB1
```

Activate the Python environment before building. CMake defaults to `g++-16`;
no compiler environment variable is required. See the root README for
prerequisites, output overrides, and test commands. Rebuild before programming
after source changes; running an artifact does not build it implicitly.
