# OT/SCADA Lab Environment Setup Guide

## Purpose

Build and verify the isolated virtual OT/SCADA environment used by the
advanced cybersecurity labs. This guide covers Proxmox networks, the Kali
gateway, the process simulator, HMI, and one controller option. Hands-on
security exercises are described in the separate advanced lab documents.

## Choose a controller option

The simulator, Kali gateway/capture host, and isolated Proxmox networks are
common to both options. Choose one controller path for a lab run:

| Option | Controller | What you will do |
| --- | --- | --- |
| **Option A — OpenPLC Runtime v4** | OpenPLC Runtime v4 plus a Control VM running the OpenPLC Editor | Configure a Modbus Remote Device, deploy a Structured Text program, and observe how PLC logic reads inputs and controls outputs. |
| **Option B — Python Modbus/TCP** | A Debian/Ubuntu LXC running `factoryio_modbus_controller.py` | Run a standalone controller that communicates directly with the simulator and executes the pick-and-place sequence. No OpenPLC Runtime or Editor is required. |

Option A is the PLC-based path and the primary route for learning how an
industrial controller and its engineering workstation interact in an
OT/SCADA system. Option B is an alternative for studying Modbus/TCP and
process behavior without setting up OpenPLC. The two controllers use the same
simulator I/O map and route through Kali, but they are alternatives, not
simultaneous controllers.

This is a learning lab for systems you own or are authorized to administer.
The simulator has no authentication and Modbus/TCP is unencrypted. Keep the
lab VNets separate from each other and from the physical LAN; Kali is their
only routed gateway. Internet egress is enabled through Kali, but new
connections from the internet into the lab must remain blocked.

## Common to both options

Both options use these shared components:

- Proxmox VE with SDN available, or equivalent isolated virtual networks.
- One Debian/Ubuntu LXC or VM running `factoryio_simulator.py`.
- One Kali VM acting as router, internet gateway, and capture point; it also
  hosts the browser-based HMI.
- Wireshark and the simulator source from this repository.

The same simulator, Kali gateway/capture host, HMI, and Modbus I/O map
are used in both options. The selected controller is the Modbus client. The
HMI polls the simulator's inputs and coils read-only.

## Shared Kali gateway, capture, and HMI setup

On Kali, identify the interface names for its internet uplink and the two
shared lab networks, `PLC-LAB` and `SIM-LAB`:

```bash
ip -br address
ip route
```

Kali's default route must use its internet uplink. Enable IPv4 forwarding for
the current boot:

```bash
sudo sysctl -w net.ipv4.ip_forward=1
```

For persistence across Kali reboots:

```bash
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-plc-lab.conf
sudo sysctl --system
```

Configure Kali to route between `PLC-LAB` and `SIM-LAB` and masquerade traffic
from both lab subnets out its internet uplink. For example, with `iptables`,
substitute your actual interface names for `WAN_IF`, `PLC_IF`, and `SIM_IF`.
Use the `FORWARD` default-drop command below only on a dedicated Kali gateway;
if Kali already routes other networks, integrate the allow rules without
changing its existing policy.

```bash
WAN_IF="your-internet-interface"
PLC_IF="your-plc-lab-interface"
SIM_IF="your-sim-lab-interface"

sudo iptables -P FORWARD DROP
sudo iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A FORWARD -i "$PLC_IF" -o "$WAN_IF" -s 10.77.10.0/24 -j ACCEPT
sudo iptables -A FORWARD -i "$SIM_IF" -o "$WAN_IF" -s 10.77.20.0/24 -j ACCEPT
sudo iptables -A FORWARD -i "$PLC_IF" -o "$SIM_IF" -s 10.77.10.10 -d 10.77.20.10 -p tcp --dport 1502 -m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT
sudo iptables -t nat -A POSTROUTING -s 10.77.10.0/24 -o "$WAN_IF" -j MASQUERADE
sudo iptables -t nat -A POSTROUTING -s 10.77.20.0/24 -o "$WAN_IF" -j MASQUERADE
```

These are example additions, not a complete firewall policy. On a dedicated
Kali lab gateway, use a default-deny FORWARD policy and then add the required
allow rules; if Kali already routes other networks, integrate an equivalent
policy without disrupting them. Apply rules in the firewall system already
managing Kali, and make them persistent across reboots. Keep forwarding from
the internet uplink to lab interfaces blocked for new connections; permit
established return traffic. Do not flush the firewall or enable unrestricted
forwarding. Keep the two lab VNets separate: allow only the
controller-to-simulator TCP `1502` flow between them, plus its established
replies. The HMI connects locally from Kali's SIM-LAB address
`10.77.20.1`, so it does not need a forwarded rule.

