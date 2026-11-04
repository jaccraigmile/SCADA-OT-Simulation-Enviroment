# Advanced Lab 4: Modbus/TCP Session Analysis with Scapy

## Purpose

Use Kali, Wireshark, and Scapy to examine how Modbus/TCP messages travel
inside an established TCP session. The exercise follows the concepts in the
[Scapy Modbus/TCP packet-injection tutorial](https://rodrigocantera.com/en/modbus-tcp-packet-injection-with-scapy/),
but limits activity to packet capture, offline analysis, and defensive
reasoning. Students do not create or transmit forged packets.

The central lesson is that a valid Modbus request payload alone does not
make it a valid TCP segment for an existing connection. TCP sequence and
acknowledgment state, stream direction, payload length, and connection state
all matter. The simulator uses a normal TCP socket and does not provide a
packet-injection bypass.

## Learning objectives

- Identify TCP streams used by the controller and HMI.
- Distinguish TCP sequence/acknowledgment numbers from Modbus transaction
  identifiers.
- Correlate TCP payload lengths with sequence-space advancement, including
  SYN and FIN flags.
- Identify retransmissions, ACK-only packets, and Modbus request/response
  payloads in a capture.
- Explain why packet injection is not performed in this exercise and propose
  defensive monitoring and containment measures.

## Required environment

- A working [lab setup](./OT_SCADA_ENVIRONMENT_SETUP.md) using one controller
  option.
- Kali connected to the isolated lab networks.
- The simulator at `10.77.20.10`, using standard Modbus/TCP port `502` and
  unit ID `1`.
- Wireshark and tcpdump.
- Scapy on Kali. Check with `python3 -c 'import scapy; print(scapy.__version__)'`.
  If it is not installed, install the Kali package with
  `sudo apt update && sudo apt install python3-scapy`.

## Safety and scope

- Capture only the assigned lab interfaces and simulator traffic.
- The only Modbus server in scope is `10.77.20.10:502`.
- Do not use Scapy `send()`, `sendp()`, `sr()`, `srp()`, or packet-crafting
  functions to transmit traffic.
- Do not attempt TCP sequence prediction, session takeover, forged writes,
  or injection against the live simulator or any other host.
- Do not change safety inputs. Follow the instructor's recovery procedure
  if normal controller operation is disrupted.
- Save PCAPs only in the authorized lab workspace and remove them according
  to the course retention policy.

## Preparation

1. Select either Option A or Option B and start only that controller.
2. Verify the simulator and HMI are working before capture. Record the
   selected controller option, the assigned Kali interface names, simulator
   address, port, and capture time.
3. On Kali, identify the routed lab interfaces:

   ```bash
   ip -br address
   ```

4. Start a bounded capture on the interface carrying controller traffic.
   Substitute the actual Kali PLC-LAB interface name:

   ```bash
   sudo tcpdump -ni <PLC_IF> -s 0 -w modbus-session.pcap \
     'host 10.77.10.10 and host 10.77.20.10 and tcp port 502'
   ```

   Capture HMI traffic separately on SIM-LAB if required:

   ```bash
   sudo tcpdump -ni <SIM_IF> -s 0 -w hmi-session.pcap \
     'host 10.77.20.1 and host 10.77.20.10 and tcp port 502'
   ```

5. Let normal controller polling run for at least 30 seconds. Include one
   ordinary box movement if possible; do not make manual Modbus writes as
   part of this lab.
6. Stop tcpdump with Ctrl+C. Keep the controller running only if required by
   the next instructor-directed task.

## Exercise

### Part A — Establish TCP session state in Wireshark

1. Open `modbus-session.pcap` in Wireshark and apply:

   ```text
   tcp.port == 502
   ```

2. Select the controller-to-simulator stream and use **Analyze > Follow >
   TCP Stream**. Record:
   - Client and server IP/port.
   - TCP stream number.
   - SYN, SYN/ACK, and ACK sequence numbers.
   - Whether the client connection remains open for multiple Modbus
     transactions.
3. Use **Statistics > Conversations > TCP** to compare the controller and
   HMI flows. Explain why the HMI has a separate connection.
4. Expand several TCP segments and record their sequence number,
   acknowledgment number, flags, and payload length. Note that SYN and FIN
   each consume one sequence number even though they carry no application
   payload. Retransmitted segments do not represent new Modbus commands.
5. Decode Modbus/TCP if Wireshark does not do so automatically:
   **Analyze > Decode As** and select Modbus/TCP for TCP port `502`.
   Compare the MBAP transaction identifier with the TCP sequence number.
   Explain why they are different fields with different purposes.
6. For a request and its response, record the Modbus unit ID, function code,
   starting address/count (when present), TCP payload length, and response
   transaction identifier. Correlate the response with its request.

### Part B — Inspect the capture offline with Scapy

Use Scapy only to read the saved PCAP. This script reports TCP headers and
the first bytes of each captured payload; it does not transmit packets:

```python
from scapy.all import IP, TCP, rdpcap

for packet in rdpcap("modbus-session.pcap"):
    if IP not in packet or TCP not in packet:
        continue

    tcp = packet[TCP]
    payload = bytes(tcp.payload)
    if tcp.sport != 502 and tcp.dport != 502:
        continue

    print(
        f"{packet[IP].src}:{tcp.sport} -> {packet[IP].dst}:{tcp.dport} "
        f"flags={tcp.flags} seq={tcp.seq} ack={tcp.ack} "
        f"payload_len={len(payload)} payload_prefix={payload[:16].hex()}"
    )
```

Answer:

1. Which direction initiates the TCP connection?
2. Which packets contain Modbus/TCP payload, and which are ACK-only?
3. Find one transaction and compare its MBAP transaction identifier to the
   TCP sequence and acknowledgment values. Why can these values not be
   substituted for one another?
4. For a non-empty TCP payload, compare the next sequence number with the
   segment's sequence number plus payload length. Account separately for
   SYN/FIN flags and any retransmissions.
5. Compare the PCAP evidence with the simulator/HMI observations. State what
   the capture proves and what it cannot prove about process state.

### Part C — Defensive analysis

Write a short detection and response note containing:

- Expected controller and HMI source/destination pairs.
- Normal connection initiators, polling cadence, Modbus function codes, and
  unit ID.
- Signals that may indicate an unexpected client, malformed exchange, or
  connection anomaly.
- Limits of relying on a single packet, TCP sequence value, or Modbus
  transaction identifier as proof of a command's origin.
- A containment plan that blocks only the unauthorized path while preserving
  the authorized controller, HMI, and management functions.

Do not treat an unusual TCP sequence value alone as proof of malicious
activity. Correlate the complete TCP conversation, Modbus transaction, host,
and process evidence.

## Deliverables

- `modbus-session.pcap` and, if assigned, `hmi-session.pcap`.
- A table of at least five TCP segments with direction, flags, sequence,
  acknowledgment, payload length, and interpretation.
- A correlated Modbus request/response table with transaction IDs and
  function codes.
- Answers to Part B and a short defensive analysis from Part C.
- Confirmation that no packets were crafted or transmitted.

## References

- [Scapy Modbus/TCP packet-injection tutorial](https://rodrigocantera.com/en/modbus-tcp-packet-injection-with-scapy/)
- [Scapy documentation](https://scapy.readthedocs.io/en/latest/)
- [Wireshark Modbus/TCP dissection tutorial](https://rodrigocantera.com/en/dissecting-openplc-modbus-tcp-communications-with-wireshark/)
