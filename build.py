"""Build host executables or FPGA bitstreams from the repository root."""

import build_tools.common


def main() -> None:
    parser = build_tools.common.application_parser(__doc__)
    args = parser.parse_args()
    directory = build_tools.common.validate_application_options(parser, args)
    if args.platform == "host":
        build_tools.common.build_host(
            args.build_dir or build_tools.common.host_build_directory(args.mode), [args.target], mode=args.mode)
    elif args.platform == "fpga":
        build_tools.common.invoke_fpga(directory, "build_fpga", args.build_dir, mode=args.mode)


if __name__ == "__main__":
    main()
