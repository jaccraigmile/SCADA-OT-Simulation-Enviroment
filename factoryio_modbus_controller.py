#!/usr/bin/env python3
"""Control the Factory I/O replacement simulator directly over Modbus/TCP."""

from __future__ import annotations

import argparse
import socket
import struct
import time
from dataclasses import dataclass


INPUT_NAMES = (
    "StartButton",
    "SafetyDoorClosed",
    "BoxAtSensor",
    "RobotDetected",
    "MovingZ",
    "Rotating",
)
COIL_NAMES = ("Conveyor", "Grab", "ExtendZ", "RotateCW", "RotateCCW")
INPUT_COUNT = len(INPUT_NAMES)
COIL_COUNT = len(COIL_NAMES)
DEFAULT_MODBUS_PORT = 502


def receive_exactly(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ConnectionError("simulator closed the Modbus connection")
        data.extend(chunk)
    return bytes(data)


class ModbusTCPClient:
    def __init__(
        self,
        host: str,
        port: int,
        unit_id: int,
        timeout: float,
    ) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self.transaction_id = 0
        self.connection: socket.socket | None = None

    def connect(self) -> None:
        self.close()
        self.connection = socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        )
        self.connection.settimeout(self.timeout)

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _exchange(self, pdu: bytes) -> bytes:
        if self.connection is None:
            raise ConnectionError("Modbus client is not connected")

        transaction_id = self.transaction_id
        self.transaction_id = (self.transaction_id + 1) & 0xFFFF
        header = struct.pack(
            ">HHHB", transaction_id, 0, len(pdu) + 1, self.unit_id
        )
        try:
            self.connection.sendall(header + pdu)
            response_header = receive_exactly(self.connection, 7)
            response_transaction, protocol, length, unit_id = struct.unpack(
                ">HHHB", response_header
            )
            if (
                response_transaction != transaction_id
                or protocol != 0
                or unit_id != self.unit_id
                or not 2 <= length <= 254
            ):
                raise ValueError("invalid Modbus/TCP response header")
            response = receive_exactly(self.connection, length - 1)
        except (OSError, ValueError):
            self.close()
            raise

        if response[0] == (pdu[0] | 0x80):
            exception_code = response[1] if len(response) > 1 else "unknown"
            raise ValueError(f"Modbus exception code {exception_code}")
        if response[0] != pdu[0]:
            raise ValueError("response function code does not match request")
        return response

    def read_bits(self, function: int, count: int) -> list[bool]:
        if function not in (1, 2):
            raise ValueError("bit reads must use function code 1 or 2")
        request = struct.pack(">BHH", function, 0, count)
        response = self._exchange(request)
        expected_bytes = (count + 7) // 8
        if (
            len(response) != expected_bytes + 2
            or response[1] != expected_bytes
        ):
            raise ValueError("invalid Modbus bit response")
        return [
            bool(response[2 + index // 8] & (1 << (index % 8)))
            for index in range(count)
        ]

    def read_inputs(self) -> list[bool]:
        return self.read_bits(2, INPUT_COUNT)

    def write_coils(self, values: list[bool]) -> None:
        if len(values) != COIL_COUNT:
            raise ValueError(f"expected {COIL_COUNT} coil values")
        byte_count = (len(values) + 7) // 8
        packed_values = bytearray(byte_count)
        for index, value in enumerate(values):
            if value:
                packed_values[index // 8] |= 1 << (index % 8)
        request = (
            struct.pack(">BHHB", 15, 0, len(values), byte_count)
            + packed_values
        )
        response = self._exchange(request)
        expected_response = struct.pack(">BHH", 15, 0, len(values))
        if response != expected_response:
            raise ValueError("invalid FC 15 write response")

    def write_all_coils_off(self) -> None:
        self.write_coils([False] * COIL_COUNT)


@dataclass
class Controller:
    client: ModbusTCPClient
    poll_interval: float
    status_interval: float
    state: str = "WAIT_START"
    run_enabled: bool = False
    coil_states: list[bool] | None = None
    motion_seen: bool = False
    robot_detected_seen: bool = False
    state_started: float = 0.0
    next_status: float = 0.0
    last_inputs: list[bool] | None = None

    def __post_init__(self) -> None:
        if self.coil_states is None:
            self.coil_states = [False] * COIL_COUNT
        self.next_status = time.monotonic()

    def log(self, message: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)

    def set_outputs(self, values: list[bool]) -> None:
        assert self.coil_states is not None
        if self.coil_states != values:
            previous = self.coil_states.copy()
            self.client.write_coils(values)
            self.coil_states = values.copy()
            for address, (old_value, value) in enumerate(
                zip(previous, values)
            ):
                if old_value != value:
                    self.log(
                        f"Output {COIL_NAMES[address]} -> "
                        f"{'ON' if value else 'OFF'}"
                    )

    def reset_for_safety(self) -> None:
        self.set_outputs([False] * COIL_COUNT)
        if self.run_enabled or self.state != "WAIT_START":
            self.log("Safety door open; stopping and waiting for Start")
        self.run_enabled = False
        self.state = "WAIT_START"
        self.motion_seen = False
        self.robot_detected_seen = False

    def scan(self, now: float) -> None:
        inputs = self.client.read_inputs()
        self.last_inputs = inputs
        start, door_closed, box_at_sensor, robot_detected, moving_z, rotating = inputs

        if not door_closed:
            self.reset_for_safety()
            return

        if not self.run_enabled and start:
            self.run_enabled = True
            self.state = "FEED"
            self.log("Start pulse received; cycle enabled")

        outputs = [False] * COIL_COUNT
        if not self.run_enabled:
            self.set_outputs(outputs)
            return

        if self.state == "FEED":
            if box_at_sensor:
                self.state = "LOWER"
                self.log("Box at pickup sensor; lowering picker")
            else:
                outputs[0] = True

        elif self.state == "LOWER":
            outputs[2] = True
            if robot_detected:
                self.robot_detected_seen = True
                outputs[1] = True
                self.state = "PICK"
                self.log("Box detected under picker; closing grab")

        elif self.state == "PICK":
            outputs[1] = True
            if self.robot_detected_seen and not robot_detected:
                self.state = "RETRACT"
                self.motion_seen = False
                self.log("Box picked; retracting picker")
            else:
                outputs[2] = True

        elif self.state == "RETRACT":
            outputs[1] = True
            if moving_z:
                self.motion_seen = True
            if self.motion_seen and not moving_z:
                self.state = "ROTATE_TO_DROP"
                self.motion_seen = False
                self.log("Picker retracted; rotating toward drop point")
            else:
                outputs[2] = False

        elif self.state == "ROTATE_TO_DROP":
            outputs[1] = True
            outputs[3] = True
            if rotating:
                self.motion_seen = True
            elif self.motion_seen:
                self.state = "RELEASE"
                self.state_started = now
                self.motion_seen = False
                self.log("Drop point reached; releasing box")

        elif self.state == "RELEASE":
            if now - self.state_started >= 0.2:
                self.state = "ROTATE_TO_PICKUP"
                self.motion_seen = False
                self.log("Box released; returning picker")

        elif self.state == "ROTATE_TO_PICKUP":
            outputs[4] = True
            if rotating:
                self.motion_seen = True
            elif self.motion_seen:
                self.state = "FEED"
                self.motion_seen = False
                self.robot_detected_seen = False
                self.log("Picker returned; ready for next box")

        else:
            self.log(f"Unknown controller state {self.state}; resetting")
            self.run_enabled = False
            self.state = "WAIT_START"

        self.set_outputs(outputs)

        if self.status_interval and now >= self.next_status:
            self.log(
                f"State={self.state} RUN={self.run_enabled} "
                f"Inputs={dict(zip(INPUT_NAMES, inputs))} "
                f"Coils={dict(zip(COIL_NAMES, self.coil_states))}"
            )
            self.next_status = now + self.status_interval

    def run(self) -> None:
        self.client.connect()
        self.client.write_all_coils_off()
        self.coil_states = [False] * COIL_COUNT
        self.log(
            f"Connected to simulator at {self.client.host}:{self.client.port}, "
            f"unit ID {self.client.unit_id}. Waiting for Start pulse."
        )
        try:
            while True:
                started = time.monotonic()
                self.scan(started)
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, self.poll_interval - elapsed))
        finally:
            try:
                self.client.write_all_coils_off()
            finally:
                self.client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="10.77.20.10", help="simulator IP address")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_MODBUS_PORT,
        help=f"Modbus/TCP port (default: {DEFAULT_MODBUS_PORT})",
    )
    parser.add_argument("--unit-id", type=int, default=1, help="Modbus unit ID")
    parser.add_argument("--poll-interval", type=float, default=0.05, help="seconds between scans")
    parser.add_argument("--status-interval", type=float, default=2.0, help="seconds between status lines; 0 disables")
    parser.add_argument("--timeout", type=float, default=2.0, help="Modbus socket timeout in seconds")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 0 <= args.unit_id <= 247:
        parser.error("--unit-id must be between 0 and 247")
    if args.poll_interval <= 0 or args.timeout <= 0 or args.status_interval < 0:
        parser.error("poll interval and timeout must be positive; status interval must not be negative")

    controller = Controller(
        ModbusTCPClient(args.host, args.port, args.unit_id, args.timeout),
        args.poll_interval,
        args.status_interval,
    )
    try:
        controller.run()
    except KeyboardInterrupt:
        print("\nController stopped.", flush=True)
    except (OSError, ValueError, ConnectionError) as error:
        parser.exit(1, f"Modbus controller failed: {error}\n")


if __name__ == "__main__":
    main()
