# Virtual OT/SCADA Cybersecurity Lab

This project provides a small, fully virtual operational technology (OT) and
supervisory control and data acquisition (SCADA) training environment. It
replaces the Factory I/O process scene with a Python packaging-line and
batch-treatment simulator that communicates over Modbus/TCP. Students can
operate the process, inspect network traffic, test the exposed protocol
within the isolated lab, investigate process effects, and practice network
defense.

The project contains runnable Python components, Proxmox environment
instructions, hands-on lab exercises, and a future SIEM/cyber-range design.
The SIEM and enterprise cyber range are proposals only; they are not deployed
by the current code.

## What is in the project

### Runtime components

| Component | Role |
| --- | --- |
| [factoryio_simulator.py](./factoryio_simulator.py) | Process model and Modbus/TCP server. Models the conveyor/picker line and a batch tank with fill, mix, transfer, and drain equipment; prints every valid FC 15 write with named output states. |
| [factoryio_modbus_controller.py](./factoryio_modbus_controller.py) | Option B Python Modbus/TCP client/controller. Runs a pick-and-place sequence without OpenPLC. |
| [optionb_control_hmi.py](./optionb_control_hmi.py) | Interactive, loopback-only Option B operator HMI. Starts/stops the Python controller and operates the simulated tank equipment. |
| [systemd/optionb-control-hmi.service](./systemd/optionb-control-hmi.service) | Optional Linux service unit for deployments that run the Option B HMI on Linux; the lab's Windows Control VM runs it from PowerShell. |
| [OPTION_A_LADDER_RECREATION.st](./OPTION_A_LADDER_RECREATION.st) | Structured Text body reproducing the supplied OpenPLC ladder rungs; variable-table setup and behavioral caveats are in the environment guide. |
| [start_option_b_from_kali.sh](./start_option_b_from_kali.sh) | Starts, stops, restarts, or checks the Option B simulator and controller services remotely from Kali over SSH. |
| [simulator_monitor.py](./simulator_monitor.py) | Browser-based, read-only HMI. Polls simulator inputs, coils, and input registers; displays line signals, inferred motion, tank level, and temperature. |
| [reset_lab_process.py](./reset_lab_process.py) | Starts or resets the simulator process through its loopback-only control endpoint. |
| [test_factoryio_simulator.py](./test_factoryio_simulator.py) | Unit and integration tests for the simulator, controller communication, HMI, and reset behavior. |

See the [Python programs guide](./PYTHON_PROGRAMS_GUIDE.md) for explanations
of each program's structure, important functions and classes, Modbus/TCP and
HTTP data flow, run commands, and test coverage.

### Guides and labs

| Document | What it covers |
| --- | --- |
| [PYTHON_PROGRAMS_GUIDE.md](./PYTHON_PROGRAMS_GUIDE.md) | Source-code walkthrough of every Python program in the project. |
| [OT_SCADA_ENVIRONMENT_SETUP.md](./OT_SCADA_ENVIRONMENT_SETUP.md) | Proxmox topology and environment build instructions, shared Kali gateway/capture/HMI setup, and Option A/B controller procedures. |
| [ADVANCED_LAB_01_OT_DETECTION_ENGINEERING.md](./ADVANCED_LAB_01_OT_DETECTION_ENGINEERING.md) | Wireshark baselining and Modbus/TCP dissection, a live simulator client test, and detection development. |
| [ADVANCED_LAB_02_OT_INCIDENT_RESPONSE.md](./ADVANCED_LAB_02_OT_INCIDENT_RESPONSE.md) | Live, bounded output-change exercise, packet/process correlation, incident timeline, and recovery. |
| [ADVANCED_LAB_03_OT_SEGMENTATION_VALIDATION.md](./ADVANCED_LAB_03_OT_SEGMENTATION_VALIDATION.md) | TCP/Modbus session analysis, approved path tests, and segmentation/containment validation. |
| [ADVANCED_LAB_04_MODBUS_TCP_SESSION_ANALYSIS_SCAPY.md](./ADVANCED_LAB_04_MODBUS_TCP_SESSION_ANALYSIS_SCAPY.md) | Kali-based Wireshark and offline Scapy analysis of Modbus/TCP session state; no forged packet transmission. |
| [SIEM_CYBER_RANGE_DESIGN.md](./SIEM_CYBER_RANGE_DESIGN.md) | Proposal for future SIEM integration, OT telemetry, and a segmented virtual-company cyber range. |

