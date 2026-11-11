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
| **Option A — OpenPLC Runtime v4** | OpenPLC Runtime v4 plus a Windows Control VM running the OpenPLC Editor | Configure a Modbus Remote Device, deploy a Structured Text program, and observe how PLC logic reads inputs and controls outputs. |
| **Option B — Python Modbus/TCP** | A Debian/Ubuntu controller LXC and a Windows Control VM running the operator HMI | The Windows Control VM starts/stops the Python controller and operates the simulated tank. No OpenPLC Runtime or Editor is required. |

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

The same simulator, Kali gateway/capture host, read-only monitor, and Modbus
I/O map are used in both options. The selected controller is a Modbus client.
Option B additionally has an interactive operator HMI on its Windows Control VM.

## Shared Kali gateway, capture, and HMI setup

On Kali, identify the interface names for its internet uplink and the two
shared lab networks, `PLC-LAB` and `SIM-LAB`:

```bash
ip -br address
ip route
```

### Optional 100 ms egress delay on Kali `eth1`

This lab setup uses a 100 ms egress delay on Kali's `eth1` interface. Apply it
after confirming that `eth1` is the intended lab interface:

```bash
sudo tc qdisc replace dev eth1 root netem delay 100ms
```

Verify the active queueing discipline:

```bash
tc qdisc show dev eth1
```

This delays packets leaving `eth1`; it affects all egress traffic on that
interface, not only Modbus. The setting is temporary and must be reapplied
after a reboot. To remove it:

```bash
sudo tc qdisc del dev eth1 root
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
from the lab subnets out its internet uplink. The following example uses
`nftables`. Replace the interface names with those shown by `ip -br address`.
The base chain has a default-drop policy; use it only on a dedicated Kali lab
gateway. If Kali routes other networks, integrate equivalent rules into its
existing nftables policy instead of adding a competing default-drop chain.

Create `/etc/nftables.d/plc-lab.nft` with the following content:

```nft
define WAN_IF = "your-internet-interface"
define PLC_IF = "your-plc-lab-interface"
define SIM_IF = "your-sim-lab-interface"

table inet plc_lab_filter {
    chain forward {
        type filter hook forward priority filter; policy drop;

        ct state established,related counter accept

        iifname $PLC_IF oifname $WAN_IF ip saddr 10.77.10.0/24 counter accept
        iifname $SIM_IF oifname $WAN_IF ip saddr 10.77.20.0/24 counter accept

        iifname $PLC_IF oifname $SIM_IF ip saddr { 10.77.10.10, 10.77.10.20 } ip daddr 10.77.20.10 tcp dport 502 ct state new,established counter accept
    }
}

table ip plc_lab_nat {
    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept;

        ip saddr 10.77.10.0/24 oifname $WAN_IF counter masquerade
        ip saddr 10.77.20.0/24 oifname $WAN_IF counter masquerade
    }
}
```

In the nftables configuration file `/etc/nftables.conf`, add this include
without removing existing rules or includes:

```nft
include "/etc/nftables.d/plc-lab.nft"
```

Check the configuration before loading it:

```bash
sudo nft -c -f /etc/nftables.conf
```

On a dedicated lab gateway, apply the lab rules without flushing other
tables:

```bash
sudo nft -f /etc/nftables.d/plc-lab.nft
```

For persistence, use the firewall manager already responsible for Kali.
If Kali's `nftables` systemd service is the sole firewall manager, ensure
`/etc/nftables.conf` includes the lab file and preserves any other required
rules before enabling that service. Then enable it to load the configuration
at boot:

```bash
sudo systemctl enable nftables
```

Do not start a second firewall manager or apply a configuration containing
`flush ruleset` on a shared gateway.

If reloading after changing the lab file, remove only the two lab-owned
tables before reapplying; do not flush the whole ruleset:

```bash
sudo nft delete table inet plc_lab_filter
sudo nft delete table ip plc_lab_nat
sudo nft -f /etc/nftables.d/plc-lab.nft
```

These are example rules, not a complete firewall policy. The forwarding
chain permits established return traffic, controller and simulator outbound
internet traffic, and the controller-to-simulator TCP `502` flow. Its
default-drop policy blocks other forwarded traffic, including new
internet-to-lab connections. Do not expose guest management services or
enable unrestricted forwarding. The HMI connects locally from Kali's SIM-LAB
address `10.77.20.1`, so it does not need a forwarded rule.

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
sudo tcpdump -ni any '(host 10.77.10.10 or host 10.77.10.20) and host 10.77.20.10 and tcp port 502'
```

