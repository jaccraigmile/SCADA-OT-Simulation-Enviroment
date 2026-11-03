# SIEM Integration and Virtual Company Cyber Range Design

## Purpose

This document explores extending the current virtual OT/SCADA lab into a
larger, fully virtualized company cyber range with centralized security
monitoring. It is an architecture proposal, not a deployment guide: no SIEM,
company services, or additional virtual networks are installed by this
document.

The current controller options, process simulator, HMI, and Proxmox network
configuration are described in
[OT_SCADA_ENVIRONMENT_SETUP.md](./OT_SCADA_ENVIRONMENT_SETUP.md).

The target learning environment combines ordinary enterprise IT with an
industrial process. Students can learn how business systems, users, networks,
controllers, and a simulated production line fit together, while a SIEM
collects events and helps analysts investigate activity across the range.
Exercises should remain confined to the authorized Proxmox environment.

## Current starting point

The existing lab already provides a useful OT pilot:

- Proxmox SDN networks keep the controller and process simulator in separate
  layer-2 segments.
- Kali routes Modbus/TCP between the controller and simulator, provides
  internet egress, and can capture the routed traffic.
- Option A uses OpenPLC Runtime v4 plus an Editor workstation. Option B uses
  a Python Modbus/TCP controller instead.
- `factoryio_simulator.py` models the conveyor and pick-and-place process.
- `simulator_monitor.py` serves a read-only browser HMI and polls Modbus input
  and coil states.

Current observability is limited. The simulator retains process events and
Modbus request counts internally, but does not print them automatically or
export structured audit events to a SIEM. Its interactive `status` command
can display a snapshot on request; the Python controller prints state and
output changes, and the HMI polls only current discrete inputs and coils.
The Modbus map does not expose exact box position or picker angle. Treat
structured simulator logging and network sensor deployment as future
integration work, not as capabilities already present.

## Proposed virtual-company architecture

Build the range from isolated network zones and route between them through
explicit firewall policy. Avoid placing every guest on one flat network.
Keep Proxmox host management outside the student range.

```text
                         Controlled update egress
                                  |
                          Range egress firewall
                                  |
       +--------------------------+--------------------------+
       |                          |                          |
   Enterprise IT                SOC zone                 OT boundary
       |                          |                          |
  Users and servers       SIEM / analyst VM          OT DMZ / jump host
       |                     log collector                    |
       +--------------------------+---------------------------+
                                  |
                         OT firewall / router
                                  |
                     PLC-LAB -> controller
                                  |
                     Kali capture / routing
                                  |
                     SIM-LAB -> simulator
```

In the existing pilot, Kali performs the OT inter-VNet routing role. As the
range grows, consider moving segmentation and egress enforcement to a
dedicated virtual firewall/router and placing a passive sensor at the OT
boundary. Kali can remain a student analysis host. This separates student
tools from the security boundary and avoids making a workstation the
long-term range firewall.

### Suggested zones

| Zone | Example systems | Purpose and boundaries |
| --- | --- | --- |
| Proxmox management | Proxmox host interfaces and administration workstation | Instructor-only infrastructure administration; not reachable from student or simulated company networks. |
| Enterprise users | A few Windows client VMs and optional Linux workstation | User activity, endpoint telemetry, and business workflow exercises. |
| Enterprise services | Directory/DNS, file service, application or intranet server | Simulated company identity, name resolution, shared documents, and business applications. |
| DMZ | Optional web or externally facing company service | A controlled place to teach boundary monitoring; no direct path from DMZ to OT. |
| SOC | SIEM, analyst workstation, log collector | Central monitoring and incident investigation; management access is restricted. |
| OT DMZ | Optional jump host or historian-like service | A monitored boundary between enterprise IT and OT. Allow only specifically required conduits. |
| PLC-LAB | OpenPLC Runtime or Python controller | Control logic and Modbus client. Retain the selected Option A or B topology. |
| SIM-LAB | Factory I/O replacement simulator | Process model and Modbus server. No direct internet or enterprise-user access. |
| Exercise tools | Kali or another instructor-approved analysis VM | Student testing tools; no attachment to the Proxmox management plane or physical production networks. |

Use the existing `MGMT`, `PLC-LAB`, and `SIM-LAB` names for the initial
pilot. For a full range, add distinct enterprise, SOC, DMZ, and OT-DMZ
networks rather than overloading the current management segment. Allocate
non-overlapping subnets from a private range and document the IP plan before
creating VMs.

