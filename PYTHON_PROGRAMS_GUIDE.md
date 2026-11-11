# Python Programs: Components and Code Guide

This guide explains the Python files in the project: what each program does,
how its code is organized, how data moves between programs, and how to run or
test it. The programs use the Python standard library; no third-party package
is required by the current source.

## How the programs fit together

```text
                    Control VM (Option B)
                   /                   \
      HTTP operator API             Modbus/TCP
                 |                       |
        Python controller  ------------> factoryio_simulator.py
         (Modbus/TCP)                  ^
                                       |
                         simulator_monitor.py (read-only)

OpenPLC Runtime (Option A) also communicates with factoryio_simulator.py
over Modbus/TCP. reset_lab_process.py uses the simulator's loopback-only HTTP
reset endpoint.
```

In Option B, the Control VM HMI commands controller start/stop over its
authenticated operator API and reads/writes the simulated process over
Modbus/TCP. Its tank controls address only tank coils; the controller owns the
line coils. `simulator_monitor.py` remains a separate read-only HMI. The
reset helper sends a local HTTP request to the simulator process; it does not
communicate through Modbus and does not change controller or network
configuration.

The project also includes a lab-only packet-injection helper and a remote
service-control helper. `injectionv2.py` captures a valid Modbus/TCP write to
coils, validates the frame structure, and then sends a crafted `FC 15` packet
with a matching transaction ID to exercise packet-forgery and detection
topics in the isolated lab. It uses Scapy and should only be run against the
training network. `start_option_b_from_kali.sh` is a bash automation wrapper
that starts, stops, or checks the simulator and controller systemd services
from Kali after SSHing to the lab guests.

## `factoryio_simulator.py`

### Purpose and entry point

This is the process model and Modbus/TCP server. It replaces the Factory I/O
scene with an in-memory conveyor/picker line, a batch tank, and a simulated
safety-door input. Run it on the simulator guest:

```bash
python3 factoryio_simulator.py --host 0.0.0.0 --port 502 --unit-id 1
```

The program uses `argparse` for configuration, `socketserver` for Modbus/TCP,
`threading` for concurrent simulation/status/server activity, and
`dataclasses` for process state.
The `--headless` option runs without the interactive terminal prompt and is
used by the systemd service for remote-managed Option B deployments.

### Process state and simulation

`Process` is the central state object. It stores:

- The simulated safety-door state and temporary start-button pulse.
- Box position, whether the picker holds a box, and the removed-box count.
- Automatic-emitter state and timing.
- Nine actuator coil values covering the conveyor/picker line and tank skid.
- Tank level and temperature, plus derived tank-level and equipment inputs.
- Picker extension state, active rotation direction, and transition timing.
- A bounded event queue and Modbus function-code request counts.

A thread lock protects shared state because the Modbus server, simulation
loop, reset handler, and terminal interface can access it concurrently.

`read_inputs()` derives twelve discrete-input values, including `BoxPresent`,
tank-level switches, mixer/transfer feedback, and an overflow switch.
`read_input_registers()` exposes tank level and temperature in tenths of a
unit. The default conveyor speed takes about 6.7 seconds to reach the pickup
sensor; a full picker rotation takes about 1.6 seconds.
`read_coils()` and `write_coils()` access the nine outputs; writes also record
output-change events. `step()` advances the process by one simulation tick. It
handles automatic box emission, pauses process motion while the safety door
is open, moves the picker, and advances the conveyor and tank equipment. Tank
fill/drain rates and the mixer/transfer interlock are modeled in the same
process step. The automatic emitter waits until a box is not on the conveyor
and is not being held by the picker before releasing the next box. The
`run_simulation()` loop calls it about every 50 ms.

`reset()` restores the in-memory process to its startup baseline: door closed,
no active start pulse, no box, no held box, zero removed count, automatic
emitter enabled, all coils off, picker retracted/home, and cleared event and
request counters. It also restarts the automatic-emitter timer.