The upstream network must allow Kali to reach the internet. Use the network's
approved DNS configuration; the forwarding and NAT rules allow lab guests to
make outbound connections and return traffic but do not expose them to new
inbound internet connections. This is internet egress, not an air-gapped lab;
do not expose guest management services, and keep outbound access limited to
what the exercise needs if the upstream policy requires it.

From a guest, verify its default route points to Kali at the gateway address
configured for that guest, then test DNS and HTTPS:

```bash
ip route
curl -I https://deb.debian.org/
```

On Kali itself, verify that its own default route uses the uplink and that an
HTTPS request succeeds before debugging guest routing:

```bash
ip route
curl -I https://deb.debian.org/
```

On Kali, `-i any` may show a forwarded packet once on ingress and again on
egress. This is expected. For a single view of the controller-originated
flow, capture on the PLC-LAB interface; capture on SIM-LAB to see the
monitor's direct connection. Internet-bound traffic can be captured on Kali's
uplink as well. Wireshark can capture on multiple interfaces if you want both
views.

Start a capture on Kali before starting either controller:

```bash
sudo tcpdump -ni any 'host 10.77.10.10 and host 10.77.20.10 and tcp port 1502'
```

Alternatively, open Wireshark on Kali, capture on its lab interfaces, and use
this display filter:

```text
tcp.port == 1502
```

If Wireshark does not decode port `1502` as Modbus/TCP automatically, select a
packet and use **Analyze > Decode As** to decode that TCP port as Modbus/TCP.

Start the browser-based HMI on Kali in another terminal:

```bash
python3 simulator_monitor.py --host 10.77.20.10 --port 1502 --unit-id 1
```

On Kali, open `http://127.0.0.1:8080/`. The page shows the simulated
conveyor/picker, all Modbus input and output states, safety-door status, and
connection freshness. It is read-only and sends only FC 2 and FC 1 polls.
The process animation is inferred from I/O signals; exact machine position
and box-count telemetry are not exposed through this Modbus map. This
display is for training and monitoring, not process control or safety
decisions; it is not safety-rated.

The HTTP server binds to localhost by default. To access it from another
authorized lab workstation, explicitly bind it to a Kali interface reachable
from that workstation (the option-specific topology identifies its Kali
addresses) and permit TCP `8080` only from that workstation:

```bash
HMI_BIND_IP="actual-kali-interface-address"
python3 simulator_monitor.py --host 10.77.20.10 --port 1502 --unit-id 1 --web-host "$HMI_BIND_IP"
```

Set `HMI_BIND_IP` to the Kali interface IP reachable from the authorized
workstation, then browse to that IP on port `8080`. Do not bind to all
interfaces or expose this unauthenticated display outside the isolated lab.

### Shared simulator setup

On the simulator guest, install Python 3, copy or clone this repository, then
run from the repository directory:

```bash
python3 factoryio_simulator.py --host 0.0.0.0 --port 1502 --unit-id 1
```

Use Python 3.10 or newer for the simulator and HMI. The simulator also starts
a process-reset HTTP endpoint bound only to `127.0.0.1:8081`; it is not
reachable through the lab network.

Keep the process running. Its prompt accepts `status`, `start`, `box`,
`door open`, `door close`, `auto on`, `auto off`, and `reset`. For this setup,
leave automatic box emission enabled. A box appears after about five seconds.
The simulator prints the
current process summary every two seconds and reports events such as box
emission, output coil changes, and picker motion. Enter `status` for an
immediate snapshot. Use `--status-interval 0` to disable periodic summaries
while retaining event logs.

### Reset the simulator process

After an advanced exercise, stop the selected controller first so it cannot
immediately write outputs back to the simulator. On the simulator guest, run
the reset helper from the repository directory:

```bash
python3 reset_lab_process.py --confirm
```

The helper calls the simulator's loopback-only reset endpoint. It restores
the startup process state: safety door closed, start pulse cleared, all five
coils off, no box in the process, picker retracted and at its home angle,
removed-box count zero, automatic emitter on, and request/event counters
cleared. The automatic emitter will release its next box after the normal
interval.

