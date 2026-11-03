#!/usr/bin/env python3
"""Serve a read-only browser HMI for the Factory I/O replacement simulator."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import struct
import threading
from typing import Any


INPUTS = (
    "StartButton",
    "SafetyDoorClosed",
    "BoxAtSensor",
    "RobotDetected",
    "MovingZ",
    "Rotating",
    "BoxPresent",
)
COILS = ("Conveyor", "Grab", "ExtendZ", "RotateCW", "RotateCCW")

HMI_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#101820">
  <title>Virtual OT Process HMI</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: "Segoe UI", Arial, sans-serif;
      background: #101820;
      color: #e7eef2;
      --panel: #1b2932;
      --line: #40515b;
      --muted: #9eb0ba;
      --green: #57d69a;
      --red: #ff6d6d;
      --amber: #ffc857;
      --blue: #70c7f5;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; }
    header {
      display: flex; align-items: center; justify-content: space-between;
      gap: 1rem; padding: 1rem clamp(1rem, 3vw, 2.5rem);
      border-bottom: 1px solid var(--line); background: #15212a;
    }
    h1 { font-size: clamp(1.15rem, 3vw, 1.65rem); margin: 0; }
    h2 { font-size: 1rem; margin: 0 0 .85rem; }
    .eyebrow { color: var(--muted); font-size: .75rem; letter-spacing: .12em;
      text-transform: uppercase; margin-bottom: .35rem; }
    main { max-width: 1400px; margin: auto; padding: 1.25rem clamp(1rem, 3vw, 2.5rem) 2rem; }
    .topline { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
    .badge { border: 1px solid var(--line); border-radius: 999px;
      padding: .35rem .7rem; font-size: .78rem; font-weight: 700; }
    .live { color: var(--green); border-color: #347e62; }
    .offline { color: var(--red); border-color: #8c4242; }
    .safety { color: var(--green); }
    .safety.open { color: var(--red); }
    .grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
      gap: 1rem; margin-top: 1rem; }
    .panel { background: var(--panel); border: 1px solid var(--line);
      border-radius: 12px; padding: 1rem; min-width: 0; }
    .diagram-wrap { overflow-x: auto; }
    svg { display: block; width: 100%; min-width: 650px; height: auto; }
    .track { stroke: #82939b; stroke-width: 14; stroke-linecap: round; }
    .roller { fill: #465963; stroke: #a7b5bb; stroke-width: 2; }
    .sensor { stroke: var(--blue); stroke-width: 4; }
    .machine-label { fill: #c8d4d9; font-size: 15px; }
    .small-label { fill: var(--muted); font-size: 12px; }
    .machine { fill: #263b47; stroke: #82939b; stroke-width: 3; }
    .arm { stroke: #d3dee2; stroke-width: 13; stroke-linecap: round; }
    .gripper { fill: none; stroke: #d3dee2; stroke-width: 7; stroke-linecap: round; }
    #box { fill: var(--amber); stroke: #fff0c2; stroke-width: 2; }
    #dropBox { fill: #ffc857; stroke: #fff0c2; stroke-width: 2; display: none; }
    .bin { fill: #25343c; stroke: #82939b; stroke-width: 3; }
    .signal-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .55rem; }
    .signal { display: flex; justify-content: space-between; align-items: center;
      gap: .5rem; border: 1px solid var(--line); border-radius: 8px; padding: .6rem .65rem;
      font-size: .85rem; }
    .signal-name { color: #dce5e9; }
    .state { font-size: .72rem; font-weight: 800; letter-spacing: .04em; }
    .on { color: var(--green); }
    .off { color: var(--muted); }
    .fault { color: var(--red); }
    .section-label { color: var(--muted); font-size: .72rem; text-transform: uppercase;
      letter-spacing: .1em; margin: 1rem 0 .5rem; }
    .telemetry { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
      color: var(--muted); font-size: .8rem; margin-top: .8rem; }
    .notice { color: var(--muted); font-size: .78rem; line-height: 1.45;
      border-top: 1px solid var(--line); margin-top: 1rem; padding-top: .75rem; }
    .error { color: var(--red); min-height: 1.2rem; font-size: .82rem; }
    @media (max-width: 850px) { .grid { grid-template-columns: 1fr; } }
    @media (max-width: 500px) { .signal-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div><div class="eyebrow">OT / SCADA training display</div><h1>Conveyor &amp; Pick-and-Place</h1></div>
    <div class="topline">
      <span id="connection" class="badge offline">CONNECTING</span>
      <span id="door" class="badge safety">DOOR —</span>
    </div>
  </header>
  <main>
    <div id="error" class="error" role="status"></div>
    <div class="grid">
      <section class="panel">
        <h2>Process overview</h2>
        <div class="diagram-wrap">
          <svg viewBox="0 0 1000 390" role="img" aria-labelledby="diagramTitle diagramDescription">
            <title id="diagramTitle">Conveyor and pick-and-place process</title>
            <desc id="diagramDescription">Approximate process animation derived from Modbus input and output states.</desc>
            <rect x="70" y="215" width="600" height="75" rx="8" class="machine"/>
            <line x1="105" y1="252" x2="625" y2="252" class="track"/>
            <g id="rollers">
              <circle cx="130" cy="252" r="13" class="roller"/><circle cx="200" cy="252" r="13" class="roller"/>
              <circle cx="270" cy="252" r="13" class="roller"/><circle cx="340" cy="252" r="13" class="roller"/>
              <circle cx="410" cy="252" r="13" class="roller"/><circle cx="480" cy="252" r="13" class="roller"/>
              <circle cx="550" cy="252" r="13" class="roller"/><circle cx="620" cy="252" r="13" class="roller"/>
            </g>
            <text x="275" y="325" class="machine-label">CONVEYOR</text>
            <line x1="610" y1="195" x2="610" y2="303" class="sensor"/>
            <text x="566" y="185" class="small-label">PICKUP SENSOR</text>
            <rect x="790" y="255" width="120" height="75" rx="4" class="bin"/>
            <text x="812" y="355" class="machine-label">DROP AREA</text>
            <rect x="140" y="220" width="38" height="38" rx="3" id="box"/>
            <rect x="830" y="220" width="38" height="38" rx="3" id="dropBox"/>
            <rect x="565" y="60" width="120" height="32" rx="5" class="machine"/>
            <text x="590" y="48" class="small-label">PICKER</text>
            <g id="armGroup">
              <line id="armBeam" x1="0" y1="0" x2="0" y2="76" class="arm"/>
              <g id="gripper" transform="translate(0 76)">
                <path d="M0 0 L-18 17 M0 0 L18 17" class="gripper"/>
              </g>
            </g>
            <text x="710" y="100" class="small-label">Arm pose is inferred from output coils</text>
          </svg>
        </div>
        <div class="telemetry"><span>Conveyor: <b id="conveyorMotion">STOPPED</b></span>
          <span>Picker: <b id="pickerMotion">IDLE</b></span><span id="updated">Waiting for data</span></div>
        <p class="notice">Read-only HMI. The animation estimates motion from Modbus I/O states;
          exact position, box count, and simulator internals are not exposed by this I/O map.
          This is a training display, not a safety-rated or supervisory control system.</p>
      </section>
      <section class="panel">
        <h2>Process inputs</h2>
        <div id="inputs" class="signal-grid"></div>
        <div class="section-label">Actuator outputs</div>
        <div id="coils" class="signal-grid"></div>
      </section>
    </div>
  </main>
  <script>
    const inputNames = ["StartButton", "SafetyDoorClosed", "BoxAtSensor", "RobotDetected", "MovingZ", "Rotating", "BoxPresent"];
    const coilNames = ["Conveyor", "Grab", "ExtendZ", "RotateCW", "RotateCCW"];
    const inputLabels = {
      StartButton: "Start button", SafetyDoorClosed: "Safety door closed",
      BoxAtSensor: "Box at pickup", RobotDetected: "Picker detects box",
      MovingZ: "Picker Z moving", Rotating: "Picker rotating",
      BoxPresent: "Box in process"
    };
    const coilLabels = {
      Conveyor: "Conveyor", Grab: "Gripper", ExtendZ: "Extend Z",
      RotateCW: "Rotate toward drop", RotateCCW: "Rotate toward pickup"
    };
    const inputsRoot = document.getElementById("inputs");
    const coilsRoot = document.getElementById("coils");
    function makeSignals(root, names, labels) {
      for (const name of names) {
        const row = document.createElement("div");
        row.className = "signal";
        const label = document.createElement("span");
        label.className = "signal-name";
        label.textContent = labels[name];
        const value = document.createElement("span");
        value.className = "state off";
        value.id = "signal-" + name;
        value.textContent = "—";
        row.append(label, value);
        root.append(row);
      }
    }
    makeSignals(inputsRoot, inputNames, inputLabels);
    makeSignals(coilsRoot, coilNames, coilLabels);

    let boxX = 140;
    let armAngle = 0;
    let lastFrame = performance.now();
    let lastData = null;
    let lastUpdate = 0;
    function setSignal(name, active, isSafety = false) {
      const element = document.getElementById("signal-" + name);
      element.textContent = active ? "ON" : "OFF";
      element.className = "state " + (isSafety && !active ? "fault" : active ? "on" : "off");
    }
    function applyStatus(data) {
      lastData = data;
      for (const name of inputNames) setSignal(name, data.inputs[name], name === "SafetyDoorClosed");
      for (const name of coilNames) setSignal(name, data.coils[name]);
      const door = document.getElementById("door");
      const isClosed = data.inputs.SafetyDoorClosed;
      door.textContent = isClosed ? "DOOR CLOSED" : "DOOR OPEN";
      door.className = "badge safety" + (isClosed ? "" : " open");
      document.getElementById("conveyorMotion").textContent =
        data.coils.Conveyor ? "RUNNING" : "STOPPED";
      const picker = data.coils.RotateCW ? "ROTATING TO DROP" :
        data.coils.RotateCCW ? "RETURNING" : data.coils.ExtendZ ? "EXTENDING" :
        data.inputs.MovingZ ? "MOVING Z" : data.coils.Grab ? "HOLDING" : "IDLE";
      document.getElementById("pickerMotion").textContent = picker;
      const connection = document.getElementById("connection");
      connection.textContent = data.connected ? "LIVE" : "RECONNECTING";
      connection.className = "badge " + (data.connected ? "live" : "offline");
      document.getElementById("error").textContent = data.error || "";
      document.getElementById("updated").textContent = data.updated_at
        ? "Last update: " + new Date(data.updated_at).toLocaleTimeString()
        : "Waiting for simulator data";
      lastUpdate = performance.now();
    }
    async function refresh() {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) throw new Error("HMI status endpoint returned HTTP " + response.status);
        applyStatus(await response.json());
      } catch (error) {
        document.getElementById("connection").textContent = "HMI SERVER ERROR";
        document.getElementById("connection").className = "badge offline";
        document.getElementById("error").textContent = error.message;
      }
    }
    function animate(now) {
      const dt = Math.min((now - lastFrame) / 1000, 0.1);
      lastFrame = now;
      const data = lastData;
      if (data) {
        const moving = data.coils.Conveyor && data.inputs.BoxPresent &&
          !data.inputs.BoxAtSensor && !data.coils.Grab;
        if (moving) boxX = Math.min(590, boxX + 67.5 * dt);
        if (data.inputs.BoxAtSensor) boxX = 590;
        if (!data.inputs.BoxPresent && !data.inputs.RobotDetected && !data.coils.Grab) boxX = 140;
        if (data.coils.RotateCW) armAngle = Math.min(90, armAngle + 56.25 * dt);
        if (data.coils.RotateCCW) armAngle = Math.max(0, armAngle - 56.25 * dt);
        const hasBox = data.inputs.BoxPresent || data.inputs.RobotDetected || data.coils.Grab;
        const box = document.getElementById("box");
        const held = data.coils.Grab && !data.inputs.BoxAtSensor;
        const heldX = 605 + (armAngle / 90) * 210;
        const heldY = data.coils.ExtendZ ? 150 : 220;
        box.style.display = hasBox ? "block" : "none";
        box.setAttribute("x", held ? heldX : boxX);
        box.setAttribute("y", held && data.coils.ExtendZ ? heldY : 220);
        document.getElementById("dropBox").style.display =
          armAngle >= 88 && !data.coils.Grab ? "block" : "none";
        const armX = held ? heldX + 19 : 625 + (armAngle / 90) * 224;
        const armY = held ? heldY + 19 :
          data.coils.ExtendZ || data.inputs.RobotDetected ? 239 : 168;
        const armDx = armX - 625;
        const armDy = armY - 92;
        const armLength = Math.hypot(armDx, armDy);
        const armAngleDegrees = -Math.atan2(armDx, armDy) * 180 / Math.PI;
        document.getElementById("armBeam").setAttribute("y2", armLength);
        document.getElementById("gripper").setAttribute(
          "transform", "translate(0 " + armLength + ")"
        );
        document.getElementById("armGroup").setAttribute(
          "transform", "translate(625 92) rotate(" + armAngleDegrees + ")"
        );
        if (now - lastUpdate > 2500) {
          document.getElementById("connection").textContent = "STALE DATA";
          document.getElementById("connection").className = "badge offline";
        }
      }
      requestAnimationFrame(animate);
    }
    refresh();
    setInterval(refresh, 100);
    requestAnimationFrame(animate);
  </script>
</body>
</html>
"""