Alternatively, open Wireshark on Kali, capture on its lab interfaces, and use
this display filter:

```text
tcp.port == 502
```

If Wireshark does not decode port `502` as Modbus/TCP automatically, select a
packet and use **Analyze > Decode As** to decode that TCP port as Modbus/TCP.

Start the shared read-only browser HMI on Kali in another terminal:

```bash
python3 simulator_monitor.py --host 10.77.20.10 --port 502 --unit-id 1
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
python3 simulator_monitor.py --host 10.77.20.10 --port 502 --unit-id 1 --web-host "$HMI_BIND_IP"
```

Set `HMI_BIND_IP` to the Kali interface IP reachable from the authorized
workstation, then browse to that IP on port `8080`. Do not bind to all
interfaces or expose this unauthenticated display outside the isolated lab.

### Shared simulator setup

On the simulator guest, install Python 3, copy or clone this repository, then
run from the repository directory:

```bash
python3 factoryio_simulator.py --host 0.0.0.0 --port 502 --unit-id 1
```

Use Python 3.10 or newer for the simulator and HMI. The simulator also starts
a process-reset HTTP endpoint bound only to `127.0.0.1:8081`; it is not
reachable through the lab network. TCP port `502` is privileged on Linux;
grant the simulator service only the `CAP_NET_BIND_SERVICE` capability using
the container or service manager, rather than running the program as root.

Keep the process running. Its prompt accepts `status`, `start`, `box`,
`door open`, `door close`, `auto on`, `auto off`, and `reset`. For this setup,
leave automatic box emission enabled. A box appears after about five seconds.
The simulator does not print periodic process summaries or general process
events. It prints each valid FC 15 request with the named output states.
Enter `status` at the `sim>` prompt to request a current process snapshot.
When updating an existing simulator container, replace its
`factoryio_simulator.py` with the updated project copy and restart the
simulator process; editing the workstation copy does not update a running
container.

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

Permit inbound TCP port `502` to the simulator from the controller at
`10.77.10.10` (forwarded through Kali), the Option B Control VM at
`10.77.10.20` (forwarded through Kali), and the read-only HMI at `10.77.20.1`
in any guest or Proxmox firewall that applies.

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

For internet egress from the Option A management subnet, make these
Option-A-only additions in `/etc/nftables.d/plc-lab.nft`. Add the interface
definition alongside the other `define` statements at the top of the file:

```nft
define MGMT_IF = "your-mgmt-interface"
```

Add this rule inside `chain forward`, before its closing brace:

```nft
iifname $MGMT_IF oifname $WAN_IF ip saddr 10.77.0.0/24 counter accept
```

Also add the following Option-A-only rule inside the `postrouting` chain:

```nft
ip saddr 10.77.0.0/24 oifname $WAN_IF counter masquerade
```

Include these additions before validating/loading the nftables configuration.
They permit the Control VM and Runtime management subnet to use Kali for
outbound internet egress; return traffic is covered by the established-state
rule. Do not add a new inbound WAN-to-MGMT accept rule.

The Runtime has two NICs, so configure its routes against the interface on
the matching subnet:

- Default route for management and internet egress: via Kali MGMT
  `10.77.0.1` on the Runtime MGMT NIC (`10.77.0.10/24`).