The same action is available by entering `reset` at the simulator's `sim>`
prompt. Restarting the simulator process also restores this baseline.
This is a process-state reset only: it does not restart or reconfigure either
controller, restore a VM snapshot, or change Kali, firewall, or Proxmox
network settings. Confirm the HMI shows the reset state, then start the
selected controller when ready.

Permit inbound TCP port `1502` to the simulator from the controller at
`10.77.10.10` (forwarded through Kali) and the HMI host at
`10.77.20.1` in any guest or Proxmox firewall that applies.

## Option A — OpenPLC Runtime v4 procedure

Follow this section for the PLC-based path. Skip it if you chose Option B.

Option A additionally requires an OpenPLC Runtime v4 VM/container and a
Control VM with the OpenPLC Editor installed. The Control VM configures and
deploys the PLC program; the Runtime is the Modbus client.

### Option A topology

This option includes a separate management network for the OpenPLC Editor
Control VM to reach Runtime v4. Kali has a WAN uplink plus MGMT, PLC-LAB, and
SIM-LAB interfaces. The process VNets remain separate; Modbus traffic must
route through Kali.

```text
                                      Internet
                                         |
                 Internet-facing Proxmox bridge (uplink only)
                                         |
                                    Kali WAN NIC
                   Kali gateway / NAT / capture / HMI
                      /              |               \
                 MGMT NIC       PLC-LAB NIC       SIM-LAB NIC
               10.77.0.1/24    10.77.10.1/24     10.77.20.1/24
                    |               |                 |
                MGMT VNet       PLC-LAB VNet       SIM-LAB VNet
                /       \            |                  |
       Control VM   Runtime mgmt  Runtime data      Simulator LXC
       10.77.0.20   10.77.0.10   10.77.10.10       10.77.20.10
```

| Guest/interface | Network | Address and gateway/route |
| --- | --- | --- |
| Control VM with Editor | `MGMT` | `10.77.0.20/24`, gateway `10.77.0.1` |
| OpenPLC Runtime management NIC | `MGMT` | `10.77.0.10/24`, gateway `10.77.0.1` |
| Kali MGMT NIC | `MGMT` | `10.77.0.1/24` |
| Kali PLC-LAB NIC | `PLC-LAB` | `10.77.10.1/24` |
| OpenPLC Runtime data NIC | `PLC-LAB` | `10.77.10.10/24`, route `10.77.20.0/24` via `10.77.10.1` |
| Kali SIM-LAB NIC | `SIM-LAB` | `10.77.20.1/24` |
| Simulator NIC | `SIM-LAB` | `10.77.20.10/24`, gateway `10.77.20.1` |
| Kali WAN NIC | Internet-facing Proxmox bridge | Upstream DHCP/static address; Kali default route |

In Proxmox, create `MGMT`, `PLC-LAB`, and `SIM-LAB` as separate networks.
Attach the Control VM and Runtime management NIC to `MGMT`, the Runtime data
NIC to `PLC-LAB`, and the simulator NIC to `SIM-LAB`. Attach Kali to all three
lab networks and the internet-facing bridge with its WAN NIC. Configure the
addresses and routes in the table; do not bridge the VNets or attach lab
guests directly to the WAN bridge.

For internet egress from the Option A management subnet, add these
Option-A-only rules to Kali's shared firewall configuration, using the
interface name for `MGMT`:

```bash
MGMT_IF="your-mgmt-interface"
sudo iptables -A FORWARD -i "$MGMT_IF" -o "$WAN_IF" -s 10.77.0.0/24 -j ACCEPT
sudo iptables -t nat -A POSTROUTING -s 10.77.0.0/24 -o "$WAN_IF" -j MASQUERADE
```

Configure the Runtime's default route through Kali's MGMT address
(`10.77.0.1`) for management/internet egress, and add the more specific route
to `10.77.20.0/24` through its data-side Kali address (`10.77.10.1`). This
specific route ensures Modbus requests pass Kali. Configure the Control VM's
default gateway as `10.77.0.1` and the simulator's as `10.77.20.1`.

The management and process paths are distinct:

```text
Editor on Control VM -> MGMT -> OpenPLC Runtime management NIC
OpenPLC Runtime data NIC -> Kali PLC-LAB -> Kali SIM-LAB -> simulator
Kali HMI -> Kali SIM-LAB -> simulator (read-only polling)
Lab internet egress -> Kali's attached network -> Kali WAN NIC
```