## Architecture at a glance

The simulator and selected controller communicate using Modbus/TCP on the
standard port `502`, unit ID `1`. Proxmox SDN keeps the process simulator and
controller on separate isolated networks; Kali routes and captures the
traffic. Kali also provides the lab's NATed internet egress. The lab guests
are not connected directly to the internet-facing bridge.

Choose one controller path for a run:

- **Option A — OpenPLC Runtime v4:** OpenPLC Runtime reads inputs and writes
  simulator outputs. A separate Control VM runs the OpenPLC Editor and
  deploys the program to the Runtime over the management network.
- **Option B — Python Modbus/TCP:** Run
  [factoryio_modbus_controller.py](./factoryio_modbus_controller.py) in a
  controller container and the Windows Control VM hosting
  [optionb_control_hmi.py](./optionb_control_hmi.py) instead of OpenPLC
  Runtime or Editor.

The Windows Control VM HMI starts and stops the controller's production
sequence through its restricted operator API and can operate the simulator's
batch-tank coils. The controller service itself remains running until stopped
by the service manager on the controller guest. The HMI is not a Linux systemd
service in the default lab deployment; it runs as a Windows local app or task.

The [environment setup guide](./OT_SCADA_ENVIRONMENT_SETUP.md) contains the
network diagrams, IP plan, Kali routing/NAT and capture guidance, and
step-by-step setup for both options. Do not run both controllers
simultaneously against the same simulator.

The [simulator monitor](./simulator_monitor.py) is read-only and binds to
localhost by default. Option B also has a separate interactive operator HMI
on its Windows Control VM for controller Start/Stop and tank controls. Both
are training interfaces, not safety-rated control systems.

## Process model and Modbus map

The simulator emits a box automatically every five seconds by default.
Controller coils move the box and picker. Additional coils operate the batch
tank fill valve, mixer, transfer pump, and drain valve; tank level and
temperature are available as Modbus input registers. Opening the simulated
safety door pauses process motion. The simulator is a behavioral training
model, not a 3D Factory I/O scene or physical-control system.
The conveyor takes about 6.7 seconds to carry a box from the emitter to the
pickup sensor, and a full picker rotation takes about 1.6 seconds so motion is
easy to observe in the HMI.

Addresses are zero-based. Discrete inputs are read with function code 02;
coils are read with FC 01 and can be written with FC 05 or FC 15. The
introductory OpenPLC configuration uses FC 05; the Python controller uses
FC 15 to write all five outputs together.

| Address | Modbus area | Signal | Meaning |
| ---: | --- | --- | --- |
| 0 | Discrete input | StartButton | Simulator `start` command pulses the input for 250 ms; Option B controller start is issued from its operator HMI instead. |
| 1 | Discrete input | SafetyDoorClosed | `1` means the simulated door is closed. |
| 2 | Discrete input | BoxAtSensor | A box is at the pickup point. |
| 3 | Discrete input | RobotDetected | Picker is down over a box. |
| 4 | Discrete input | MovingZ | Picker Z axis is transitioning. |
| 5 | Discrete input | Rotating | Picker is rotating. |
| 6 | Discrete input | BoxPresent | A box is on the conveyor or held by the picker. |
| 7 | Discrete input | TankLow | Tank level is at or below 20%. |
| 8 | Discrete input | TankHigh | Tank level is at or above 80%. |
| 9 | Discrete input | MixerRunning | Mixer is operating; mixing and transfer are interlocked. |
| 10 | Discrete input | TransferFlow | Transfer pump is moving liquid from a non-empty tank. |
| 11 | Discrete input | TankOverflow | Tank level is at or above 95%. |
| 0 | Coil | Conveyor | Advances a box on the conveyor. |
| 1 | Coil | Grab | Picks up or releases a box, depending on process position. |
| 2 | Coil | ExtendZ | Extends the picker; off retracts it. |
| 3 | Coil | RotateCW | Moves the picker toward the drop point. |
| 4 | Coil | RotateCCW | Returns the picker toward the conveyor. |
| 5 | Coil | FillValve | Fills the tank at 6 percentage points per second. |
| 6 | Coil | Mixer | Mixes and warms the tank; inhibited while transfer is requested. |
| 7 | Coil | TransferPump | Transfers liquid out at 4 percentage points per second; inhibited while mixing is requested. |
| 8 | Coil | DrainValve | Drains the tank at 12 percentage points per second; fill and drain cannot run together. |

