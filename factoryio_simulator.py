#!/usr/bin/env python3
"""A small Modbus/TCP process simulator for the OpenPLC lab."""

from __future__ import annotations

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import signal
import socketserver
import struct
import threading
import time
from dataclasses import dataclass, field


INPUT_COUNT = 7
COIL_COUNT = 5
DEFAULT_MODBUS_PORT = 502
INPUT_NAMES = (
    "StartButton",
    "SafetyDoorClosed",
    "BoxAtSensor",
    "RobotDetected",
    "MovingZ",
    "Rotating",
    "BoxPresent",
)
COIL_NAMES = ("Conveyor", "Grab", "ExtendZ", "RotateCW", "RotateCCW")
CONVEYOR_SPEED = 0.15
PICKER_ROTATION_SECONDS = 1.6
PICKER_Z_TRANSITION_SECONDS = 0.75


@dataclass
class Process:
    unit_id: int = 1
    emitter_interval: float = 5.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    door_closed: bool = True
    start_button_until: float = 0.0
    box_position: float | None = None
    box_held: bool = False
    boxes_removed: int = 0
    auto_emitter: bool = True
    last_emission: float = field(default_factory=time.monotonic)
    coils: list[bool] = field(default_factory=lambda: [False] * COIL_COUNT)
    z_down: bool = False
    z_transition_until: float = 0.0
    robot_angle: float = 0.0
    rotation_direction: int = 0
    events: deque[str] = field(default_factory=lambda: deque(maxlen=100))
    request_counts: list[int] = field(default_factory=lambda: [0] * 16)

    def read_inputs(self) -> list[bool]:
        with self.lock:
            now = time.monotonic()
            return [
                now < self.start_button_until,
                self.door_closed,
                self.box_position is not None and self.box_position >= 1.0,
                self.z_down and self.box_position is not None and self.robot_angle < 0.1,
                now < self.z_transition_until,
                self.rotation_direction != 0,
                self.box_position is not None or self.box_held,
            ]

    def read_coils(self, address: int, count: int) -> list[bool]:
        with self.lock:
            return self.coils[address : address + count]

    def write_coils(self, address: int, values: list[bool]) -> None:
        with self.lock:
            previous = self.coils[address : address + len(values)]
            self.coils[address : address + len(values)] = values
            for offset, (old_value, new_value) in enumerate(zip(previous, values)):
                if old_value != new_value:
                    name = COIL_NAMES[address + offset]
                    state = "ON" if new_value else "OFF"
                    self._record_event(f"Output {name} -> {state}")

    def reset(self) -> None:
        with self.lock:
            self.door_closed = True
            self.start_button_until = 0.0
            self.box_position = None
            self.box_held = False
            self.boxes_removed = 0
            self.auto_emitter = True
            self.last_emission = time.monotonic()
            self.coils = [False] * COIL_COUNT
            self.z_down = False
            self.z_transition_until = 0.0
            self.robot_angle = 0.0
            self.rotation_direction = 0
            self.events.clear()
            self.request_counts = [0] * len(self.request_counts)

    def record_request(self, function: int) -> None:
        with self.lock:
            if 0 <= function < len(self.request_counts):
                self.request_counts[function] += 1

    def drain_events(self) -> list[str]:
        with self.lock:
            events = list(self.events)
            self.events.clear()
            return events

    def _record_event(self, message: str) -> None:
        self.events.append(message)

    def set_start_button(self) -> None:
        with self.lock:
            self.start_button_until = time.monotonic() + 0.25
            self._record_event("Start button pressed (250 ms pulse)")

    def set_door(self, closed: bool) -> None:
        with self.lock:
            if self.door_closed != closed:
                self._record_event(f"Safety door {'closed' if closed else 'opened'}")
            self.door_closed = closed

    def set_auto_emitter(self, enabled: bool) -> None:
        with self.lock:
            if self.auto_emitter != enabled:
                self._record_event(f"Automatic box emitter {'enabled' if enabled else 'disabled'}")
            self.auto_emitter = enabled

    def add_box(self) -> bool:
        with self.lock:
            if self.box_position is not None:
                return False
            self.box_position = 0.0
            self._record_event("Box entered the conveyor")
            return True

    def status(self) -> str:
        inputs = self.read_inputs()
        coils = self.read_coils(0, COIL_COUNT)
        with self.lock:
            box = "none" if self.box_position is None else f"{self.box_position:.2f}"
            return (
                f"door={'closed' if self.door_closed else 'open'} "
                f"box_position={box} box_held={self.box_held} "
                f"removed={self.boxes_removed} auto_emitter={self.auto_emitter}\n"
                f"inputs={inputs} coils={coils}"
            )

    def step(self, now: float, dt: float) -> None:
        with self.lock:
            if self.auto_emitter and self.box_position is None:
                if now - self.last_emission >= self.emitter_interval:
                    self.box_position = 0.0
                    self.last_emission = now
                    self._record_event("Automatic emitter released a box")

            if not self.door_closed:
                return

            conveyor, grab, extend_z, rotate_cw, rotate_ccw = self.coils

            if extend_z != self.z_down:
                self.z_down = extend_z
                self.z_transition_until = now + PICKER_Z_TRANSITION_SECONDS
                self._record_event(f"Picker Z axis {'extending' if extend_z else 'retracting'}")

            direction = 0
            if rotate_cw and not rotate_ccw and self.robot_angle < 1.0:
                self.robot_angle = min(1.0, self.robot_angle + dt / PICKER_ROTATION_SECONDS)
                direction = 1
            elif rotate_ccw and not rotate_cw and self.robot_angle > 0.0:
                self.robot_angle = max(0.0, self.robot_angle - dt / PICKER_ROTATION_SECONDS)
                direction = -1

            if direction != self.rotation_direction:
                if direction:
                    movement = "clockwise" if direction > 0 else "counter-clockwise"
                    self._record_event(f"Picker rotating {movement}")
                elif self.rotation_direction:
                    self._record_event(
                        f"Picker rotation stopped at {self.robot_angle * 90:.0f} degrees"
                    )
                self.rotation_direction = direction

            if (
                grab
                and self.z_down
                and self.robot_angle < 0.1
                and self.box_position is not None
                and self.box_position >= 1.0
            ):
                self.box_held = True
                self.box_position = None
                self._record_event("Picker grabbed the box")

            if not grab and self.box_held and not self.z_down and self.robot_angle >= 0.9:
                self.box_held = False
                self.boxes_removed += 1
                self._record_event(f"Box released at drop point (removed={self.boxes_removed})")

            if conveyor and self.box_position is not None:
                previous_position = self.box_position
                self.box_position += dt * CONVEYOR_SPEED
                if previous_position < 1.0 <= self.box_position:
                    self._record_event("Box reached the pickup sensor")
                if self.box_position > 1.5:
                    self._record_event("Box passed the end of the conveyor")
                    self.box_position = None

    def live_status(self) -> str:
        inputs = self.read_inputs()
        coils = self.read_coils(0, COIL_COUNT)
        with self.lock:
            request_counts = self.request_counts.copy()
            if self.box_held:
                box = "HELD BY PICKER"
            elif self.box_position is None:
                box = "none"
            else:
                progress = max(0, min(20, round(self.box_position / 1.5 * 20)))
                box = f"[{'#' * progress}{'.' * (20 - progress)}] {self.box_position:.2f}/1.50"
            angle = self.robot_angle * 90
            return (
                f"Door: {'CLOSED' if self.door_closed else 'OPEN'} | "
                f"Auto emitter: {'ON' if self.auto_emitter else 'OFF'}\n"
                f"Conveyor: {box}\n"
                f"Picker: Z={'DOWN' if self.z_down else 'UP'} "
                f"angle={angle:.0f}deg | Removed: {self.boxes_removed}\n"
                f"Inputs: " + "  ".join(
                    f"{name}={'ON' if value else 'off'}"
                    for name, value in zip(INPUT_NAMES, inputs)
                ) + "\n"
                f"Coils:  " + "  ".join(
                    f"{name}={'ON' if value else 'off'}"
                    for name, value in zip(COIL_NAMES, coils)
                ) + "\n"
                f"Modbus requests: FC1={request_counts[1]} "
                f"FC2={request_counts[2]} FC5={request_counts[5]} "
                f"FC15={request_counts[15]}"
            )