#### Option A troubleshooting

- **Control VM cannot connect to Runtime:** Check MGMT addresses and
  reachability, then verify the Runtime v4/Edge Device registration and the
  deployment-specific management ports.
- **Editor has no Modbus option:** The editor documentation gates Modbus
  Remote Devices to the Simulator or Runtime v4 targets. Confirm the selected
  target.
- **PLC uploads but does not run:** Click **Play** after the upload and check
  that the Program instance is assigned to a cyclic task.

### 1. Connect the Control VM's editor to Runtime v4

The Control VM is not the Modbus master; the Runtime is. Connect the editor
and deploy the program before setting up the Remote Device:

1. Confirm the Control VM can reach the Runtime management interface
   `10.77.0.10` on `MGMT`. Keep this connection separate from the PLC-LAB and
   SIM-LAB process networks.
2. In the new editor, expand **Device** and open **Edge Devices**. Select the
   Runtime v4 vPLC and click **Connect**. If it is a first connection, create
   the runtime user; otherwise log in with the runtime-side credentials.
3. If the Runtime does not appear, finish registering/bringing its Edge Device
   online using the deployment's platform workflow. The editor docs require
   the Edge Device to be online and reachable; do not expose its management
   interface to the lab VNets just to make discovery work.
4. Once connected, build and upload from the Control VM. The Runtime then
   makes the Modbus connection to `10.77.20.10:1502` through Kali.

The exact management service/port depends on how Runtime v4 was deployed.
Allow the ports required by that deployment between the Control VM and
Runtime only; this lab does not assume a universal management port.

### 2. Verify the routed connection

On the OpenPLC runtime guest, check that the simulator route goes through
Kali:

```bash
ip route get 10.77.20.10
```

The result should show next hop `10.77.10.1` on the PLC-LAB interface. Then
test the Modbus TCP port:

```bash
nc -vz -w 3 10.77.20.10 1502
```

Expect a successful TCP connection. At the same time, Kali's capture should
show traffic between `10.77.10.10` and `10.77.20.10`. If the route or port
test fails, fix the network before configuring the editor.

### 3. Configure a Modbus Remote Device in OpenPLC Editor

The simulator is the Modbus **server/slave**; OpenPLC is the **client/master**.
In the new editor, create a **Remote Device**, not a Modbus Server:

1. Open a project and select the Runtime v4 target. In the project tree, click
   `+` > **Remote Device** > **Modbus**. Name it `FactoryIOSimulator` and
   create it.
2. Set **Transport** to `TCP/IP`, **IP Address** to `10.77.20.10`,
   **Port** to `1502`, **Slave ID** to `1`, and **Timeout (ms)** to `1000`.
3. Add a read group:

   | Field | Value |
   | --- | --- |
   | Name | `Sensors` |
   | Function Code | Read Discrete Inputs (FC 2) |
   | Cycle Time (ms) | `100` |
   | Offset | `0` |
   | Length | `6` |

   Expand the group and assign these aliases in address order:

   | Offset | Alias |
   | ---: | --- |
   | 0 | `StartButton` |
   | 1 | `SafetyDoorClosed` |
   | 2 | `BoxAtSensor` |
   | 3 | `RobotDetected` |
   | 4 | `MovingZ` |
   | 5 | `Rotating` |

4. Add five write groups. Use **Write Single Coil (FC 5)**, length `1`, and
   cycle time `100` ms for each:

   | Group | Offset | Point alias |
   | --- | ---: | --- |
   | `Conveyor` | 0 | `Conveyor` |
   | `Grab` | 1 | `Grab` |
   | `ExtendZ` | 2 | `ExtendZ` |
   | `RotateCW` | 3 | `RotateCW` |
   | `RotateCCW` | 4 | `RotateCCW` |

These are remote Modbus offsets, starting at zero. Do not use the older
`%IX100.x` / `%QX100.x` addresses from the Factory I/O tutorial; this
simulator uses a different I/O map. FC 5 is used because the current editor's
documented Modbus group picker offers single-coil writes. The simulator also
supports FC 15, but this lab does not depend on the editor exposing it.

### 4. Write a first ST program

