# Virtual OT/SCADA Cybersecurity Lab

This project provides a small, fully virtual operational technology (OT) and
supervisory control and data acquisition (SCADA) training environment. It
replaces the Factory I/O process scene with a Python conveyor and
pick-and-place simulator that communicates over Modbus/TCP. Students can
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
| [factoryio_simulator.py](./factoryio_simulator.py) | Headless process model and Modbus/TCP server. Models the conveyor, box, picker, safety-door input, and five output coils; process status is shown on request at the simulator prompt. |
| [factoryio_modbus_controller.py](./factoryio_modbus_controller.py) | Optional standalone Python Modbus/TCP client/controller. Runs a pick-and-place sequence without OpenPLC. |
| [simulator_monitor.py](./simulator_monitor.py) | Browser-based, read-only HMI. Polls simulator inputs/coils and displays process signals and inferred motion. |
| [reset_lab_process.py](./reset_lab_process.py) | Resets the running simulator's process state to its startup baseline through a loopback-only endpoint. |
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
| [SIEM_CYBER_RANGE_DESIGN.md](./SIEM_CYBER_RANGE_DESIGN.md) | Proposal for future SIEM integration, OT telemetry, and a segmented virtual-company cyber range. |

## Architecture at a glance

The simulator and selected controller communicate using Modbus/TCP on port
`1502`, unit ID `1`. Proxmox SDN keeps the process simulator and controller
on separate isolated networks; Kali routes and captures the traffic. Kali
also provides the lab's NATed internet egress. The lab guests are not
connected directly to the internet-facing bridge.

Choose one controller path for a run:

- **Option A — OpenPLC Runtime v4:** OpenPLC Runtime reads inputs and writes
  simulator outputs. A separate Control VM runs the OpenPLC Editor and
  deploys the program to the Runtime over the management network.
- **Option B — Python Modbus/TCP:** Run
  [factoryio_modbus_controller.py](./factoryio_modbus_controller.py) in a
  controller container instead of OpenPLC Runtime or Editor.

The [environment setup guide](./OT_SCADA_ENVIRONMENT_SETUP.md) contains the
network diagrams, IP plan, Kali routing/NAT and capture guidance, and
step-by-step setup for both options. Do not run both controllers
simultaneously against the same simulator.

The [simulator HMI](./simulator_monitor.py) is read-only and binds to
localhost by default. Its animation is inferred from I/O; the current
Modbus map does not provide exact box position or box count. It is not a
safety-rated or supervisory control system.

## Process model and Modbus map

The simulator emits a box automatically every five seconds by default.
Controller coils move the box and picker; opening the simulated safety door
pauses process motion. The simulator is a behavioral training model, not a
3D Factory I/O scene or physical-control system.
The conveyor takes about 6.7 seconds to carry a box from the emitter to the
pickup sensor, and a full picker rotation takes about 1.6 seconds so motion is
easy to observe in the HMI.

Addresses are zero-based. Discrete inputs are read with function code 02;
coils are read with FC 01 and can be written with FC 05 or FC 15. The
introductory OpenPLC configuration uses FC 05 for coil writes.

| Address | Modbus area | Signal | Meaning |
| ---: | --- | --- | --- |
| 0 | Discrete input | StartButton | Simulator `start` command pulses the input for 250 ms. |
| 1 | Discrete input | SafetyDoorClosed | `1` means the simulated door is closed. |
| 2 | Discrete input | BoxAtSensor | A box is at the pickup point. |
| 3 | Discrete input | RobotDetected | Picker is down over a box. |
| 4 | Discrete input | MovingZ | Picker Z axis is transitioning. |
| 5 | Discrete input | Rotating | Picker is rotating. |
| 6 | Discrete input | BoxPresent | A box is on the conveyor or held by the picker. |
| 0 | Coil | Conveyor | Advances a box on the conveyor. |
| 1 | Coil | Grab | Picks up or releases a box, depending on process position. |
| 2 | Coil | ExtendZ | Extends the picker; off retracts it. |
| 3 | Coil | RotateCW | Moves the picker toward the drop point. |
| 4 | Coil | RotateCCW | Returns the picker toward the conveyor. |

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
python3 factoryio_simulator.py --host 0.0.0.0 --port 1502 --unit-id 1
```

The prompt accepts `status`, `start`, `box`, `door open`, `door close`,
`auto on`, `auto off`, `reset`, and `quit`. For the complete Proxmox setup,
including required guest firewall access, follow
[OT_SCADA_ENVIRONMENT_SETUP.md](./OT_SCADA_ENVIRONMENT_SETUP.md).

## Reset after an exercise

Stop the selected controller before resetting so it cannot immediately write
outputs again. On the simulator guest, run:

```bash
python3 reset_lab_process.py --confirm
```

This restores the process state to door closed, all coils off, no box,
picker at home, zero removed boxes, automatic emitter on, and cleared
request/event counters. You can also enter `reset` at the simulator prompt.
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