## SIEM choices

Choose one platform based on course goals, available compute, instructor
experience, and licensing:

| Approach | Fit | Trade-offs |
| --- | --- | --- |
| Wazuh-based deployment | A practical starting point for endpoint agents, centralized event collection, and basic alert investigations. | Network protocol analysis may require a separate sensor and integration; plan storage and retention carefully. |
| Elastic-based stack | Flexible search and dashboard experience with a broad ecosystem. | More components and configuration to operate; control ingestion and retention to fit the host. |
| Splunk training deployment | Useful when the program specifically teaches Splunk workflows or the institution already has access. | Confirm education licensing and ingest limits before building the range around it. |
| Security Onion or another network-security distribution | Useful when network telemetry and analyst workflows are primary learning objectives. | Higher resource and operational footprint; may overlap with endpoint/SIEM capabilities. |

For a first implementation, use one SIEM platform and a small set of data
sources. Avoid installing multiple overlapping stacks until students have
learned basic event triage and correlation. Recheck each platform's current
licensing, supported versions, minimum resources, and deployment guidance
before selecting it; those details change over time.

## Telemetry plan

Centralize a few high-value sources first. Preserve timestamps and host
identity, synchronize guest clocks to the instructor-controlled time source,
and define retention limits so lab activity cannot exhaust Proxmox storage.

| Source | Candidate telemetry | Initial collection approach |
| --- | --- | --- |
| Windows endpoints and servers | Authentication events, account changes, service/process events, endpoint security alerts | SIEM-supported endpoint agent; enable only course-relevant audit categories. |
| Linux servers and controller | Authentication, service state, package changes, application output | Agent or controlled forwarding of journald/syslog. For the Python controller, capture its existing console output through a managed service and forward the service journal. |
| Kali/router/firewall | Allowed and denied forwarding, NAT/routing changes, authentication, system events | Export firewall counters/logs and system logs to the SOC collector. Avoid logging every accepted packet by default. |
| OT network | Modbus client/server conversations, function codes, endpoints, timing, protocol errors, connection attempts | Passive Zeek/Suricata or PCAP-based sensor at the routed OT boundary. Test parser coverage against this simulator and selected port `1502`; do not assume port `502` defaults apply. |
| Simulator process | Box emitted/picked/released, door state changes, coil transitions, simulator lifecycle | Future enhancement: emit structured JSON lines or syslog with UTC timestamp, simulator ID, event type, and relevant signal names. Current terminal text is not a structured SIEM feed. |
| OpenPLC/Python controller | Deployment or service lifecycle, controller state, connection errors, output transitions | Collect host/service logs. Keep controller audit events distinguishable from simulator events. |
| HMI | HMI service start/stop and access logs, if needed | The current HMI is read-only and has no authentication; bind it only to localhost or a restricted lab interface. Do not treat it as an authorization or safety control. |

Network monitoring should be passive. In a routed design, observe traffic at
the Kali OT-facing interfaces or a dedicated sensor on the routed path.
Proxmox SDN does not guarantee that a VM attached to a switched VNet sees
other guests' unicast traffic. If adding a dedicated sensor, use a deliberate
traffic mirror or place it where the routed packets actually traverse.

Use a forwarding/collector path that does not make the SIEM a transit router
for Modbus. Permit controller-to-simulator traffic only as required; send
telemetry to the SOC over a separate, explicitly allowed path. Keep telemetry
transport and management interfaces off the public uplink.

## Example detection and investigation exercises

Use detections to teach normal baselines and investigation, not just alert
generation. Keep all activity inside the range and use snapshots to restore
known-good states.

1. **Baseline production:** Run the selected controller normally. Identify
   expected Modbus endpoints, FC 2 polling, coil writes, service logs, and
   normal simulator event ordering.
2. **Unexpected OT communication:** Generate an instructor-approved
   connection attempt within the isolated range. Investigate endpoint,
   interface, firewall, and sensor evidence; distinguish allowed process
   traffic from blocked attempts.
3. **Unusual control change:** In a controlled exercise, make an approved
   change to one simulated output and compare the controller log, Modbus
   capture, simulator event, and HMI display. Use this to teach evidence
   correlation and process impact.
