#!/usr/bin/env python3
"""Serve an interactive operator HMI for the Option B training controller."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import struct
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from simulator_monitor import read_snapshot


TANK_COILS = {
    "FillValve": 5,
    "Mixer": 6,
    "TransferPump": 7,
    "DrainValve": 8,
}

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#101820">
  <title>Option B Operator HMI</title>
  <style>
    :root { color-scheme: dark; font-family: "Segoe UI", Arial, sans-serif;
      background: #101820; color: #e7eef2; --panel: #1b2932; --line: #40515b;
      --muted: #9eb0ba; --green: #57d69a; --red: #ff6d6d; --amber: #ffc857; }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; }
    header { display: flex; justify-content: space-between; align-items: center;
      gap: 1rem; padding: 1rem clamp(1rem, 3vw, 2.5rem);
      border-bottom: 1px solid var(--line); background: #15212a; }
    h1 { font-size: clamp(1.15rem, 3vw, 1.65rem); margin: 0; }
    h2 { font-size: 1rem; margin: 0 0 .85rem; }
    main { max-width: 1200px; margin: auto; padding: 1.25rem clamp(1rem, 3vw, 2.5rem); }
    .eyebrow, .muted { color: var(--muted); font-size: .8rem; }
    .eyebrow { font-size: .72rem; letter-spacing: .12em; text-transform: uppercase; }
    .badge { border: 1px solid var(--line); border-radius: 999px;
      padding: .4rem .75rem; font-size: .78rem; font-weight: 800; }
    .live { color: var(--green); border-color: #347e62; }
    .offline, .fault { color: var(--red); border-color: #8c4242; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem; margin-top: 1rem; }
    .panel { background: var(--panel); border: 1px solid var(--line);
      border-radius: 12px; padding: 1rem; min-width: 0; }
    .wide { grid-column: 1 / -1; }
    .controls, .tank-controls { display: flex; flex-wrap: wrap; gap: .65rem; }
    button { border: 1px solid var(--line); border-radius: 8px; padding: .65rem .9rem;
      color: #e7eef2; background: #263b47; font-weight: 700; cursor: pointer; }
    button:hover:enabled { filter: brightness(1.2); }
    button:disabled { opacity: .45; cursor: not-allowed; }
    .start { background: #1d6148; border-color: #347e62; }
    .stop { background: #713e3e; border-color: #8c4242; }
    .on { color: var(--green); }
    .off { color: var(--muted); }
    .notice { margin-top: .9rem; color: var(--muted); font-size: .8rem; line-height: 1.5; }
    .error { min-height: 1.25rem; color: var(--red); font-size: .85rem; }
    .signals { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .5rem; }
    .signal { display: flex; justify-content: space-between; gap: .5rem;
      border: 1px solid var(--line); border-radius: 7px; padding: .55rem; font-size: .82rem; }
    .tank-layout { display: flex; align-items: center; gap: 1.25rem; flex-wrap: wrap; }
    .gauge { width: 110px; height: 190px; border: 3px solid #82939b; border-radius: 10px;
      position: relative; overflow: hidden; background: #15212a; }
    .liquid { position: absolute; bottom: 0; width: 100%; height: 25%;
      background: #278ab2; transition: height .3s, background .3s; }
    .gauge-value { position: absolute; inset: 0; display: grid; place-items: center;
      font-weight: 800; text-shadow: 0 1px 5px #101820; }
    .metrics { display: grid; gap: .7rem; }
    .metric { font-size: .9rem; }
    @media (max-width: 700px) { .grid { grid-template-columns: 1fr; }
      .wide { grid-column: auto; } }
    @media (max-width: 460px) { .signals { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <div><div class="eyebrow">Option B · operator station</div>
      <h1>Packaging &amp; Batch Treatment</h1></div>
    <span id="connection" class="badge offline">CONNECTING</span>
  </header>
  <main>
    <p id="error" class="error" role="status"></p>
    <div class="grid">
      <section class="panel">
        <h2>Controller</h2>
        <div class="controls">
          <button id="start" class="start" type="button">Start production</button>
          <button id="stop" class="stop" type="button">Stop production</button>
        </div>
        <p>Mode: <b id="mode">—</b> · State: <b id="state">—</b></p>
        <p id="controllerMessage" class="muted">Waiting for controller status.</p>
        <p class="notice">Stop disables controller outputs on its next scan. An open
          safety door trips the controller; close it and press Start to resume. This is
          a training HMI, not a safety-rated control system.</p>
      </section>
      <section class="panel">
        <h2>Batch tank</h2>
        <div class="tank-layout">
          <div class="gauge"><div id="liquid" class="liquid"></div>
            <div id="level" class="gauge-value">—</div></div>
          <div class="metrics">
            <div class="metric">Temperature: <b id="temperature">—</b></div>
            <div class="metric">Level switches: <b id="tankSwitches">—</b></div>
            <div class="metric">Equipment feedback: <b id="tankFeedback">—</b></div>
          </div>
        </div>
        <p class="notice">Tank operations write dedicated Modbus coils 5–8. Mixing
          and transfer are interlocked in the simulator. The controller owns coils
          0–4; this HMI does not write those outputs.</p>
        <div id="tankControls" class="tank-controls"></div>
      </section>
      <section class="panel wide">
        <h2>RTU signals</h2>
        <div id="inputs" class="signals"></div>
        <p class="muted">Discrete inputs: FC 02 · Outputs: FC 01 · Tank measurements: FC 04</p>
      </section>
    </div>
  </main>
  <script>
    const inputNames = ["StartButton", "SafetyDoorClosed", "BoxAtSensor",
      "RobotDetected", "MovingZ", "Rotating", "BoxPresent", "TankLow",
      "TankHigh", "MixerRunning", "TransferFlow", "TankOverflow"];
    const inputLabels = {
      StartButton: "Legacy start input", SafetyDoorClosed: "Safety door closed",
      BoxAtSensor: "Box at pickup", RobotDetected: "Picker detects box",
      MovingZ: "Picker Z moving", Rotating: "Picker rotating",
      BoxPresent: "Box in process", TankLow: "Tank low", TankHigh: "Tank high",
      MixerRunning: "Mixer running", TransferFlow: "Transfer flow",
      TankOverflow: "Tank overflow"
    };
    const tankNames = ["FillValve", "Mixer", "TransferPump", "DrainValve"];
    const inputsRoot = document.getElementById("inputs");
    const tankRoot = document.getElementById("tankControls");
    for (const name of inputNames) {
      const row = document.createElement("div");
      row.className = "signal";
      const label = document.createElement("span");
      label.textContent = inputLabels[name];
      const value = document.createElement("b");
      value.id = "input-" + name;
      value.textContent = "—";
      row.append(label, value);
      inputsRoot.append(row);
    }
    for (const name of tankNames) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.coil = name;
      button.textContent = name + " ON";
      button.addEventListener("click", () => setTankCoil(name, true));
      tankRoot.append(button);
      const offButton = document.createElement("button");
      offButton.type = "button";
      offButton.dataset.coil = name;
      offButton.textContent = name + " OFF";
      offButton.addEventListener("click", () => setTankCoil(name, false));
      tankRoot.append(offButton);
    }
    async function api(path, method = "GET", body = undefined) {
      const response = await fetch(path, {
        method, cache: "no-store",
        headers: body === undefined ? {} : {"Content-Type": "application/json"},
        body: body === undefined ? undefined : JSON.stringify(body)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "HTTP " + response.status);
      return result;
    }
    async function control(path) {
      document.getElementById("error").textContent = "";
      try { await api(path, "POST"); await refresh(); }
      catch (error) { document.getElementById("error").textContent = error.message; }
    }
    async function setTankCoil(coil, enabled) {
      document.getElementById("error").textContent = "";
      try { await api("/api/tank", "POST", {coil, enabled}); await refresh(); }
      catch (error) { document.getElementById("error").textContent = error.message; }
    }
    function setSignal(name, active) {
      const element = document.getElementById("input-" + name);
      element.textContent = active ? "ON" : "OFF";
      element.className = active ? "on" : "off";
      if (name === "SafetyDoorClosed" && !active) element.className = "fault";
    }
    async function refresh() {
      try {
        const data = await api("/api/status");
        const controller = data.controller;
        const process = data.process;
        document.getElementById("connection").textContent = "LIVE";
        document.getElementById("connection").className = "badge live";
        document.getElementById("mode").textContent =
          controller.run_enabled ? "RUNNING" : "STOPPED";
        document.getElementById("state").textContent = controller.state;
        document.getElementById("controllerMessage").textContent =
          controller.inputs && !controller.inputs.SafetyDoorClosed ?
            "Safety door open — controller is stopped." : "Controller and RTU connected.";
        document.getElementById("start").disabled =
          controller.run_enabled || (controller.inputs && !controller.inputs.SafetyDoorClosed);
        document.getElementById("stop").disabled = !controller.run_enabled;
        for (const name of inputNames) setSignal(name, process.inputs[name]);
        const level = process.process.TankLevelPct;
        document.getElementById("level").textContent = level.toFixed(1) + "%";
        document.getElementById("liquid").style.height = level + "%";
        document.getElementById("liquid").style.background =
          process.inputs.TankOverflow ? "var(--red)" : "#278ab2";
        document.getElementById("temperature").textContent =
          process.process.TankTemperatureC.toFixed(1) + " °C";
        document.getElementById("tankSwitches").textContent =
          (process.inputs.TankLow ? "LOW " : "") +
          (process.inputs.TankHigh ? "HIGH " : "") +
          (process.inputs.TankOverflow ? "OVERFLOW" : "NORMAL");
        document.getElementById("tankFeedback").textContent =
          (process.inputs.MixerRunning ? "MIXING " : "") +
          (process.inputs.TransferFlow ? "TRANSFERRING" : "IDLE");
        for (const name of tankNames) {
          const buttons = [...tankRoot.querySelectorAll("button")]
            .filter(button => button.dataset.coil === name);
          const active = process.coils[name];
          buttons[0].disabled = active;
          buttons[1].disabled = !active;
        }
        document.getElementById("error").textContent = "";
      } catch (error) {
        document.getElementById("connection").textContent = "DISCONNECTED";
        document.getElementById("connection").className = "badge offline";
        document.getElementById("controllerMessage").textContent = "Waiting for services.";
        document.getElementById("error").textContent = error.message;
      }
    }
    document.getElementById("start").addEventListener("click", () => control("/api/controller/start"));
    document.getElementById("stop").addEventListener("click", () => control("/api/controller/stop"));
    refresh();
    setInterval(refresh, 1000);
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


def read_process(
    host: str, port: int, unit_id: int, timeout: float
) -> dict[str, Any]:
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        inputs, coils, process, _ = read_snapshot(connection, 0, unit_id)
    return {
        "inputs": inputs,
        "coils": coils,
        "process": process,
    }


def write_tank_coil(
    host: str,
    port: int,
    unit_id: int,
    timeout: float,
    name: str,
    enabled: bool,
) -> None:
    address = TANK_COILS[name]
    value = 0xFF00 if enabled else 0
    pdu = struct.pack(">BHH", 5, address, value)
    header = struct.pack(">HHHB", 0, 0, len(pdu) + 1, unit_id)
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(header + pdu)
        response_header = receive_exactly(connection, 7)
        transaction, protocol, length, response_unit = struct.unpack(
            ">HHHB", response_header
        )
        if transaction != 0 or protocol != 0 or response_unit != unit_id or length != 6:
            raise ValueError("invalid Modbus/TCP response header")
        response = receive_exactly(connection, length - 1)
        if response != pdu:
            raise ValueError("invalid FC 05 write response")


class ControllerAPIError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def controller_request(
    base_url: str,
    token: str,
    path: str,
    method: str = "GET",
    timeout: float = 2.0,
) -> dict[str, Any]:
    request = Request(
        base_url.rstrip("/") + path,
        method=method,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error", detail)
        except ValueError:
            message = detail
        raise ControllerAPIError(
            error.code, f"Controller API HTTP {error.code}: {message}"
        ) from error
    except URLError as error:
        raise ConnectionError(f"Controller API unavailable: {error.reason}") from error
    if not isinstance(payload, dict):
        raise ValueError("invalid controller API response")
    return payload


def make_handler(
    modbus_host: str,
    modbus_port: int,
    unit_id: int,
    timeout: float,
    controller_api: str,
    token: str,
) -> type[BaseHTTPRequestHandler]:
    class OperatorHMIHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, payload: dict[str, Any] | str, content_type: str) -> None:
            content = (
                payload.encode("utf-8")
                if isinstance(payload, str)
                else json.dumps(payload).encode("utf-8")
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(content)

        def _controller_action(self, action: str) -> None:
            payload = controller_request(
                controller_api, token, f"/api/{action}", "POST", timeout
            )
            self._respond(200, payload, "application/json; charset=utf-8")

        def do_GET(self) -> None:
            if self.path == "/":
                self._respond(200, PAGE, "text/html; charset=utf-8")
                return
            if self.path != "/api/status":
                self._respond(404, {"error": "not found"}, "application/json")
                return
            try:
                status = controller_request(
                    controller_api, token, "/api/status", timeout=timeout
                )
                process = read_process(
                    modbus_host, modbus_port, unit_id, timeout
                )
            except ControllerAPIError as error:
                self._respond(
                    error.status, {"error": str(error)}, "application/json; charset=utf-8"
                )
                return
            except (OSError, ValueError, RuntimeError) as error:
                self._respond(
                    502, {"error": str(error)}, "application/json; charset=utf-8"
                )
                return
            self._respond(
                200,
                {"controller": status, "process": process},
                "application/json; charset=utf-8",
            )

        def do_POST(self) -> None:
            expected_origin = (
                f"http://{self.server.server_address[0]}:"
                f"{self.server.server_address[1]}"
            )
            if self.headers.get("Origin") != expected_origin:
                self._respond(
                    403, {"error": "same-origin request required"},
                    "application/json; charset=utf-8",
                )
                return
            try:
                if self.path == "/api/controller/start":
                    self._controller_action("start")
                    return
                if self.path == "/api/controller/stop":
                    self._controller_action("stop")
                    return
                if self.path != "/api/tank":
                    self._respond(404, {"error": "not found"}, "application/json")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if not 1 <= length <= 256:
                    self._respond(
                        400, {"error": "invalid request size"},
                        "application/json; charset=utf-8",
                    )
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._respond(
                        400, {"error": "request body must be valid JSON"},
                        "application/json; charset=utf-8",
                    )
                    return
                if (
                    not isinstance(payload, dict)
                    or payload.get("coil") not in TANK_COILS
                    or not isinstance(payload.get("enabled"), bool)
                ):
                    self._respond(
                        400, {"error": "invalid tank coil command"},
                        "application/json; charset=utf-8",
                    )
                    return
                write_tank_coil(
                    modbus_host,
                    modbus_port,
                    unit_id,
                    timeout,
                    payload["coil"],
                    payload["enabled"],
                )
            except ControllerAPIError as error:
                self._respond(
                    error.status, {"error": str(error)}, "application/json; charset=utf-8"
                )
                return
            except (OSError, ValueError, RuntimeError) as error:
                self._respond(
                    502, {"error": str(error)}, "application/json; charset=utf-8"
                )
                return
            self._respond(
                200,
                {"coil": payload["coil"], "enabled": payload["enabled"]},
                "application/json; charset=utf-8",
            )

        def log_message(self, _format: str, *_args: object) -> None:
            del _format, _args

    return OperatorHMIHandler


class OperatorHMIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modbus-host", default="10.77.20.10")
    parser.add_argument("--modbus-port", type=int, default=502)
    parser.add_argument("--unit-id", type=int, default=1)
    parser.add_argument(
        "--controller-api",
        default="http://10.77.10.10:8082",
        help="controller operator API base URL",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HMI web bind address")
    parser.add_argument("--port", type=int, default=8083, help="HMI web port")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--control-token",
        default=os.environ.get("FACTORYIO_CONTROL_TOKEN"),
        help="controller API bearer token; may also use FACTORYIO_CONTROL_TOKEN",
    )
    args = parser.parse_args()
    if not 1 <= args.modbus_port <= 65535 or not 1 <= args.port <= 65535:
        parser.error("ports must be between 1 and 65535")
    if not 0 <= args.unit_id <= 247:
        parser.error("--unit-id must be between 0 and 247")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not args.control_token:
        parser.error("set --control-token or FACTORYIO_CONTROL_TOKEN")
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        parser.error("the operator HMI must bind to loopback; use it on the Control VM")

    server = OperatorHMIServer(
        (args.host, args.port),
        make_handler(
            args.modbus_host,
            args.modbus_port,
            args.unit_id,
            args.timeout,
            args.controller_api,
            args.control_token,
        ),
    )
    print(
        f"Option B operator HMI: http://{args.host}:{args.port}/ "
        f"(controller API {args.controller_api}, RTU {args.modbus_host}:{args.modbus_port})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nOperator HMI stopped.", flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
