# Advanced Lab 3: Modbus/TCP Session State and Segmentation

## Purpose

Investigate how TCP session state and network segmentation affect Modbus/TCP
access to the virtual OT/SCADA process. Students test a small, approved set
of paths, examine TCP and Modbus/TCP evidence in Wireshark, and assess the
security limits of an unauthenticated protocol.

This is a live red-team/blue-team policy-validation lab in the isolated
Proxmox environment. Students test the assigned paths from Kali, then assess
and improve the defensive boundary. The lab discusses packet-injection risks
from the
[Scapy Modbus/TCP tutorial](https://rodrigocantera.com/en/modbus-tcp-packet-injection-with-scapy/),
but does not transmit crafted packets. A valid Modbus payload alone does not
bypass TCP session checks; the simulator uses a normal TCP socket and does not
provide an injection bypass.

## Learning objectives

- Explain the trust boundaries in the selected Option A or B topology.
- Distinguish a Modbus transaction identifier from TCP sequence and
  acknowledgment numbers.
- Explain why observing or constructing a Modbus request does not, by
  itself, make it an accepted TCP-session payload.
- Translate business and process requirements into narrowly scoped
  network-flow rules.
- Validate both permitted and prohibited communication without relying on
  assumptions about a switched SDN segment.
- Plan safe containment that preserves instructor and Proxmox management.

## Required environment

- A working [environment setup](./OT_SCADA_ENVIRONMENT_SETUP.md), using one controller
  option.
- Instructor access to Kali's gateway/firewall configuration and Proxmox.
- A designated test source guest and the assigned list of exact destination
  addresses and ports.
- A maintenance window or isolated clone for any policy changes.
- A saved, instructor-approved firewall configuration and recovery method.
- Optional: a SOC workstation or passive capture sensor.

The lab assignment authorizes the listed tests against the provided VMs and
VNets. Students may change firewall policy only on an isolated lab gateway
clone or when the instructor has designated the gateway as student-managed.
Do not change Proxmox host management, the physical LAN, or the
internet-facing uplink policy.

## Topology and expected paths

Use the addresses in the environment setup guide unless the instructor provides a
different IP plan.

### Option A — OpenPLC Runtime v4

- Control VM `10.77.0.20` communicates with Runtime management
  `10.77.0.10` on `MGMT`, only on ports required by the deployed Runtime
  v4 workflow.
- Runtime data interface `10.77.10.10` initiates Modbus/TCP to simulator
  `10.77.20.10:1502` through Kali.
- Kali HMI polls the simulator locally from Kali's SIM-LAB address
  `10.77.20.1`.
- The Control VM does not need a direct Modbus path to the simulator.

### Option B — Python Modbus/TCP controller

- Controller `10.77.10.10` initiates Modbus/TCP to simulator
  `10.77.20.10:1502` through Kali.
- Kali HMI polls the simulator locally from `10.77.20.1`.
- There is no OpenPLC Runtime, Editor Control VM, or MGMT network for this
  option.

### Shared boundary requirements

- Keep PLC-LAB and SIM-LAB as separate VNets; route between them through
  Kali or the instructor-designated firewall.
- Permit only the required controller-to-simulator Modbus flow and its
  established replies.
- Permit only explicitly required management and HMI access.
- Block new internet-originated connections to lab guests.
- Do not expose the simulator or controller services directly to the
  internet-facing bridge.

## Exercise

### Part A — Build the allowed-flow matrix

Document source zone, destination zone, initiator, protocol/port, purpose,
expected decision, and evidence source. Include at least the following
cases:

| Test case | Expected result |
| --- | --- |
| Selected controller to simulator on TCP `1502` | Allowed through the designated gateway; capture confirms the routed path. |
| Established simulator reply to the controller | Allowed as return traffic for the permitted flow. |
| Kali HMI to simulator on TCP `1502` | Allowed locally on SIM-LAB; distinguish this connection from controller traffic. |
| Unrelated guest to simulator Modbus service | Denied unless explicitly authorized by the instructor. |
| Simulator initiating a new connection to the controller | Denied unless a documented lab requirement says otherwise. |
| New connection from the internet uplink to a lab guest | Denied. |
| Option A Control VM to Runtime management | Allowed only on deployment-required management ports. |
| Option B Control VM/Editor management path | Not applicable; those components are absent in Option B. |

If a path is not represented in the selected topology, mark it **not
applicable** rather than inventing an endpoint.

### Part B — Verify the baseline policy

1. Use the test endpoints in the matrix and the selected topology. The
   authorized source is the assigned Kali guest; the simulator endpoint is
   `10.77.20.10:1502`. Keep each check within the listed source, destination,
   and port.
2. On Kali, start Wireshark on the interface through which the test path
   should pass. Apply `tcp.port == 1502`. If needed, use **Analyze > Decode
   As** to decode port `1502` as Modbus/TCP.
3. Confirm the normal controller-to-simulator connection with the
   environment setup guide's route and TCP reachability checks.
4. From the designated test guest, check only the assigned simulator address
   and TCP port. Record the route, whether TCP connects, and the corresponding
   packets at the Kali capture point. Do not enumerate other hosts or ports.
5. In the controller capture, use **Analyze > Follow > TCP Stream** to review
   the connection. Identify the TCP handshake and note the
   sequence/acknowledgment fields on a request and its response. Separately
   identify the Modbus MBAP transaction identifier. Explain why these are
   different protocol-layer values and why a transaction identifier is not
   an authentication mechanism.
6. For each prohibited path in the matrix, perform one connection check from
   the designated lab source. Do not run a subnet scan, test unrelated
   addresses, or attempt authentication bypass or exploitation.
7. Record the observed result, capture evidence, and any mismatch against
   the matrix. A failed connection alone is not proof of a firewall deny;
   check route, service state, and the designated gateway evidence.

### Part C — Packet-injection risk analysis

1. Use the instructor-provided PCAP from Part B or a separate instructor
   capture. Do not generate or transmit crafted packets.
2. Select one ordinary Modbus request and its TCP segment. Record the
   direction, TCP stream, sequence/acknowledgment context, and Modbus
   transaction identifier.
3. In a short written analysis, explain what additional session context an
   operating system's TCP stack checks before accepting payload bytes, and
   why a syntactically valid Modbus message is not sufficient evidence that
   a new or out-of-session packet would be accepted.
4. Compare the protocol's lack of client authentication with the protections
   supplied by segmentation and allow-listing. State the residual risk if an
   unauthorized client can establish an allowed TCP connection.
5. If the course requires a live demonstration, use the approved Modbus
   client from Part B to produce normal, attributable traffic to the simulator
   and analyze it in Wireshark. Do not use Scapy or another tool to inject
   packets into a live session.

### Part D — Containment tabletop and controlled validation

1. Select the assigned containment scenario, identify the narrowest flow
   that should be restricted, and list the services that must remain
   available.
2. Write a proposed change in the matrix before touching firewall
   configuration. Specify expected impact, validation check, approver, and
   rollback condition.
3. Apply the change only on the isolated lab gateway clone or
   student-managed gateway designated for this lab. Preserve the existing
   management path and console access.
4. Re-run only the approved positive and negative checks from Part B. Verify
   that the controller-to-simulator process path and HMI behave as expected,
   and that denied paths remain unavailable.
5. If any expected management or process function is lost, stop testing and
   invoke the documented rollback. Do not broaden access to make the test
   pass.

## Deliverables

Submit:

1. The completed allowed-flow matrix for the selected option.
2. A labeled topology diagram identifying where capture was performed.
3. Evidence and results for each approved positive/negative test.
4. A TCP-session versus Modbus-transaction explanation and packet-injection
   risk analysis based on observed evidence.
5. One containment recommendation with expected operational impact.
6. A rollback and post-change validation checklist.

## Instructor assessment

Assess whether rules are based on the selected topology, management and
process paths are kept distinct, the HMI is recognized as a separate
Modbus client, and test scope stays limited. A technically restrictive rule
that interrupts the documented process or risks Proxmox management access
should not be considered a successful result.

## Cleanup

Restore the instructor-approved firewall configuration if it was changed.
Verify both the selected controller's route to the simulator and the HMI's
read-only connection, then confirm no test guests remain attached to
unapproved networks.
