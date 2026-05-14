# Firmwide Development Kit

Originally named FPGA Development Kit (FDK), this repository began as a collection
of reusable RTL modules and C++ host libraries.

It has since grown into a monorepo for shared libraries, FPGA components,
applications, examples, and development tools. The name Firmwide Development Kit
reflects this broader scope while retaining the FDK abbreviation.

## System requirements

- Linux.
- Python 3.10 or newer with `venv` and `pip`, plus the dependencies in
  `requirements.txt`.
- CMake 3.30 or newer, Make or Ninja, and a compiler supporting the project's
  C++23 features. Host builds default to `g++-16`; set `CXX` to select another
  compatible compiler before the first build.
- A C compiler for whisper.cpp, zlib development headers and libraries, and Git.
  CMake fetches C++ dependencies during configuration, so the first host build
  needs network access. Boost 1.87 or newer can also be supplied locally.
- Catch2 3 for host tests; the default CMake configuration enables testing.
- Node.js on `PATH` to include AFK frontend tests; CMake skips them if unavailable.
- Vivado on `PATH` to build and program the FPGA, and a Basys3 connected through
  its PROG USB port.
- Verilator on `PATH` to run RTL simulation tests.

Run the following commands from the repository root. Create and activate the
Python environment first:

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Build and run the examples

Build and program the FPGA before starting its matching host client. Replace
`/dev/ttyUSB1` with the board's serial device; your user needs permission to
access it. Press Ctrl+C to stop a host client. Rebuild after source changes:
`run.py` uses the existing build.

Builds default to `--mode debug`. Host output goes into `build_debug/host/` with
CMake's Debug configuration. Use `--mode release` for Release output in
`build_release/host/`, and select the same mode when running:

```sh
python build.py --platform host --target afk_host --mode release
python run.py --platform host --target afk_host --mode release -- build_release/host/mount-afk /dev/ttyUSB1
```

`test.py` also accepts `--mode debug|release`. FPGA artifacts and simulations
live under the selected mode's `fpga/` and `sim/` subdirectories. The mode sets
the C++ build configuration; FPGA synthesis behavior is unchanged.
`--build-dir` overrides the build/run output path while retaining the selected
C++ configuration. Existing `build/` directories are no longer used by default.

### Byte echo

The FPGA echoes incoming UART bytes. The host sends `Hello world!` repeatedly
and logs the sent and received characters.

First, build and program the FPGA:

```sh
python build.py --platform fpga --directory examples/basys3/uart_echo_bytes
python run.py --platform fpga --directory examples/basys3/uart_echo_bytes
```

Press the board's center button to reset the example, then build and run the host:

```sh
python build.py --platform host --target basys3_uart_echo_bytes
python run.py --platform host --target basys3_uart_echo_bytes -- /dev/ttyUSB1
```

### Channel echo

The host sends messages over numbered channels. The FPGA responds on the same
channel, and the host verifies and logs each response.

First, build and program the FPGA:

```sh
python build.py --platform fpga --directory examples/basys3/uart_echo_channels
python run.py --platform fpga --directory examples/basys3/uart_echo_channels
```

Then build and run the host:

```sh
python build.py --platform host --target basys3_uart_echo_channels
python run.py --platform host --target basys3_uart_echo_channels -- /dev/ttyUSB1
```

## Repo Structure

### `fpga/`

`fpga/rtl/` contains reusable RTL IPs, including UART, FIFO, channel framing,
and message handling components. `fpga/host/` contains C++ interfaces for
interacting with those components from the host side.

### `cpp/`

General-purpose C++ libraries, including our own utilities under `cpp/fdk/`
and third-party dependency setup.

### `apps/`

Full applications built with the kit. [AI Food Kiosk (`apps/afk/`)](apps/afk/README.md)
combines a browser frontend, C++ server, Whisper speech recognition, Codex agent,
and FPGA trigger matcher to handle spoken food orders.

### `examples/`

Small example and test applications demonstrating individual kit features.
The Basys3 byte echo and channel echo examples pair FPGA designs with C++ host
clients to exercise UART communication and message handling.

### `build_tools/`

Shared Python tooling for the root `build.py`, `run.py`, and `test.py` commands,
using Vivado for FPGA builds, CMake for host builds, and Verilator for RTL
simulations. Generated artifacts live under `build_debug/` or `build_release/`.

### `tests/`

Automated tests for RTL components, C++ libraries, applications, and build tools.
Run all tests with `python test.py`, or select a suite with
`python test.py --directory tests/fpga/rtl`. The tests build their prerequisites
and run without Vivado or physical hardware.
