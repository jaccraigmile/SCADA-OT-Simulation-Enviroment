# Advanced Lab 2: OT/SCADA Incident Response and Process-Aware Forensics

## Purpose

Practice a detailed Modbus/TCP investigation after a simulated unauthorized
control action. Students will identify the client and requested coil change
in Wireshark, correlate it with the process effect, and perform a safe,
instructor-directed recovery.

This is a live purple-team exercise in the isolated lab. Students perform a
bounded control action against the simulator, then investigate its process
impact. The exercise does not involve physical equipment or traffic outside
the lab. It follows the traffic-analysis
workflow of the
[Wireshark Modbus/TCP tutorial](https://rodrigocantera.com/en/dissecting-openplc-modbus-tcp-communications-with-wireshark/).

## Learning objectives

- Establish an OT incident timeline from independent data sources.
- Distinguish process impact from its possible cause.
- Use a safe-state response and a documented recovery plan.
- Identify missing evidence and communicate uncertainty to an incident team.

## Required environment

- A working [environment setup](./OT_SCADA_ENVIRONMENT_SETUP.md) with one controller
  option, the simulator, Kali capture, and browser HMI.
- A capture started on Kali before the exercise.
- Instructor-approved worksheet or case record with a synchronized clock.
- Optional SOC/SIEM workstation. A SIEM is not required.

The HMI is read-only and not safety-rated. It does not replace controller
interlocks, physical safety systems, or an operator's safety procedures.

## Rules of engagement

- Run only on the assigned simulator and isolated lab networks.
- The lab assignment authorizes the listed activity against the simulator;
  the instructor establishes the starting state and recovery procedure.
- Use only the assigned Kali guest and simulator at `10.77.20.10:1502`.
- Use only the one non-safety output coil selected for this exercise. Never
  write safety inputs, disable safety logic, or change firewall policy.
- If the simulator or controller behaves unexpectedly, stop the exercise
  using the instructor's established procedure; do not experiment on a live
  physical process.

## Instructor setup

1. Select Option A or Option B and verify normal controller operation.
   For Option A, confirm the deployed program's door-open behavior before
   class; for Option B, use the documented controller behavior.
2. Verify the HMI reports connected and that its live safety-door and output
   indicators agree with the simulator.
3. Start Wireshark on Kali's PLC-LAB interface and use the display filter
   `tcp.port == 1502`. Capture on SIM-LAB as well if students will correlate
   the HMI connection.
4. Select one non-safety output coil for the hands-on test and confirm its
   expected process effect. Provide the coil address and original value to
   students. Pause the controller before the test to avoid competing writes.
5. Confirm the restore procedure and instructor contact method. Students
   conduct the test during the lab and restore the output before the
   controller resumes.

## Exercise

### Part A — Establish the baseline

1. Students record the selected option, relevant guest addresses, capture
   interfaces, TCP port `1502`, and current process state.
2. Observe the normal behavior supported by the selected controller
   configuration. Record controller state, simulator console events, HMI
   inputs/outputs, and Modbus traffic timestamps. The introductory Option A
   sample may only advance a box to the pickup sensor.
3. In Wireshark, isolate the controller stream and one HMI stream. For each,
   record the TCP initiator, source/destination, unit identifier, transaction
   identifier, function code, and observed poll interval. Confirm that the
   HMI's Kali address `10.77.20.1` is a distinct client.
4. Define the expected safe response to `SafetyDoorClosed = 0` using the
   selected controller's documented behavior. Do not change the safety
   input as part of the red-team action.

### Part B — Perform and investigate the live control test

With Wireshark capturing and the controller paused, students conduct the
assigned live test against the simulator. The goal is to demonstrate how an
authorized client can change an unauthenticated Modbus output and how
defenders can detect and investigate that activity.

Students should:

1. From Kali, use the lab's Modbus client to issue exactly one write to the
   assigned non-safety coil. Record its zero-based coil address and requested
   value. Do not craft or inject packets, target other addresses, or repeat
   the write.
2. Find the test client's TCP stream in Wireshark. Expand the Modbus/TCP
   request and response. Record the MBAP transaction identifier, unit
   identifier, function code, coil address, requested value, and response.
   Confirm the response transaction identifier corresponds to the request.
3. Correlate the packet timestamp with the HMI's output state and simulator
   console event. Distinguish the test client from the controller and Kali
   HMI connections; an IP address alone does not identify a person.
4. Check whether any unsafe or unexpected process behavior occurred. If it
   did, stop the test and follow the preapproved recovery procedure; do not
   attempt additional writes.
5. Construct a timeline with at least:
   - Last known normal state.
   - Authorized test action and assigned source.
   - First observation of the changed process/output state.
   - Controller response, if the controller was resumed by the instructor.
   - HMI observation and any relevant simulator console message.
   - Student recovery and return to normal operation.
6. State what the evidence establishes, what it suggests, and what it cannot
   establish. For example, a packet capture can show observed protocol
   exchanges but does not by itself identify a human actor.

### Part C — Restore and verify

1. Restore the tested output coil to its recorded original value using the
   lab Modbus client and the assigned procedure.
2. Confirm the HMI reflects the restored state. Have the instructor verify
   process conditions before restarting the controller.
3. Stop the controller normally if the instructor requests it. Preserve
   approved evidence before clearing or restarting any component.
4. Confirm the process has returned to the known-good state and report any
   mismatch to the instructor.

## Deliverables

Submit an incident record containing:

- A timestamped event timeline and source for each observation.
- A simple process/network diagram showing the observed communication path.
- Impact assessment: affected process state, outputs, and duration.
- Containment and recovery actions, who authorized them, and verification.
- Alternative explanations and evidence needed to distinguish them.
- A short after-action report with two recommended monitoring or procedure
  improvements.

## Instructor assessment

Evaluate evidence handling, correct interpretation of the safety input,
recognition that the HMI is not a control or safety authority, preservation
of uncertainty, and adherence to the stop/recovery procedure. Students must
not attribute intent or actor identity without supporting evidence.

## Cleanup

Stop and save the capture according to course policy. Restore the simulator,
controller, and HMI to the known-good baseline and verify the process is idle
or in its instructor-designated starting state.