The display methods `status()` and `live_status()` format the current
signals and process state for the terminal. Exact box position and picker
angle remain internal; tank level and temperature are exposed at tenths
resolution through the input-register map.

### Modbus/TCP protocol code

`process_pdu()` handles Modbus function requests and returns response
payloads:

- FC 01 reads output coils.
- FC 02 reads discrete inputs.
- FC 04 reads tank level and temperature input registers.
- FC 05 writes one coil.
- FC 15 writes multiple coils.

It checks request shape and address/count bounds and returns Modbus exception
responses for unsupported functions or invalid requests. `ModbusHandler`
reads the Modbus/TCP header and payload from each TCP connection, checks the
protocol identifier and length, verifies the unit ID, calls `process_pdu()`,
and echoes the transaction identifier in the response. The server logs each
Modbus client connection and disconnection. Each valid FC 15 request prints
its transaction ID, starting address, quantity, and named requested output
states to the simulator terminal, even when the requested values match the
current outputs.

`ModbusServer` hosts these handlers on the configured address and port. The
source and documented lab default Modbus port is `502`.

### Terminal and reset HTTP interfaces

`run_cli()` accepts `start`, `box`, `door open`, `door close`, `auto on`,
`auto off`, `coil <name> on|off`, `reset`, `status`, `help`, and `quit`.
Named coil commands manually operate any output, including the tank equipment.
Process events are retained in memory for the model but are not automatically
printed. Valid FC 15 output-write requests are printed as they arrive. The
`status` command prints a process snapshot only when requested.

`ResetServer` is a separate HTTP server bound specifically to
`127.0.0.1`, default port `8081`. Its `GET /health` checks readiness;
`POST /start` pulses the legacy `StartButton` input, and `POST /reset` calls
`Process.reset()`.
Successful requests return HTTP 204. Because the server binds to loopback, it
is intended to be called on the simulator guest, not directly across the lab
network. The legacy start pulse does not start the Option B controller; use
the Control VM operator HMI.

`main()` parses and validates command-line values, creates the process and
both servers, starts the Modbus server, simulation loop, and reset listener,
then runs the interactive terminal unless `--headless` is set. In headless
mode it waits for a termination signal. On exit it shuts down both servers.

## `factoryio_modbus_controller.py`

### Purpose and entry point

This is Option B: a standalone Modbus/TCP controller that communicates with
the simulator and performs a pick-and-place sequence without OpenPLC.

```bash
python3 factoryio_modbus_controller.py --host 10.77.20.10 --port 502 --unit-id 1
```

It uses Python's standard-library networking, HTTP, threading, and JSON
modules; no third-party package is required.

### Modbus client

`receive_exactly()` reads the requested number of bytes from a TCP stream,
which may deliver data in partial chunks. `ModbusTCPClient` manages the
connection, transaction counter, and request/response exchanges.

`_exchange()` constructs a Modbus/TCP MBAP header, sends the header and PDU,
then verifies transaction ID, protocol ID, unit ID, response length, and
function code. It recognizes Modbus exception responses and closes the
connection when transport or validation errors occur.

`read_inputs()` uses FC 02 to read the six controller input bits. The
controller starts disabled; the Control VM operator HMI enables or disables
the production sequence through the controller's HTTP API. The legacy
`StartButton` discrete input is still readable but does not enable Option B.
`write_coils()` uses FC 15 to send the complete
five-coil conveyor/picker output state in one request and validates the
response address and quantity. `write_all_coils_off()` uses this same FC 15
operation to establish a known state for the controller-managed outputs on
startup and during normal shutdown.
`Controller.set_outputs()` sends a request only when at least one output
changes, keeping the five actuator values synchronized as a single update.

### Controller state machine

`Controller.scan()` reads the inputs and computes outputs for each scan. The
operator API enables the run; the controller uses these states:

