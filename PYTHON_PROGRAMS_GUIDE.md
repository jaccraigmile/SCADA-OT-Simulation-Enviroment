# Python Programs: Components and Code Guide

This guide explains the Python files in the project: what each program does,
how its code is organized, how data moves between programs, and how to run or
test it. The programs use the Python standard library; no third-party package
is required by the current source.

## How the programs fit together

```text
OpenPLC Runtime (Option A)  OR  Python controller (Option B)
                   | Modbus/TCP client
                   v
          factoryio_simulator.py
             ^             ^
             | Modbus/TCP  | loopback-only HTTP reset
             | read-only   |
       simulator_monitor.py  reset_lab_process.py
             |
        Browser HMI
```

In the Proxmox environment, the selected controller reaches the simulator
over routed Modbus/TCP through Kali. The HMI is a separate read-only Modbus
client. The reset helper sends a local HTTP request to the simulator process;
it does not communicate through Modbus and does not change the controller,
firewall, guest networking, or Proxmox configuration.

## `factoryio_simulator.py`

### Purpose and entry point

This is the process model and Modbus/TCP server. It replaces the Factory I/O
scene with an in-memory conveyor, box, picker, and simulated safety-door
input. Run it on the simulator guest:

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
- Five actuator coil values.
- Picker extension state, active rotation direction, and transition timing.
- A bounded event queue and Modbus function-code request counts.

A thread lock protects shared state because the Modbus server, simulation
loop, reset handler, and terminal interface can access it concurrently.

`read_inputs()` derives seven discrete-input values from this state, including
`BoxPresent` so the HMI can distinguish an actual box from an energized
conveyor with no box. The default conveyor speed takes about 6.7 seconds to
reach the pickup sensor; a full picker rotation takes about 1.6 seconds.
`read_coils()` and `write_coils()` access the five output values; writes also
record output-change events. `step()` advances the process by one simulation
tick. It handles automatic box emission, pauses physical-model motion while
the safety door is open, moves the picker, picks/releases boxes, and advances
the conveyor. The `run_simulation()` loop calls it about every 50 ms.

`reset()` restores the in-memory process to its startup baseline: door closed,
no active start pulse, no box, no held box, zero removed count, automatic
emitter enabled, all coils off, picker retracted/home, and cleared event and
request counters. It also restarts the automatic-emitter timer.

The display methods `status()` and `live_status()` format the current
signals and process state for the terminal. The model's continuous values,
such as exact position and angle, are internal; they are not exposed in the
Modbus map.

### Modbus/TCP protocol code

`process_pdu()` handles Modbus function requests and returns response
payloads:

- FC 01 reads output coils.
- FC 02 reads discrete inputs.
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
`auto off`, `reset`, `status`, `help`, and `quit`. Process events are retained
in memory for the model but are not automatically printed. Valid FC 15
output-write requests are printed as they arrive. The `status` command prints
a process snapshot only when requested.

`ResetServer` is a separate HTTP server bound specifically to
`127.0.0.1`, default port `8081`. Its `GET /health` checks readiness;
`POST /start` pulses `StartButton`, and `POST /reset` calls `Process.reset()`.
Successful requests return HTTP 204. Because the server binds to loopback, it
is intended to be called on the simulator guest, not directly across the lab
network. The Kali Option B launcher invokes the start helper over SSH.

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

It uses only `argparse`, `socket`, `struct`, `time`, and `dataclasses`.

### Modbus client

`receive_exactly()` reads the requested number of bytes from a TCP stream,
which may deliver data in partial chunks. `ModbusTCPClient` manages the
connection, transaction counter, and request/response exchanges.

`_exchange()` constructs a Modbus/TCP MBAP header, sends the header and PDU,
then verifies transaction ID, protocol ID, unit ID, response length, and
function code. It recognizes Modbus exception responses and closes the
connection when transport or validation errors occur.

`read_inputs()` uses FC 02 to read the six controller input bits. The HMI
also reads the seventh `BoxPresent` input. `write_coils()` uses FC 15 to send
the complete five-coil output state in one request and validates the response
address and quantity. `write_all_coils_off()` uses this same FC 15 operation
to establish a known output state on startup and during normal shutdown.
`Controller.set_outputs()` sends a request only when at least one output
changes, keeping the five actuator values synchronized as a single update.

### Controller state machine

`Controller.scan()` reads the inputs and computes outputs for each scan. The
controller uses these states:

| State | Behavior |
| --- | --- |
| `WAIT_START` | Outputs stay off until the simulator's start pulse is seen. |
| `FEED` | Conveyor advances a box until `BoxAtSensor` is true. |
| `LOWER` | Extends the picker; waits for `RobotDetected`. |
| `PICK` | Closes/holds the gripper and waits for the detection signal to clear. |
| `RETRACT` | Retracts the picker and waits for the Z-motion transition to finish. |
| `ROTATE_TO_DROP` | Rotates toward the drop point and waits for rotation to finish. |
| `RELEASE` | Pauses briefly to release the box. |
| `ROTATE_TO_PICKUP` | Rotates back and returns to `FEED`. |

If `SafetyDoorClosed` is false, `reset_for_safety()` turns outputs off and
returns the controller to `WAIT_START`. The code observes a simulated input;
it is not a certified safety controller.

`run()` connects, initializes all coils off, repeatedly scans at the
configured polling interval, and turns coils off/closes the socket in a
`finally` block. `main()` validates command-line settings and reports
connection/protocol failures explicitly.

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

The standalone controller retains its 50 ms scan interval by default. This is
the control loop, not display polling; increasing it could delay input and
safety-door response or miss brief input changes.

`make_handler()` creates an HTTP request handler with two GET routes:

- `/` serves the HMI page.
- `/api/status` returns the current state as JSON.

Other paths return 404. The HMI has no write route and does not control
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
- HMI snapshot decoding, HTML/JSON endpoints, and polling-thread updates.
- The reset helper sending a request to a temporary loopback reset server.

Run the suite from the project directory:

```bash
python3 -m unittest -v test_factoryio_simulator.py
```

## Suggested reading order

1. Read the [project README](./README.md) for the architecture overview.
2. Follow [OT_SCADA_ENVIRONMENT_SETUP.md](./OT_SCADA_ENVIRONMENT_SETUP.md) to
   build the environment.
3. Use this guide while reading the source files.
4. Run the tests and then work through the
   [advanced labs](./README.md#advanced-student-labs).