Input registers use function code 04. Address 0 is tank level in tenths of a
percent (0–1000); address 1 is tank temperature in tenths of a degree Celsius.
The tank starts at 25.0% and 20.0 °C. The browser HMI remains read-only. In
interactive simulator mode, `coil <name> on|off` manually sets an output
(for example, `coil FillValve on`); do not manually drive outputs while a
controller is connected. A quick tank exercise is to turn on `FillValve`
until the level rises above the low switch, turn it off, run `Mixer`, then
turn the mixer off before running `TransferPump`. Watch the live values and
switch states in the HMI.

The simulator supports the Modbus exchanges examined in the
[Wireshark Modbus/TCP tutorial](https://rodrigocantera.com/en/dissecting-openplc-modbus-tcp-communications-with-wireshark/).
Traffic is unencrypted and the simulator does not authenticate clients.
Capture and test only within the assigned isolated lab. The advanced labs
include live client activity against the simulator; packet crafting or
testing systems outside the lab is not part of those exercises.

## Start the Python simulator

The simulator and HMI use only the Python standard library. On the simulator
guest, from the project directory:

```bash
python3 factoryio_simulator.py --host 0.0.0.0 --port 502 --unit-id 1
```

The prompt accepts `status`, `start`, `box`, `door open`, `door close`,
`auto on`, `auto off`, `coil <name> on|off`, `reset`, and `quit`. For the complete Proxmox setup,
including required guest firewall access, follow
[OT_SCADA_ENVIRONMENT_SETUP.md](./OT_SCADA_ENVIRONMENT_SETUP.md).
The `start` command only pulses the legacy Modbus input; Option B production
is started from the operator HMI.

## Reset after an exercise

Stop the selected controller before resetting so it cannot immediately write
outputs again. On the simulator guest, run:

```bash
python3 reset_lab_process.py --confirm
```

This restores the process state to door closed, all coils off, no box,
picker at home, tank level 25.0%, tank temperature 20.0 °C, zero removed
boxes, automatic emitter on, and cleared request/event counters. You can also
enter `reset` at the simulator prompt.
This is a **process-only reset**: it does not restart or reconfigure the
controller, restore a VM snapshot, or change Kali, firewall, or Proxmox
network settings. The setup guide documents the reset details.

## Advanced student labs

The three advanced labs use the live simulator and assigned Kali guest as
their testing scope:

1. [Modbus/TCP traffic analysis and detection](./ADVANCED_LAB_01_OT_DETECTION_ENGINEERING.md)
2. [OT/SCADA incident response](./ADVANCED_LAB_02_OT_INCIDENT_RESPONSE.md)
3. [Modbus/TCP session state and segmentation](./ADVANCED_LAB_03_OT_SEGMENTATION_VALIDATION.md)

The Scapy tutorial's packet-injection topic is addressed through TCP session
state and capture analysis; the labs do not ask students to inject crafted
packets into a live session. See the [SIEM/cyber-range design](./SIEM_CYBER_RANGE_DESIGN.md)
for a proposed future expansion; it does not describe currently deployed
services.

## Tests

Run the simulator and HMI unit/integration tests with Python 3.10 or newer:

```bash
python3 -m unittest -v test_factoryio_simulator.py
```

The tests cover Modbus input/output handling, process behavior, the Python
controller client, the HMI endpoint and poller, and the simulator reset
operation.