| State | Behavior |
| --- | --- |
| `STOPPED` | Outputs stay off until the Control VM operator presses Start. |
| `SAFETY_STOP` | Outputs stay off after the door opens; close it and press Start to resume. |
| `FEED` | Conveyor advances a box until `BoxAtSensor` is true. |
| `LOWER` | Extends the picker; waits for `RobotDetected`. |
| `PICK` | Closes/holds the gripper and waits for the detection signal to clear. |
| `RETRACT` | Retracts the picker and waits for the Z-motion transition to finish. |
| `ROTATE_TO_DROP` | Rotates toward the drop point and waits for rotation to finish. |
| `RELEASE` | Pauses briefly to release the box. |
| `ROTATE_TO_PICKUP` | Rotates back and returns to `FEED`. |

If `SafetyDoorClosed` is false, `reset_for_safety()` turns outputs off and
sets `SAFETY_STOP`; after the door closes, the operator must press Start
again. The code observes a simulated input; it is not a certified safety
controller.

`run()` connects, initializes all coils off, repeatedly scans at the
configured polling interval, and turns coils off/closes the socket in a
`finally` block. `ControllerControlServer` exposes token-authenticated
`GET /api/status`, `POST /api/start`, and `POST /api/stop` routes. The API
defaults to loopback; a non-loopback bind requires a bearer token. `main()`
validates command-line settings and reports connection/protocol failures
explicitly.

## `optionb_control_hmi.py`

This is the interactive Option B operator station intended for the Control
VM. It binds to loopback on port `8083`, polls controller/API status and the
simulator Modbus map, and displays the production state, RTU signals, and tank
telemetry. Its Start/Stop buttons control the Python controller's run-enable
state. Tank buttons write only FC 05 coils 5–8; they do not write the
controller-managed line outputs at addresses 0–4.

The HMI acts as a local web proxy: its server-side requests use a bearer token
to call the controller API and a separate Modbus/TCP connection for plant
telemetry and tank coil commands. The token is read from
`FACTORYIO_CONTROL_TOKEN`; it is never sent to the browser. The HMI is bound
to loopback by default and rejects non-loopback web binds. It is an operator
training interface, not a safety-rated controller or physical-process HMI.

## `simulator_monitor.py`

### Purpose and entry point

This program serves the browser-based read-only HMI and polls the simulator.
It has two connections/surfaces:

1. A Modbus/TCP client connection from Kali to the simulator.
2. An HTTP server for the HMI browser.

```bash
python3 simulator_monitor.py --host 10.77.20.10 --port 502 --unit-id 1
```

The HTTP server defaults to `127.0.0.1:8080`. `--web-host` can bind it to a
specific reachable interface when needed; avoid binding an unauthenticated
display to untrusted networks.

### Reading and storing signals

`receive_exactly()` reads complete TCP frames. `read_bits()` sends a Modbus
bit-read request, checks the MBAP header and response function, detects
Modbus exception responses, validates the byte count, and unpacks returned
bits. `read_snapshot()` reads FC 02 discrete inputs and FC 01 coils and maps
them by name. If an older simulator rejects input address 6, it retries with
the original six-input map and infers `BoxPresent` from available sensor
inputs and conveyor/gripper coils.

`HMIState` protects a shared snapshot with a thread lock. It stores
connection status, input/output dictionaries, the UTC time of the last good
poll, and an error string. `get()` returns copies of the signal dictionaries
so request handlers cannot mutate the shared state.

`ModbusPoller` is a daemon thread that connects to the simulator, obtains
snapshots every 100 ms by default (configurable with `--interval`), and
updates `HMIState`. Socket or Modbus validation errors close the connection, mark the HMI disconnected,
and trigger a retry after a delay. Unexpected exceptions are re-raised
instead of being silently treated as a normal reconnect.

### HTTP API and browser page