- Specific route to the simulator subnet `10.77.20.0/24`: via Kali
  PLC-LAB `10.77.10.1` on the Runtime PLC-LAB NIC (`10.77.10.10/24`).

Do **not** set `10.77.10.1` as the default gateway on the MGMT NIC. The
gateway must be directly reachable on the subnet of the interface using it.
For example, first identify the Runtime's actual interface names:

```bash
ip -br address
ip route
```

Then, substituting the names shown for the Runtime's MGMT and PLC-LAB NICs,
apply these temporary routes:

```bash
MGMT_IF="runtime-mgmt-interface"
PLC_IF="runtime-plc-lab-interface"

sudo ip route replace default via 10.77.0.1 dev "$MGMT_IF"
sudo ip route replace 10.77.20.0/24 via 10.77.10.1 dev "$PLC_IF"
```

These `ip route` commands do not persist across reboot. Make the same
gateway and subnet-route settings persistent using the network configuration
manager installed in the Runtime guest. Configure the Control VM's default
gateway as `10.77.0.1` and the simulator's as `10.77.20.1`.

Verify that each destination selects the intended Runtime interface and
gateway:

```bash
ip route get 8.8.8.8
ip route get 10.77.20.10
```

The public destination should use the default route via `10.77.0.1` on MGMT;
the simulator destination should use `10.77.10.1` on PLC-LAB. For the
documented interface layout, the route table should be equivalent to:

```text
default via 10.77.0.1 dev <MGMT_IF>
10.77.0.0/24 dev <MGMT_IF> src 10.77.0.10
10.77.10.0/24 dev <PLC_IF> src 10.77.10.10
10.77.20.0/24 via 10.77.10.1 dev <PLC_IF>
```

The management and process paths are distinct:

```text
Editor on Control VM -> MGMT -> OpenPLC Runtime management NIC
OpenPLC Runtime data NIC -> Kali PLC-LAB -> Kali SIM-LAB -> simulator
Kali HMI -> Kali SIM-LAB -> simulator (read-only polling)
Lab internet egress -> Kali's attached network -> Kali WAN NIC
```

#### Option A troubleshooting

- **Runtime has no internet access:** Check `ip -br address` and
  `ip route get 8.8.8.8` on the Runtime. Its MGMT NIC `10.77.0.10/24` must
  use Kali MGMT `10.77.0.1` as the default gateway. If the default route
  instead uses `10.77.10.1` on the MGMT interface, replace it using the
  commands above; `10.77.10.1` belongs on the separate PLC-LAB NIC and is
  only the next hop for `10.77.20.0/24`. Then verify Kali's WAN route,
  IPv4 forwarding, and the Option A MGMT forwarding and masquerade rules.
  On Kali, inspect `sudo nft list chain inet plc_lab_filter forward` and
  `sudo nft list chain ip plc_lab_nat postrouting` while retrying the
  connection; increasing rule counters help locate which hop is failing.
  If another firewall manager controls Kali's nftables rules, inspect that
  active configuration and integrate the lab rules there.
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
   makes the Modbus connection to `10.77.20.10:502` through Kali.

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
nc -vz -w 3 10.77.20.10 502
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
   **Port** to `502`, **Slave ID** to `1`, and **Timeout (ms)** to `1000`.
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

   This OpenPLC example needs the first six inputs. The HMI independently
   polls the additional `BoxPresent` input at address `6` so it only animates
   a box when one is actually in the process.

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
   refreshes the seven discrete inputs and five coils, renders an approximate
   process overview, and sends FC 2 and FC 1 read requests only. Its polling
   appears in the capture as a separate TCP connection from Kali.
3. Start the Kali capture, then run the PLC. In Wireshark, look for periodic
   FC 2 requests and responses. The configured OpenPLC read group polls the
   first six inputs; the HMI polls all seven.
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

### Ladder-to-Structured-Text recreation

