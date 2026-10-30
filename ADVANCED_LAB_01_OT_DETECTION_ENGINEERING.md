# Advanced Lab 1: Modbus/TCP Traffic Analysis and Detection

## Purpose

Use Wireshark to passively discover and dissect the Modbus/TCP conversations
in the virtual OT/SCADA lab. Then perform the scoped live client test
authorized by the lab assignment and determine whether its activity is
distinguishable from normal controller and HMI traffic.

This lab follows the workflow in the
[Wireshark Modbus/TCP tutorial](https://rodrigocantera.com/en/dissecting-openplc-modbus-tcp-communications-with-wireshark/),
using the lab's port `1502` rather than the common Modbus port `502`.

## Learning objectives

By the end of the lab, students will be able to:

- Establish expected controller-to-simulator and HMI-to-simulator traffic.
- Explain why the HMI creates a separate Modbus connection from Kali.
- Read the MBAP header, function code, address, and quantity in a captured
  request and response.
- Identify useful OT telemetry and its limitations.
- Write detection requirements, test them against observed benign traffic,
  and document false positives and blind spots.

## Required environment

- A working [environment setup](./OT_SCADA_ENVIRONMENT_SETUP.md), using either Option A
  (OpenPLC Runtime) or Option B (Python controller).
- Kali capture access on the routed PLC-LAB and SIM-LAB interfaces.
- The simulator, controller, and HMI.
- Wireshark or tcpdump for packet capture.
- Optional: an instructor-provisioned passive Zeek/Suricata sensor and SIEM
  reachable from the SOC network.

The current simulator does not export structured audit events to a SIEM.
Do not treat its terminal output or the HMI as an existing SIEM integration.
If no SIEM or network sensor is available, complete the analysis using PCAP
files and the simulator/controller console output.

## Safety and scope

This isolated lab is intentionally provided for students to perform the
hands-on tests below against the live simulator. The course assignment
authorizes activity only from the assigned Kali guest to
`10.77.20.10:1502`. The simulator has no Modbus authentication and traffic is
unencrypted. Do not target any other host, port, network, or physical OT
system. Limit writes to the assigned non-safety coil and restore its original
state before resuming the controller.

## Preparation

1. Select one controller option; do not run both controllers simultaneously.
2. Verify the controller reaches `10.77.20.10:1502` through Kali and confirm
   the simulator and HMI are working.
3. Synchronize guest clocks to the instructor-controlled time source.
4. Record the selected option, guest IPs, TCP port, unit ID, capture
   interface, and exercise start time.
5. If using a SIEM, have the instructor confirm approved ingestion paths and
   storage limits before sending logs or captures.

## Exercise

### Part A — Record a normal baseline

Use the simulator's zero-based map when correlating packet addresses with
process state:

| Modbus area | Address | Signal |
| --- | ---: | --- |
| Discrete input | 0 | StartButton |
| Discrete input | 1 | SafetyDoorClosed |
| Discrete input | 2 | BoxAtSensor |
| Discrete input | 3 | RobotDetected |
| Discrete input | 4 | MovingZ |
| Discrete input | 5 | Rotating |
| Coil | 0 | Conveyor |
| Coil | 1 | Grab |
| Coil | 2 | ExtendZ |
| Coil | 3 | RotateCW |
| Coil | 4 | RotateCCW |

1. On Kali, start Wireshark on the PLC-LAB interface before starting the
   selected controller. Use the SIM-LAB interface for the HMI's local
   connection, or capture on both interfaces.
2. Start the controller and let the normal process run. In Wireshark, apply:

   ```text
   tcp.port == 1502
   ```

   To isolate the controller path:

   ```text
   ip.addr == 10.77.10.10 && ip.addr == 10.77.20.10 && tcp.port == 1502
   ```

   To isolate the HMI path:

   ```text
   ip.addr == 10.77.20.1 && ip.addr == 10.77.20.10 && tcp.port == 1502
   ```

3. If Wireshark does not decode port `1502` as Modbus/TCP, select a packet
   and choose **Analyze > Decode As**, then decode that TCP port as Modbus/TCP.
4. Select a controller request and expand the TCP and Modbus/TCP details.
   Record the TCP stream, client/server addresses, MBAP transaction
   identifier, protocol identifier, length, unit identifier, function code,
   starting address, and quantity. Follow the stream or select the response
   and verify that the Modbus response matches the request's transaction
   identifier.
5. Identify which requests use FC 2 (read discrete inputs), FC 5 (write one
   coil), and, if present in the selected capture, FC 15 (write multiple
   coils). The editor configuration in the introductory Option A uses FC 5;
   do not assume every controller sends FC 15.
6. Compare the observed input values with the HMI and simulator console.
   Record the normal client address and polling pattern. The HMI is a
   separate client from Kali (`10.77.20.1`), not part of the controller's
   PLC-LAB flow.
7. Save a PCAP with the selected option and capture interface in its
   filename. Note that Option A's introductory ST sample may only move a box
   to the pickup sensor rather than complete a full pick-and-place cycle.

### Part B — Conduct a live red-team test

Students now actively test the live simulator in the isolated lab. The
authorized source is the assigned Kali guest; the only target is
`10.77.20.10` on TCP `1502`.

1. Pause the selected controller and leave the simulator and capture
   running. This prevents the controller from immediately overwriting a
   student test value.
2. From Kali, use the lab's Modbus client to read the six discrete inputs
   starting at address `0`. Confirm the response against the HMI.
3. Use the assigned non-safety coil from the I/O map and issue one write
   changing its state. Capture the request and response; record the source,
   time, function code, address, requested value, and simulator effect. Do
   not write the safety-door input or repeat the test against other coils.
4. Restore the coil to its recorded original value using the same lab client.
   Confirm the HMI and simulator state, then resume the controller.
5. In Wireshark, identify the test client's TCP stream and compare its
   source, MBAP transaction identifier, function code, address, and response
   with the baseline. Correlate the packet time with HMI and simulator
   evidence.

### Part C — Specify detections

Write vendor-neutral detection requirements before implementing alerts.
Candidates include:

| Detection objective | Evidence to correlate | Tuning question |
| --- | --- | --- |
| New Modbus client | Source/destination pair, TCP port, capture interface | Does the HMI's Kali-originated connection create an expected additional client? |
| Unexpected Modbus destination | Destination address/port and allowed-flow matrix | Is the traffic on the routed controller path or another lab service? |
| Change in polling behavior | Request frequency, function code, response status | What is normal for the selected controller and HMI, and what variation is benign? |
| Failed or malformed protocol exchange | TCP resets, Modbus exception responses, parser events | Can the sensor decode the non-default port `1502` reliably? |
| Process-state transition | Simulator console event and HMI discrete inputs/coils | Which signals are visible, and which details the Modbus map does not expose? |

Use a detection worksheet with: rule name, purpose, data source, expected
normal behavior, alert condition, severity rationale, false-positive risks,
and response action. An alert should identify evidence and uncertainty; it
must not claim an attack solely because a protocol is present.

### Part D — Validate and tune

1. If a SIEM or sensor is available, ingest the baseline through the
   instructor-approved path. Confirm timestamps and endpoint identity.
2. Write detection requirements for a new Modbus client, an unexpected
   destination, unusual polling, and an unexpected output write.
3. Test the requirements against both the baseline and the live
   client activity. Verify that expected controller writes and HMI polling
   do not incorrectly alert as unauthorized control.
4. Record which detections are possible with current data, which need
   structured simulator logs, and which cannot be supported by this simulator.
5. Refine the requirements and document the resulting false positives and
   blind spots.

## Deliverables

Submit:

1. A sanitized network-flow diagram for the selected option.
2. Baseline flow and function-code summary with timestamps.
3. At least three detection specifications from Part C.
4. Validation notes, including one tuning change and its reason.
5. A limitations statement distinguishing packet evidence, console output,
   and HMI state from a complete audit trail.

## Instructor assessment

Assess whether students correctly distinguish the HMI flow from controller
traffic, use evidence from more than one source, describe normal behavior
before proposing alerts, and avoid overstating what the available telemetry
proves. Award no credit for testing outside the assigned range.

## Cleanup

Stop captures, label and store approved evidence in the course location, and
remove temporary sensor/SIEM data according to course retention policy. Leave
the Proxmox network and controller configuration unchanged.
