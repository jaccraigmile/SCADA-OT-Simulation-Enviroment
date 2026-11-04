#!/usr/bin/env python3
"""Start or reset the local simulator process."""

from __future__ import annotations

import argparse
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--confirm",
        action="store_true",
        help="confirm that the selected controller is stopped and the process may reset",
    )
    action.add_argument(
        "--start",
        action="store_true",
        help="pulse the simulator StartButton after confirming its local endpoint is ready",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8081,
        help="simulator's loopback-only reset port (default: 8081)",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    if args.start:
        health_request = Request(f"http://127.0.0.1:{args.port}/health")
        deadline = time.monotonic() + 10
        while True:
            try:
                with urlopen(health_request, timeout=1) as response:
                    if response.status != 204:
                        parser.exit(1, f"Simulator health check failed with HTTP {response.status}\n")
                break
            except URLError as error:
                if time.monotonic() >= deadline:
                    parser.exit(
                        1,
                        f"Simulator did not become ready on local port {args.port}: {error}\n",
                    )
                time.sleep(0.2)
        endpoint = "start"
    else:
        endpoint = "reset"

    request = Request(
        f"http://127.0.0.1:{args.port}/{endpoint}",
        data=b"",
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            if response.status != 204:
                parser.exit(
                    1,
                    f"Simulator {endpoint} action failed with HTTP {response.status}\n",
                )
    except URLError as error:
        parser.exit(
            1,
            f"Could not send the simulator {endpoint} action on port "
            f"{args.port}: {error}\n"
            "Confirm the simulator is running and uses the same reset port.\n",
        )

    if args.start:
        print("Simulator StartButton pulsed.")
    else:
        print(
            "Simulator reset to startup state: door closed, coils off, no box, "
            "picker home, removed count zero, and automatic emitter enabled."
        )
        print("Controller, VM, firewall, and Proxmox network settings were not changed.")


if __name__ == "__main__":
    main()