`HMI_PAGE` contains the HTML, CSS, SVG process diagram, and JavaScript for
displaying the inputs, coils, connection state, and approximate process
motion. `BoxPresent` prevents the animation from showing a box before one
exists. The browser refreshes displayed status every 100 ms, while
`requestAnimationFrame` continuously renders the process animation. Exact
process position and box count are not available through the current Modbus
map. Because a new box may be emitted before the
next HMI poll after a drop, the animation also resets its conveyor position
when the gripper releases a box at the drop point.
The Z-axis animation interpolates the `ExtendZ` coil over the simulator's
750 ms actuator transition with easing, moving a held box down to pick and
up during retraction rather than switching its displayed height immediately.
While the gripper output is on, the box remains attached to the gripper even
if the pickup sensor input changes. If rotation begins while a box is held,
the animation continues toward the retracted height, and the picker status
continues to show retraction until the box is visibly raised. This avoids
showing the carried box at the drop platform before it is released. During the
last part of the swing, the held box lowers onto the drop platform; its final
position is centered over the platform before the gripper releases it.

The standalone controller retains its 50 ms scan interval by default. This is
the control loop, not display polling; increasing it could delay input and
safety-door response or miss brief input changes. The controller starts
disabled and no longer uses the simulator's legacy `StartButton` input.
`request_start()` and `request_stop()` are driven by the authenticated
operator API; opening the safety door disables the run and requires a new
operator Start after the door is closed.

`make_handler()` creates an HTTP request handler with two GET routes:

- `/` serves the HMI page.
- `/api/status` returns the current state as JSON.

Other paths return 404. This remains a read-only display and does not control
process outputs. `main()` validates options, starts the Modbus poller and
HTTP server, and stops both cleanly on Ctrl+C.

## `reset_lab_process.py`

This is a small command-line client for the simulator's loopback-only process
control HTTP endpoint. It does not connect to Modbus or stop the controller
automatically.

```bash
python3 reset_lab_process.py --confirm
```

`--confirm` is required as an explicit operator acknowledgement; stop the
selected controller before running it to prevent the controller from
immediately rewriting outputs. The helper sends `POST /reset` to
`127.0.0.1:8081` (or the configured `--port`) and expects HTTP 204.
For headless service deployments, `--start` waits for the local health check
and sends `POST /start` to pulse the simulated StartButton. Connection
failures are reported with a nonzero exit status. These actions change only
simulator process state; neither resets Proxmox nor changes guest, controller,
firewall, or network configuration.

## `test_factoryio_simulator.py`

This file uses Python's built-in `unittest` framework. Each
`ModbusProcessTests` test creates an isolated in-memory `Process` instance
with automatic box emission disabled. The tests cover:

- FC 01/02 reads and FC 05/15 writes, including address validation.
- Process motion, safety-door pausing, event output, and reset-to-startup
  state.
- Modbus/TCP framing and the standalone controller's client/state behavior.
- Controller operator start/stop behavior and operator HMI controller/tank
  endpoints.
- HMI snapshot decoding, HTML/JSON endpoints, and polling-thread updates.
- The reset helper sending a request to a temporary loopback reset server.

Run the suite from the project directory:

```bash
python3 -m unittest -v test_factoryio_simulator.py
```

## Supporting utility scripts

`injectionv2.py` is a Scapy-based Modbus/TCP packet-capture and injection
utility used during the lab exercises that inspect forged write requests.
The script listens for a valid coil-write exchange, confirms the Modbus frame
fields and coil count, and then transmits a crafted FC 15 packet with the same
TCP metadata. This is a training-focused helper for lab traffic analysis and
packet validation; it is not a production component and should never be used
outside the isolated OT lab.

`start_option_b_from_kali.sh` is a convenience wrapper for starting and checking
Option B services from a Kali control host. It uses SSH to call
`systemctl` on the simulator and controller guests, allowing a single command
to bring up or inspect the Controller and Simulator services without explicit
remote shell steps.

## Suggested reading order

1. Read the [project README](./README.md) for the architecture overview.
2. Follow [OT_SCADA_ENVIRONMENT_SETUP.md](./OT_SCADA_ENVIRONMENT_SETUP.md) to
   build the environment.
3. Use this guide while reading the source files.
4. Run the tests and then work through the
   [advanced labs](./README.md#advanced-student-labs).