def _exception_response(function: int, code: int) -> bytes:
    return bytes((function | 0x80, code))


def _log_multiple_coil_write(
    address: int, values: list[bool], transaction_id: int | None
) -> None:
    outputs = ", ".join(
        f"{COIL_NAMES[address + offset]}={'ON' if value else 'OFF'}"
        for offset, value in enumerate(values)
    )
    transaction = (
        f" transaction_id=0x{transaction_id:04x};"
        if transaction_id is not None
        else ""
    )
    print(
        f"Received FC 15 write:{transaction} address={address}, "
        f"count={len(values)}; "
        f"outputs: {outputs}",
        flush=True,
    )


def process_pdu(
    process: Process, pdu: bytes, transaction_id: int | None = None
) -> bytes:
    if not pdu:
        return b""

    function = pdu[0]
    process.record_request(function)
    if function in (1, 2):
        if len(pdu) != 5:
            return _exception_response(function, 3)
        address, count = struct.unpack(">HH", pdu[1:])
        if count < 1 or count > 2000:
            return _exception_response(function, 3)
        limit = COIL_COUNT if function == 1 else INPUT_COUNT
        if address + count > limit:
            return _exception_response(function, 2)
        values = (
            process.read_coils(address, count)
            if function == 1
            else process.read_inputs()[address : address + count]
        )
        packed = bytearray((count + 7) // 8)
        for index, value in enumerate(values):
            if value:
                packed[index // 8] |= 1 << (index % 8)
        return bytes((function, len(packed))) + packed

    if function == 5:
        if len(pdu) != 5:
            return _exception_response(function, 3)
        address, value = struct.unpack(">HH", pdu[1:])
        if address >= COIL_COUNT:
            return _exception_response(function, 2)
        if value not in (0x0000, 0xFF00):
            return _exception_response(function, 3)
        process.write_coils(address, [value == 0xFF00])
        return pdu

    if function == 15:
        if len(pdu) < 6:
            return _exception_response(function, 3)
        address, count, byte_count = struct.unpack(">HHB", pdu[1:6])
        if count < 1 or count > 1968 or byte_count != (count + 7) // 8:
            return _exception_response(function, 3)
        if len(pdu) != 6 + byte_count:
            return _exception_response(function, 3)
        if address + count > COIL_COUNT:
            return _exception_response(function, 2)
        values = [
            bool(pdu[6 + index // 8] & (1 << (index % 8)))
            for index in range(count)
        ]
        process.write_coils(address, values)
        _log_multiple_coil_write(address, values, transaction_id)
        return bytes((function,)) + struct.pack(">HH", address, count)

    return _exception_response(function, 1)


class ModbusHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client_host, client_port = self.client_address[:2]
#        print(
#            f"Modbus client connected: {client_host}:{client_port}",
#            flush=True,
#        )
        try:
            while True:
                header = self._receive_exactly(6)
#                print(
#                    "HEADER:",
#                    header.hex() if header else None,
#                    flush=True
#                )
                if header is None:
                    return
                transaction, protocol, length = struct.unpack(">HHH", header)
#                print(
#                    f"TXN={transaction} "
#                    f"PROTO={protocol} "
#                    f"LEN={length}",
#                   f"HEADER={header.hex()}",
#                    flush=True
#                )
                if protocol != 0 or length < 2 or length > 254:
                    return
                body = self._receive_exactly(length)
                if body is None:
                    return
#                print(f"PDU={body.hex()}", flush=True)
                unit_id, pdu = body[0], body[1:]
                response_pdu = (
                    process_pdu(self.server.process, pdu, transaction)
                    if unit_id == self.server.process.unit_id
                    else _exception_response(pdu[0] if pdu else 0, 11)
                )
                response_body = bytes((unit_id,)) + response_pdu
                response_header = struct.pack(">HHH", transaction, 0, len(response_body))
#                print(
#                    f"SENDING RESPONSE TXN={transaction}",
#                    flush=True
#                )
                self.request.sendall(response_header + response_body)
        finally:
            print(
                f"Modbus client disconnected: {client_host}:{client_port}",
                flush=True,
            )

    def _receive_exactly(self, count: int) -> bytes | None:
        data = bytearray()
        while len(data) < count:
            chunk = self.request.recv(count - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)


class ModbusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], process: Process):
        self.process = process
        super().__init__(address, ModbusHandler)


class ResetHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return

        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/start":
            self.server.process.set_start_button()
        elif self.path == "/reset":
            self.server.process.reset()
        else:
            self.send_error(404)
            return

        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        del _format, _args


class ResetServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], process: Process):
        self.process = process
        super().__init__(address, ResetHandler)