Create a **Program** POU using **Structured Text (ST)**. The variables table
must expose the Remote Device aliases used below. Add one local BOOL variable
named `RUN`, initialized to `FALSE`. In the ST body, enter only the statements
below; the editor manages the POU and variable declarations separately:

```iecst
IF NOT SafetyDoorClosed THEN
    RUN := FALSE;
ELSIF StartButton THEN
    RUN := TRUE;
END_IF;

Conveyor := RUN AND NOT BoxAtSensor;
Grab := FALSE;
ExtendZ := FALSE;
RotateCW := FALSE;
RotateCCW := FALSE;
```

This first exercise latches `RUN` when the simulator's `start` command pulses
the start input, stops the conveyor when the safety door opens, and advances a
box until it reaches the pickup sensor. It deliberately leaves the picker
outputs off; the goal is to verify input reads, an output write, and the routed
capture before attempting pick-and-place logic.

Check **Resource** and ensure an instance of the Program is assigned to a
cyclic task. Connect the editor to the Runtime v4 target through **Device** >
**Edge Devices**. Choose **Build only** to validate first, then **Build &
Upload** and **Play** to run on the vPLC. Uploading does not start the PLC.

### 5. Observe and validate

1. In the simulator prompt, enter `status`. Initially, the door input should
   be `True`; a newly emitted box begins away from the sensor.
2. Open the HMI at `http://127.0.0.1:8080/` in Kali's browser. It
   refreshes the six discrete inputs and five coils, renders an approximate
   process overview, and sends FC 2 and FC 1 read requests only. Its polling
   appears in the capture as a separate TCP connection from Kali.
3. Start the Kali capture, then run the PLC. In Wireshark, look for periodic
   FC 2 requests and responses. The configured read group polls all six inputs.
4. At the simulator prompt, enter `start`. The start input is pulsed for
   250 ms, so the HMI may show it briefly; watch the editor debugger for
   the latched `RUN` value. The conveyor coil should turn on.
5. Watch the HMI as the box approaches `BoxAtSensor`. The PLC should
   turn the conveyor off when the input becomes true. Enter `door open`; the
   PLC should clear `RUN` and keep the conveyor off. Enter `door close` and
   issue `start` again to resume.
6. In Wireshark, distinguish the runtime's Modbus stream (source
   `10.77.10.10`) from the HMI's read-only stream (source
   `10.77.20.1`). Identify FC 2 polls, FC 5 writes, unit ID `1`, and changes
   that match the HMI display. Save a PCAP only in the authorized lab
   workspace.

## Option B — Python Modbus/TCP controller

This option replaces the OpenPLC Runtime on the PLC-LAB side with a small
Python container that acts as the Modbus/TCP client. The simulator remains the
Modbus server. Keep Kali between the controller and simulator:

### Option B topology

```text
                                      Internet
                                         |
                 Internet-facing Proxmox bridge (uplink only)
                                         |
                                    Kali WAN NIC
                   Kali gateway / NAT / capture / HMI
                      /                               \
             PLC-LAB NIC                           SIM-LAB NIC
           10.77.10.1/24                           10.77.20.1/24
                 |                                      |
             PLC-LAB VNet                           SIM-LAB VNet
                 |                                      |
 Python controller LXC                         Simulator LXC
     10.77.10.10/24                               10.77.20.10/24
```

| Guest/interface | Network | Address and gateway/route |
| --- | --- | --- |
| Kali PLC-LAB NIC | `PLC-LAB` | `10.77.10.1/24` |
| Python controller LXC | `PLC-LAB` | `10.77.10.10/24`, gateway `10.77.10.1` |
| Kali SIM-LAB NIC | `SIM-LAB` | `10.77.20.1/24` |
| Simulator NIC | `SIM-LAB` | `10.77.20.10/24`, gateway `10.77.20.1` |
| Kali WAN NIC | Internet-facing Proxmox bridge | Upstream DHCP/static address; Kali default route |

Create separate `PLC-LAB` and `SIM-LAB` networks. Kali needs NICs on both,
plus its WAN NIC; do not attach the controller or simulator directly to the
internet-facing bridge. Do not configure an OpenPLC Runtime, Editor Control
VM, or MGMT network for this option. Configure the controller's default
gateway as `10.77.10.1` and the simulator's as `10.77.20.1`. The controller
route to the simulator must pass through Kali; do not add a direct
controller-to-simulator interface or bypass route.