4. **Safety-state transition:** Open the simulator's safety door using the
   simulator interface. Confirm that the HMI reports the input, controller
   behavior is visible, and the event timeline is consistent.
5. **Endpoint and identity investigation:** Use a prepared account or service
   event on a Windows/Linux VM and investigate it alongside network activity.
   Do not reuse real credentials or connect the exercise identity system to
   production.
6. **Protocol-security capstone:** If the course includes Modbus packet
   manipulation, define the exact lab target, expected process effect,
   monitoring evidence, and reset procedure in a separate instructor
   exercise. Keep it limited to the simulator and routed lab subnet; this
   design document does not provide packet-crafting instructions.

For each exercise, record the learning objective, authorized source and
destination, expected benign evidence, stop condition, instructor contact,
and reset steps. Avoid uncontrolled automation or scenarios that can escape
the range.

## Build plan

### Phase 1 — Stabilize the OT pilot

- Choose Option A or Option B and capture a known-good Proxmox snapshot.
- Confirm routing, Kali capture, simulator, controller, and HMI work as
  documented in the environment setup guide.
- Record normal Modbus conversations and process behavior as a baseline.

### Phase 2 — Add a minimal SOC

- Deploy one SIEM VM and a separate analyst workstation on the SOC network.
- Forward a small set of Windows, Linux, and Kali logs.
- Verify timestamps, host naming, event visibility, and retention.
- Initially keep the SIEM management UI reachable only from the analyst
  workstation or instructor network.

### Phase 3 — Add OT network telemetry

- Place a passive sensor at the routed OT boundary or export carefully
  selected PCAPs from Kali for analysis.
- Confirm the sensor sees both directions of the controller/simulator flow.
- Validate Modbus decoding on the configured TCP port and compare observed
  traffic with controller and simulator logs.
- Add rules for basic inventory, unexpected endpoint pairs, protocol errors,
  and unusual communication rates. Tune them against normal polling so the
  class can distinguish signal from noise.

### Phase 4 — Add the simulated company

- Add a small user population and a few representative enterprise services.
- Define a fictional company workflow that causes a production request to
  reach the OT operator/controller through approved, documented interfaces.
- Add network zones incrementally, enforcing deny-by-default boundaries and
  permitting only required business-to-OT conduits.
- Collect a small subset of identity, endpoint, DNS, firewall, and application
  logs for cross-domain investigation.

### Phase 5 — Instructor-led range exercises

- Publish an exercise brief, rules of engagement, allowed targets, and
  emergency stop/reset procedure.
- Test each exercise and its defensive evidence before student use.
- Reset from snapshots and rotate any credentials used in the fictional
  environment between cohorts.
- Review SIEM event quality, exercise timing, and storage impact after each
  run.

## Resource and operations considerations

A useful first cyber range does not need a large simulated enterprise. Start
with the current controller/simulator pair, a SIEM, an analyst VM, one
Windows client, and a small Linux service. Add directory services, more
endpoints, or a DMZ only when a specific lesson needs them.

Before sizing, check available Proxmox CPU, memory, and storage and use the
selected SIEM's current official sizing guidance. Reserve disk for event
growth and snapshots, not only VM disks. Limit event retention and avoid
unfiltered packet capture for long periods. A compact lab can export bounded
PCAP clips for lessons rather than storing every packet indefinitely.

Operational controls should include:

- Isolated SDN networks and explicit firewall policy.
- No routes from the range to physical production or personal networks.
- Restricted internet egress through a controlled gateway; no inbound
  internet exposure.
- Instructor-only Proxmox administration and student-limited range access.
- Synthetic company data and unique, disposable lab credentials.
- Time synchronization, snapshots, documented reset, and log-retention
  limits.
- A written rule that student activity and packet capture are authorized only
  within the assigned range.

## Recommendation

The environment can be extended into a useful virtual-company cyber range.
The best next step is not to build a large company all at once: first add a
small SIEM and endpoint logs to the existing OT pilot, then add passive OT
network telemetry, and only then add enterprise identity and business
services. Keep the existing Option A and Option B as alternative OT
controller configurations, and make the SIEM and analyst workflow common to
both.

This staged approach gives students a complete investigation path—from user
or system event, through network evidence, to a visible simulated process
effect—without connecting the range to real OT equipment.
