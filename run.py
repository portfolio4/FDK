"""Run an existing host executable or program an existing FPGA bitstream."""

import shlex
import subprocess

import build_tools.common


def main() -> None:
    parser = build_tools.common.application_parser(__doc__)
    arguments, forwarded = build_tools.common.split_arguments()
    args = parser.parse_args(arguments)
    directory = build_tools.common.validate_application_options(parser, args)
    if args.platform == "host":
        build_dir = (args.build_dir or build_tools.common.host_build_directory(args.mode)).resolve()
        executable = build_tools.common.executable_path(build_dir, args.target)
        command = [str(executable), *forwarded]
        print(shlex.join(command), flush=True)
        subprocess.run(command, check=True)
    elif args.platform == "fpga":
        if forwarded:
            parser.error("fpga run does not accept arguments after --")
        build_tools.common.invoke_fpga(directory, "program_fpga", args.build_dir, mode=args.mode)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