[`OPTION_A_LADDER_RECREATION.st`](./OPTION_A_LADDER_RECREATION.st) is the
Structured Text body corresponding to the supplied ladder screenshots. The
Autonomy Edge ST editor keeps declarations in its Variables Table, so add the
variables there before pasting the file body into a Program POU. This follows
the editor's [ST basics](https://edge.autonomylogic.com/docs/openplc-editor/programming-languages/structured-text/st-basics),
[examples](https://edge.autonomylogic.com/docs/openplc-editor/programming-languages/structured-text/st-examples),
and [editor workflow](https://edge.autonomylogic.com/docs/openplc-editor/programming-languages/structured-text/st-editor):

| Class | Name | Type | Location / initial value |
| --- | --- | --- | --- |
| Local | `StartButton` | BOOL | `StartButton` |
| Local | `SafetyDoor` | BOOL | `SafetyDoorClosed` |
| Local | `BoxAtSensor` | BOOL | `BoxAtSensor` |
| Local | `Picker_Holding_Box` | BOOL | `RobotDetected` |
| Local | `Picker_Moving_Z` | BOOL | `MovingZ` |
| Local | `Picker_Rotating` | BOOL | `Rotating` |
| Local | `Box_Not_Waiting` | BOOL | `FALSE` (assigned in ST body) |
| Local | `Conveyor_Move` | BOOL | `Conveyor` |
| Local | `Picker_Grab` | BOOL | `Grab` |
| Local | `Picker_Move_Down` | BOOL | `ExtendZ` |
| Local | `Picker_Rotate_CW` | BOOL | `RotateCW` |
| Local | `Picker_Rotate_CCW` | BOOL | `RotateCCW` |
| Local | `Run` | BOOL | `FALSE` |
| Local | `Picker_Holding_Box_Previous` | BOOL | `FALSE` |
| Local | `Picker_Moving_Z_Previous` | BOOL | `FALSE` |
| Local | `Picker_Rotating_Previous` | BOOL | `FALSE` |
| Local | `Picker_Holding_Box_Rising` | BOOL | `FALSE` |
| Local | `Picker_Moving_Z_Falling` | BOOL | `FALSE` |
| Local | `Picker_Rotating_Falling` | BOOL | `FALSE` |

The `.st` body implements the remaining N/P contacts as one-scan falling/rising
edge pulses using previous-scan BOOL variables, and implements Set/Reset coils
by assigning `TRUE` or `FALSE` only when their rungs fire. It also makes these
corrections needed for the provided simulator: `Run` has a seal-in branch so a
250 ms `StartButton` pulse is retained, `Box_Not_Waiting` is derived as
`NOT BoxAtSensor`, and pickup uses the active `BoxAtSensor` level rather than
an edge pulse. The level condition ensures the picker starts if the PLC starts
after a box has already reached the sensor.

In the variable table screenshot, the safety input location appears as
`SaftyDoorClose`. That does not match the simulator's exact input alias
`SafetyDoorClosed`; correct the remote-device alias/location in the editor.
If the safety input is false or unresolved, the seal-in rung intentionally
drops `Run`.

With `BoxAtSensor=ON`, `Run=ON`, and `Picker_Holding_Box=OFF`, the expected
outputs are `Conveyor_Move=OFF`, `Picker_Move_Down=ON`, and `Picker_Grab=ON`.
If the simulator reports `BoxAtSensor=ON` while the PLC continues writing
`Conveyor=ON`, verify the PLC's live values for those three variables and that
the uploaded program and FC 2 offset-2 alias are current. The simulator's
status command reports its actual coil state; use it alongside the OpenPLC
live variable table to distinguish a stale log line from a current write.

Each FC 15 packet is a real Modbus Write Multiple Coils request. The simulator
logs every request, even when it writes the same coil values as the preceding
request. The all-OFF values shown in the controller log mean it is actively
commanding all five outputs OFF; they are not merely read responses or proof
that an actuator changed state. Repeated FC 15 packets indicate the OpenPLC
output group is issuing repeated writes. Set that group's cycle time to at
least 100 ms (the setup above uses 100 ms) to limit traffic. Do not slow the
PLC task itself to fix Modbus traffic; that changes edge detection and process
response timing. Confirm the write interval from packet timestamps in
Wireshark.

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
       /                 \                             |
Windows Control VM  Python controller LXC         Simulator LXC
10.77.10.20/24          10.77.10.10/24              10.77.20.10/24
```

| Guest/interface | Network | Address and gateway/route |
| --- | --- | --- |
| Kali PLC-LAB NIC | `PLC-LAB` | `10.77.10.1/24` |
| Python controller LXC | `PLC-LAB` | `10.77.10.10/24`, gateway `10.77.10.1` |
| Option B Control VM | `PLC-LAB` | `10.77.10.20/24`, gateway `10.77.10.1` |
| Kali SIM-LAB NIC | `SIM-LAB` | `10.77.20.1/24` |
| Simulator NIC | `SIM-LAB` | `10.77.20.10/24`, gateway `10.77.20.1` |
| Kali WAN NIC | Internet-facing Proxmox bridge | Upstream DHCP/static address; Kali default route |

Create separate `PLC-LAB` and `SIM-LAB` networks. Kali needs NICs on both,
plus its WAN NIC; do not attach the controller, Control VM, or simulator
directly to the internet-facing bridge. The Option B Control VM is a normal
operator workstation on `PLC-LAB`; it runs the interactive HMI but does not
run OpenPLC Runtime or Editor. No separate MGMT network is required.
Configure the controller and Control VM default gateways as `10.77.10.1`
and the simulator gateway as `10.77.20.1`. Modbus traffic from both the
controller and Control VM to the simulator must pass through Kali; do not add
a direct controller-to-simulator interface or bypass route.

1. Create a Debian/Ubuntu LXC named `python-controller` and attach its NIC to
   `PLC-LAB`. Configure `10.77.10.10/24` with default gateway `10.77.10.1`.
   Create/attach the Option B Windows Control VM to `PLC-LAB` at
   `10.77.10.20/24`, gateway `10.77.10.1`. Do not reuse the Option A Control
   VM's `MGMT` address for this interface.
2. Install Python 3.10 or newer and `openssh-server` in the simulator and
   controller containers. On the Windows Control VM, install Python 3.10 or
   newer, copy the repository to a working directory, and keep its browser and
   local Python environment accessible to the operator. The Linux service files
   in this repo are not the default Control VM launch method.

   In each Linux LXC, install Python and SSH and prepare the service account:

   ```bash
   sudo apt-get update
   sudo apt-get install -y python3 openssh-server
   sudo useradd --create-home --shell /bin/bash otlab
   sudo passwd otlab
   sudo install -d -o otlab -g otlab /opt/factoryio
   sudo systemctl enable --now ssh
   ```

   On the Windows Control VM, install Python 3 and copy the project files to a
   local directory such as `C:\FactoryIO` or a work folder on the VM. The
   Windows operator runs `optionb_control_hmi.py` by opening a PowerShell window
   in that directory and launching the script with Python. Stop any copies
   currently running in terminals before starting the HMI again.

   Transfer these source files from the repository to the Linux guests using
   the Proxmox console or an approved file-transfer method. The destination
   directory `/opt/factoryio` was created above:

   | Guest | Files to install in `/opt/factoryio` |
   | --- | --- |
   | Simulator LXC | `factoryio_simulator.py`, `reset_lab_process.py` |
   | Controller LXC | `factoryio_modbus_controller.py` |

   Set each source file's owner to `otlab:otlab` and ensure it is readable by
   that account. The Windows Control VM needs both `optionb_control_hmi.py`
   and `simulator_monitor.py` in the same local directory because the HMI
   imports the monitor module.
3. Install the matching service unit from this repository for the Linux
   guests only:

   - Simulator LXC: copy `systemd/factoryio-simulator.service` to
     `/etc/systemd/system/factoryio-simulator.service`.
   - Controller LXC: copy `systemd/factoryio-controller.service` to
     `/etc/systemd/system/factoryio-controller.service`.

   Transfer each unit file from the repository to its guest, install it at
   the destination shown above, then run `sudo systemctl daemon-reload` in
   both Linux guests. Enable each service so it starts after a guest reboot:

   ```bash
   sudo systemctl enable factoryio-simulator.service
   ```

   Run the corresponding command in the controller LXC:

   ```bash
   sudo systemctl enable factoryio-controller.service
   ```

   The Windows Control VM does not use `systemd`; launch
   `optionb_control_hmi.py` from PowerShell as shown below. Generate
   a strong random API token on a trusted administration workstation:

   ```bash
   openssl rand -hex 32
   ```

   Store the generated value in `/etc/factoryio/controller.env` on the
   controller LXC. The Windows HMI does not use or need
   `/etc/factoryio/control-hmi.env`; its token is entered into the PowerShell
   process when launching it, as shown in step 9. On the controller LXC, create
   the directory and edit its environment file with the same generated token
   on a line like `FACTORYIO_CONTROL_TOKEN=<generated-value>`:

   ```bash
   sudo install -d -o root -g otlab -m 0750 /etc/factoryio
   sudoedit /etc/factoryio/controller.env
   ```

   Set the Linux controller file's owner/group to `root:otlab` and mode to
   `0640`:

   ```bash
   sudo chown root:otlab /etc/factoryio/controller.env
   sudo chmod 0640 /etc/factoryio/controller.env
   ```

   Keep the token out of source files and screenshots. The controller API
   listens on `10.77.10.10:8082`; its bearer token is sent
   over HTTP, so keep the PLC-LAB isolated and permit that port only from
   `10.77.10.20`. The HMI itself binds to the Windows Control VM loopback at
   `127.0.0.1:8083`.

   The simulator
   unit runs as `otlab` and receives only `CAP_NET_BIND_SERVICE` to bind TCP
   `502`. The controller unit handles SIGINT on stop so it can turn its coils
   off before exiting. It starts with the production sequence stopped; the
   HMI enables/disables that sequence through the controller API.
4. Configure SSH access from Kali to `otlab@10.77.20.10` and
   `otlab@10.77.10.10` using a dedicated public key. Keep the private key on
   Kali. Restrict SSH ingress on the simulator to Kali's SIM-LAB address
   `10.77.20.1`, and on the controller to Kali's PLC-LAB address
   `10.77.10.1`. On Kali, create the key and display its public half:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/factoryio-optionb
   cat ~/.ssh/factoryio-optionb.pub
   ```

   From each container's Proxmox console, create the authorized-keys file,
   paste the complete public-key line, and press Ctrl+D:

   ```bash
   sudo install -d -o otlab -g otlab -m 0700 /home/otlab/.ssh
   sudo tee /home/otlab/.ssh/authorized_keys >/dev/null
   ```

   Then set ownership and permissions:

   ```bash
   sudo chown otlab:otlab /home/otlab/.ssh/authorized_keys
   sudo chmod 0600 /home/otlab/.ssh/authorized_keys
   ```

   In each container, add a sudoers drop-in with
   `sudo visudo -f /etc/sudoers.d/otlab-factoryio` allowing `otlab` to run
   only these service-management commands without a password:

   ```sudoers
   otlab ALL=(root) NOPASSWD: /usr/bin/systemctl start factoryio-simulator.service, /usr/bin/systemctl stop factoryio-simulator.service, /usr/bin/systemctl restart factoryio-simulator.service, /usr/bin/systemctl is-active factoryio-simulator.service
   ```

   Use `factoryio-controller.service` instead of
   `factoryio-simulator.service` in the controller container's rule. Validate
   the file with `sudo visudo -cf /etc/sudoers.d/otlab-factoryio`.
5. On the controller LXC, restrict inbound TCP `8082` to the Control VM
   (`10.77.10.20`) using its host firewall. For example, with UFW:

   ```bash
   sudo ufw default deny incoming
   sudo ufw allow from 10.77.10.1 to any port 22 proto tcp
   sudo ufw allow from 10.77.10.20 to any port 8082 proto tcp
   sudo ufw enable
   sudo ufw status numbered
   ```

   Review existing rules before enabling UFW on a guest; do not overwrite
   another firewall policy. Ensure no broader allow rule permits TCP `8082`
   from other sources. Keep SSH ingress limited to Kali as described above.
   On Kali, copy `start_option_b_from_kali.sh` from this repository and make
   it executable with `chmod +x start_option_b_from_kali.sh`. Test both
   targets with the dedicated key:

   ```bash
   ssh -i ~/.ssh/factoryio-optionb otlab@10.77.10.10 true
   ssh -i ~/.ssh/factoryio-optionb otlab@10.77.20.10 true
   ```

   Set `SSH_IDENTITY_FILE=~/.ssh/factoryio-optionb` when invoking the
   launcher, or load the key into the agent with `ssh-add` (required if the
   private key has a passphrase). On first connection, verify the SSH host
   keys interactively before using the launcher's non-interactive SSH calls.
6. Keep the simulator at `10.77.20.10:502`, unit ID `1`. From Kali, start,
   inspect, and stop the Option B services with:

   ```bash
   SSH_IDENTITY_FILE=~/.ssh/factoryio-optionb ./start_option_b_from_kali.sh start
   SSH_IDENTITY_FILE=~/.ssh/factoryio-optionb ./start_option_b_from_kali.sh status
   SSH_IDENTITY_FILE=~/.ssh/factoryio-optionb ./start_option_b_from_kali.sh stop
   ```

   The `start` command starts the simulator and the controller service. The
   controller service remains active but its production sequence is stopped
   until an operator presses Start in the Control VM HMI. The `restart`
   command restarts the services without pulsing simulator StartButton.
   `stop` stops the controller service before the simulator. The script
   changes no VNet, route, or Modbus forwarding settings.
7. On Kali, allow TCP `502` from the controller and Control VM through to the simulator and
   established return traffic. The common Kali gateway section has the
   example forwarding rule; use Kali's `PLC-LAB` and `SIM-LAB` interface
   names. Capture with:

   ```bash
   sudo tcpdump -ni any '(host 10.77.10.10 or host 10.77.10.20) and host 10.77.20.10 and tcp port 502'
   ```

8. From the controller LXC and the Windows Control VM, verify route and TCP reachability:

   On Linux:

   ```bash
   ip route get 10.77.20.10
   nc -vz -w 3 10.77.20.10 502
   ```

   On Windows PowerShell:

   ```powershell
   route print
   Test-NetConnection 10.77.20.10 -Port 502
   ```

   The route must go through `10.77.10.1` and the TCP connection must succeed.
9. On the Windows Control VM, launch the operator HMI from a PowerShell session
   in the project directory:

   ```powershell
   $secureToken = Read-Host "Controller API token" -AsSecureString
   $env:FACTORYIO_CONTROL_TOKEN = [System.Net.NetworkCredential]::new("", $secureToken).Password
   Set-Location C:\FactoryIO
   py -3 .\optionb_control_hmi.py --modbus-host 10.77.20.10 --modbus-port 502 --unit-id 1 --controller-api http://10.77.10.10:8082 --host 127.0.0.1 --port 8083
   ```

   Replace `C:\FactoryIO` if you chose a different project directory. The
   token prompt is required in each new PowerShell session; the HMI reads the
   token from its process environment. Keep this PowerShell window open while
   using the HMI.

   Open `http://127.0.0.1:8083/` in the Control VM browser. The HMI shows
   controller state and RTU signals; Start and Stop operate the controller
   sequence. Tank buttons write only the tank's FC 05 coils (addresses 5–8).
   The existing `simulator_monitor.py` on Kali remains a separate read-only
   HMI.
10. For manual controller diagnosis, run it in the controller LXC with a
    valid `FACTORYIO_CONTROL_TOKEN`, binding the operator API only to its
    PLC-LAB interface:

    ```bash
    set -a
    source /etc/factoryio/controller.env
    set +a
    python3 factoryio_modbus_controller.py --host 10.77.20.10 --port 502 --unit-id 1 --control-host 10.77.10.10 --control-port 8082
    ```

    It remains stopped until a Start request reaches its API; a simulator
    StartButton pulse is no longer the Option B run command. An open safety
    door trips the controller and requires the operator to close the door
    and press Start again. Press Ctrl+C to stop the service process; on
    normal shutdown it attempts to turn its five line coils off.
11. Open the read-only monitor at `http://127.0.0.1:8080/` in Kali's browser.
    The Control VM HMI polls the simulator from `10.77.10.20`; Wireshark can
    distinguish its FC 1/2/4/5 traffic from the controller's FC 2/15 traffic.
    All Modbus exchanges to the simulator route through Kali; Kali is not an
    active Modbus proxy.

This Python option replaces the PLC logic for this introductory exercise. It
does not run an OpenPLC Runtime, execute IEC 61131-3 programs, or connect to
the Editor.

#### Option B troubleshooting

- **Kali launcher cannot connect:** Verify SSH host keys, public-key
  authentication, SSH ingress from Kali's lab-side addresses, and the
  container-specific `otlab` sudoers rule. Check service logs in the
  container with `sudo journalctl -u factoryio-simulator.service` or
  `sudo journalctl -u factoryio-controller.service`.
- **Python controller cannot start:** Check Python 3.10+, simulator host/port,
  Slave ID `1`, and that the simulator is running. The controller exits with
  an error if its Modbus connection or response fails.

## Troubleshooting

- **No packets on Kali:** On the PLC guest, check `ip route get 10.77.20.10`.
  If the next hop is not Kali's `10.77.10.1`, the Modbus flow bypasses Kali.
- **Route works but TCP test fails:** Check that the simulator is listening on
  `0.0.0.0:502`, the simulator IP is correct, and forwarding/firewall rules
  permit the flow.
- **HMI shows disconnected:** Verify the simulator accepts TCP `502` from
  Kali's `10.77.20.1` address, and check the HMI command's simulator IP, port,
  and unit ID. The HMI retries after connection errors.
- **Lab guest has no internet access:** Check its default gateway is the Kali
  address on that network, Kali has a working default route on its uplink,
  IPv4 forwarding and NAT rules are active, and the upstream network permits
  Kali's egress. Also verify the guest's DNS configuration.
- **TCP connects but Modbus errors:** Check Slave ID `1`, FC 2 input range
  offset `0` length `6`, and FC 5 coil offsets `0` through `4`.
- **No traffic appears on port 502:** Verify the simulator and Remote Device
  both use TCP `502`, and that Kali's forwarding rule permits that port.



## References

- [OpenPLC Editor overview](https://edge.autonomylogic.com/docs/openplc-editor/overview/)
- [OpenPLC Modbus Remote Device](https://edge.autonomylogic.com/docs/openplc-editor/communication/modbus/client)
- [OpenPLC variables editor](https://edge.autonomylogic.com/docs/openplc-editor/working-with-variables/variables-editor)
- [Connecting to a vPLC](https://edge.autonomylogic.com/docs/openplc-editor/connecting-to-runtimes)
- [Building a project](https://edge.autonomylogic.com/docs/openplc-editor/building-deploying/project-compilation)
- [Proxmox VE SDN documentation](https://pve.proxmox.com/pve-docs/chapter-pvesdn.html)
