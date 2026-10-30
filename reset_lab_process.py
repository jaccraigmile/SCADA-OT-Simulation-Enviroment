#!/usr/bin/env python3
"""Reset the local simulator process to its startup state."""

from __future__ import annotations

import argparse
from urllib.error import URLError
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="confirm that the selected controller is stopped and the process may reset",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8081,
        help="simulator's loopback-only reset port (default: 8081)",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("stop the selected controller, then pass --confirm to reset the process")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    request = Request(
        f"http://127.0.0.1:{args.port}/reset",
        data=b"",
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            if response.status != 204:
                parser.exit(1, f"Simulator reset failed with HTTP {response.status}\n")
    except URLError as error:
        parser.exit(
            1,
            f"Could not reset the local simulator on port {args.port}: {error}\n"
            "Confirm the simulator is running and uses the same reset port.\n",
        )

    print(
        "Simulator reset to startup state: door closed, coils off, no box, "
        "picker home, removed count zero, and automatic emitter enabled."
    )
    print("Controller, VM, firewall, and Proxmox network settings were not changed.")


if __name__ == "__main__":
    main()