1. Create a Debian/Ubuntu LXC named `python-controller` and attach its NIC to
   `PLC-LAB`. Configure `10.77.10.10/24` with default gateway `10.77.10.1`.
2. Install Python 3.10 or newer in the controller LXC. Copy
   `factoryio_modbus_controller.py` from this repository into it. The
   controller uses only the Python standard library.
3. Keep the simulator running at `10.77.20.10:1502`, unit ID `1`, as in the
   common simulator setup.
4. On Kali, allow TCP `1502` from the controller through to the simulator and
   established return traffic. The common Kali gateway section has the
   example forwarding rule; use Kali's `PLC-LAB` and `SIM-LAB` interface
   names. Capture with:

   ```bash
   sudo tcpdump -ni any 'host 10.77.10.10 and host 10.77.20.10 and tcp port 1502'
   ```

5. From the controller LXC, verify the route and TCP reachability:

   ```bash
   ip route get 10.77.20.10
   nc -vz -w 3 10.77.20.10 1502
   ```

   The route must go through `10.77.10.1` and the TCP connection must succeed.
6. Start the direct controller:

   ```bash
   python3 factoryio_modbus_controller.py --host 10.77.20.10 --port 1502 --unit-id 1
   ```

   It polls the six discrete inputs with FC 2, writes coils with FC 5, and
   prints its state and output changes. It starts in `WAIT_START`; at the
   simulator's `sim>` prompt, enter `start` to pulse `StartButton` and begin
   the conveyor/pick/place/return sequence. Enter `door open` to stop outputs
   and reset the sequence; close the door and issue `start` again to resume.
   Press Ctrl+C in the controller terminal to stop it; on normal shutdown it
   attempts to turn all five coils off.
7. Open the HMI at `http://127.0.0.1:8080/` in Kali's browser. The
   display shows live process signals and approximate motion, while Wireshark
   shows the controller's FC 2 requests and FC 5 coil writes. The HMI's own
   FC 2 and FC 1 polling is a separate connection sourced from Kali at `10.77.20.1`.
   The Modbus exchange itself is direct controller-to-simulator over the
   routed Kali path; Kali is not acting as an active Modbus proxy.

This Python option replaces the PLC logic for this introductory exercise. It
does not run an OpenPLC Runtime, execute IEC 61131-3 programs, or connect to
the Editor.

#### Option B troubleshooting

- **Python controller cannot start:** Check Python 3.10+, simulator host/port,
  Slave ID `1`, and that the simulator is running. The controller exits with
  an error if its Modbus connection or response fails.

## Troubleshooting

- **No packets on Kali:** On the PLC guest, check `ip route get 10.77.20.10`.
  If the next hop is not Kali's `10.77.10.1`, the Modbus flow bypasses Kali.
- **Route works but TCP test fails:** Check that the simulator is listening on
  `0.0.0.0:1502`, the simulator IP is correct, and forwarding/firewall rules
  permit the flow.
- **HMI shows disconnected:** Verify the simulator accepts TCP `1502` from
  Kali's `10.77.20.1` address, and check the HMI command's simulator IP, port,
  and unit ID. The HMI retries after connection errors.
- **Lab guest has no internet access:** Check its default gateway is the Kali
  address on that network, Kali has a working default route on its uplink,
  IPv4 forwarding and NAT rules are active, and the upstream network permits
  Kali's egress. Also verify the guest's DNS configuration.
- **TCP connects but Modbus errors:** Check Slave ID `1`, FC 2 input range
  offset `0` length `6`, and FC 5 coil offsets `0` through `4`.
- **No traffic appears on port 502:** This lab intentionally uses `1502`.
  The simulator and Remote Device must use the same port.



## References

- [OpenPLC Editor overview](https://edge.autonomylogic.com/docs/openplc-editor/overview/)
- [OpenPLC Modbus Remote Device](https://edge.autonomylogic.com/docs/openplc-editor/communication/modbus/client)
- [OpenPLC variables editor](https://edge.autonomylogic.com/docs/openplc-editor/working-with-variables/variables-editor)
- [Connecting to a vPLC](https://edge.autonomylogic.com/docs/openplc-editor/connecting-to-runtimes)
- [Building a project](https://edge.autonomylogic.com/docs/openplc-editor/building-deploying/project-compilation)
- [Proxmox VE SDN documentation](https://pve.proxmox.com/pve-docs/chapter-pvesdn.html)