def receive_exactly(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ConnectionError("simulator closed the Modbus connection")
        data.extend(chunk)
    return bytes(data)


class ModbusExceptionError(ValueError):
    def __init__(self, function: int, code: int, address: int, count: int) -> None:
        self.function = function
        self.code = code
        self.address = address
        self.count = count
        super().__init__(
            f"Modbus FC {function} read at address {address}, count {count}: "
            f"exception code {code}"
        )


def read_bits(
    connection: socket.socket,
    transaction_id: int,
    unit_id: int,
    function: int,
    count: int,
) -> list[bool]:
    request_pdu = struct.pack(">BHH", function, 0, count)
    request_header = struct.pack(">HHHB", transaction_id, 0, len(request_pdu) + 1, unit_id)
    connection.sendall(request_header + request_pdu)

    header = receive_exactly(connection, 7)
    response_transaction, protocol, length, response_unit = struct.unpack(">HHHB", header)
    if response_transaction != transaction_id or protocol != 0:
        raise ValueError("invalid Modbus/TCP response header")
    if response_unit != unit_id or not 2 <= length <= 254:
        raise ValueError("unexpected Modbus/TCP unit ID or response length")

    response_pdu = receive_exactly(connection, length - 1)
    if not response_pdu:
        raise ValueError("empty Modbus response")
    if response_pdu[0] == function | 0x80:
        exception_code = response_pdu[1] if len(response_pdu) > 1 else "unknown"
        if not isinstance(exception_code, int):
            raise ValueError(f"Modbus exception code {exception_code}")
        raise ModbusExceptionError(function, exception_code, 0, count)
    expected_bytes = (count + 7) // 8
    if (
        len(response_pdu) != expected_bytes + 2
        or response_pdu[0] != function
        or response_pdu[1] != expected_bytes
    ):
        raise ValueError("unexpected Modbus bit response")

    return [
        bool(response_pdu[2 + index // 8] & (1 << (index % 8)))
        for index in range(count)
    ]


def read_snapshot(
    connection: socket.socket, transaction_id: int, unit_id: int
) -> tuple[dict[str, bool], dict[str, bool], int]:
    requested_count = len(INPUTS)
    while True:
        try:
            input_values = read_bits(
                connection, transaction_id, unit_id, 2, requested_count
            )
            break
        except ModbusExceptionError as error:
            if error.function != 2 or error.code != 2 or requested_count == 1:
                raise
            requested_count -= 1
            transaction_id = (transaction_id + 1) & 0xFFFF
    transaction_id = (transaction_id + 1) & 0xFFFF
    coils = read_bits(connection, transaction_id, unit_id, 1, len(COILS))
    transaction_id = (transaction_id + 1) & 0xFFFF
    input_values.extend([False] * (len(INPUTS) - len(input_values)))
    if requested_count < len(INPUTS):
        input_values[6] = (
            input_values[2] or input_values[3] or coils[0] or coils[1]
        )
    return (
        dict(zip(INPUTS, input_values, strict=True)),
        dict(zip(COILS, coils, strict=True)),
        transaction_id,
    )


class HMIState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] = {
            "connected": False,
            "inputs": {name: False for name in INPUTS},
            "coils": {name: False for name in COILS},
            "updated_at": None,
            "error": "Waiting for the first Modbus response",
        }

    def update(
        self,
        inputs: dict[str, bool] | None = None,
        coils: dict[str, bool] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            if inputs is not None and coils is not None:
                self._snapshot["inputs"] = inputs.copy()
                self._snapshot["coils"] = coils.copy()
                self._snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._snapshot["connected"] = True
                self._snapshot["error"] = None
            else:
                self._snapshot["connected"] = False
                self._snapshot["error"] = error

    def get(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._snapshot,
                "inputs": self._snapshot["inputs"].copy(),
                "coils": self._snapshot["coils"].copy(),
            }


class ModbusPoller(threading.Thread):
    def __init__(
        self,
        state: HMIState,
        host: str,
        port: int,
        unit_id: int,
        interval: float,
        timeout: float,
    ) -> None:
        super().__init__(name="modbus-poller", daemon=True)
        self.state = state
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.interval = interval
        self.timeout = timeout
        self.stop_event = threading.Event()
        self.connection: socket.socket | None = None
        self.transaction_id = 0

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.connection is None:
                    self.connection = socket.create_connection(
                        (self.host, self.port), timeout=self.timeout
                    )
                    self.connection.settimeout(self.timeout)
                inputs, coils, self.transaction_id = read_snapshot(
                    self.connection, self.transaction_id, self.unit_id
                )
                self.state.update(inputs, coils)
                self.stop_event.wait(self.interval)
            except (OSError, ValueError) as error:
                if self.connection is not None:
                    self.connection.close()
                    self.connection = None
                self.state.update(error=str(error))
                self.stop_event.wait(1.0)
            except Exception:
                if self.connection is not None:
                    self.connection.close()
                    self.connection = None
                raise
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def stop(self) -> None:
        self.stop_event.set()


def make_handler(state: HMIState) -> type[BaseHTTPRequestHandler]:
    class HMIRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                content = HMI_PAGE.encode("utf-8")
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/status":
                content = json.dumps(state.get()).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_args: Any) -> None:
            del _format, _args

    return HMIRequestHandler


class HMIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="10.77.20.10", help="simulator IP address")
    parser.add_argument("--port", type=int, default=1502, help="Modbus/TCP port")
    parser.add_argument("--unit-id", type=int, default=1, help="Modbus unit ID")
    parser.add_argument(
        "--interval",
        type=float,
        default=0.1,
        help="seconds between Modbus status polls (default: 0.1)",
    )
    parser.add_argument("--timeout", type=float, default=2.0, help="socket timeout in seconds")
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="HMI listen address; defaults to localhost for local-only access",
    )
    parser.add_argument("--web-port", type=int, default=8080, help="HMI HTTP port")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 1 <= args.web_port <= 65535:
        parser.error("--web-port must be between 1 and 65535")
    if not 0 <= args.unit_id <= 247:
        parser.error("--unit-id must be between 0 and 247")
    if args.interval <= 0 or args.timeout <= 0:
        parser.error("--interval and --timeout must be positive")

    state = HMIState()
    poller = ModbusPoller(
        state, args.host, args.port, args.unit_id, args.interval, args.timeout
    )
    try:
        server = HMIServer((args.web_host, args.web_port), make_handler(state))
    except OSError as error:
        parser.exit(1, f"Cannot start HMI server on {args.web_host}:{args.web_port}: {error}\n")

    poller.start()
    print(
        f"Read-only process HMI: http://{args.web_host}:{args.web_port}/ "
        f"(Modbus/TCP {args.host}:{args.port}, unit ID {args.unit_id})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nHMI stopped.", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        poller.stop()
        poller.join(timeout=args.timeout + 1)
        if poller.is_alive():
            raise RuntimeError("Modbus polling thread did not stop cleanly")


if __name__ == "__main__":
    main()