def run_simulation(process: Process, tick: float) -> None:
    last = time.monotonic()
    while True:
        time.sleep(tick)
        now = time.monotonic()
        process.step(now, now - last)
        last = now


def run_cli(process: Process) -> None:
    print("Commands: start, box, door open|close, auto on|off, reset, status, help, quit")
    while True:
        try:
            command = input("sim> ").strip().lower().split()
        except EOFError:
            return
        if not command:
            continue
        if command == ["quit"]:
            return
        if command == ["help"]:
            print("start: pulse the start button; box: add a box at the emitter")
            print("door open|close: set the safety door; auto on|off: emitter mode")
            print("reset: restore the simulator startup state")
            print("status: show process state; quit: stop the simulator")
        elif command == ["start"]:
            process.set_start_button()
            print("Start button pulsed.")
        elif command == ["box"]:
            print("Box added." if process.add_box() else "A box is already in the process.")
        elif command[:1] == ["door"] and len(command) == 2 and command[1] in ("open", "close"):
            process.set_door(command[1] == "close")
            print(f"Safety door {command[1]}.")
        elif command[:1] == ["auto"] and len(command) == 2 and command[1] in ("on", "off"):
            process.set_auto_emitter(command[1] == "on")
            print(f"Emitter {'enabled' if command[1] == 'on' else 'disabled'}.")
        elif command == ["reset"]:
            process.reset()
            print("Simulator process reset to startup baseline.")
        elif command == ["status"]:
            print(process.live_status())
        else:
            print("Unknown command. Type 'help' for available commands.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: all interfaces)")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_MODBUS_PORT,
        help=f"Modbus/TCP port (default: {DEFAULT_MODBUS_PORT})",
    )
    parser.add_argument("--unit-id", type=int, default=1, help="Modbus unit ID (default: 1)")
    parser.add_argument(
        "--reset-port",
        type=int,
        default=8081,
        help="loopback-only process reset HTTP port (default: 8081)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without the interactive terminal command prompt",
    )
    parser.add_argument("--emitter-interval", type=float, default=5.0, help="seconds between automatic boxes")
    args = parser.parse_args()
    if not 0 <= args.unit_id <= 247:
        parser.error("--unit-id must be between 0 and 247")
    if not 1 <= args.reset_port <= 65535:
        parser.error("--reset-port must be between 1 and 65535")
    if args.emitter_interval <= 0:
        parser.error("--emitter-interval must be positive")
    process = Process(unit_id=args.unit_id, emitter_interval=args.emitter_interval)
    server = ModbusServer((args.host, args.port), process)
    reset_server = ResetServer(("127.0.0.1", args.reset_port), process)
    print(
        f"Modbus/TCP listening on {args.host}:{args.port}, unit ID {args.unit_id}. "
        f"Local reset endpoint on 127.0.0.1:{args.reset_port}."
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=run_simulation, args=(process, 0.05), daemon=True).start()
    reset_thread = threading.Thread(target=reset_server.serve_forever, daemon=True)
    reset_thread.start()
    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop_event.set())
    try:
        if args.headless:
            stop_event.wait()
        else:
            run_cli(process)
    except KeyboardInterrupt:
        print()
    finally:
        server.shutdown()
        server.server_close()
        reset_server.shutdown()
        reset_server.server_close()
        reset_thread.join(timeout=1)


if __name__ == "__main__":
    main()