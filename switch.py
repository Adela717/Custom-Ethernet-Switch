#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

def create_hpdu(mac_sender):
    dst_mac = b'\xff\xff\xff\xff\xff\xff'

    ethertype = struct.pack('!H', 0x0800)
    payload = bytes([255])

    frame = dst_mac + mac_sender + ethertype + payload

    return frame

def send_hpdu(interfaces):
    while True:
        mac_sender = get_switch_mac()
        packet = create_hpdu(mac_sender)
        for o in interfaces:
            send_to_link(o, len(packet), packet)
        time.sleep(1)

def create_ppdu(mac_sender, switch_priority, port_no, seq, root_bridge_id, root_path):
    dst_mac = b'\x01\x80\xc2\x00\x00\x00'

    llc_length = struct.pack('!H', 56)

    dsap = b'\x42'
    ssap = b'\x42'
    control = b'\x03'
    llc_header = dsap + ssap + control

    protocol_id = struct.pack('!H', 0x0002)
    protocol_version = b'\x00'
    ppdu_type = b'\x80'
    seq_number = struct.pack('!I', seq)
    ppdu_header = protocol_id + protocol_version + ppdu_type + seq_number

    flags = b'\x00'
    bridge_id = struct.pack('!H', switch_priority) + mac_sender
    root_path_cost = struct.pack('!I', root_path)
    port_id = struct.pack('!H', (switch_priority & 0xF) << 12 | port_no)
    message_age = struct.pack('!H', 0x0000)
    max_age = struct.pack('!H', 40)
    hello_time = struct.pack('!H', 2)
    forward_delay = struct.pack('!H', 4)

    ppdu_config = flags + root_bridge_id + root_path_cost + bridge_id + port_id + message_age + max_age + hello_time + forward_delay

    frame = dst_mac + mac_sender + llc_length + llc_header + ppdu_header + ppdu_config

    return frame

def send_ppdu(interfaces, switch_priority):
    mac_sender = get_switch_mac()
    bridge_id = struct.pack('!H', switch_priority) + mac_sender
        
    for o in interfaces:
        packet = create_ppdu(mac_sender, switch_priority, int(o), 0, bridge_id, 0)
        send_to_link(o, len(packet), packet)

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]

    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    vlan_tci = -1
    # Check for VLAN tag (0x8200 in network byte order is b'\x82\x00')

    is_hpdu = False
    if ether_type == 0x0800 and len(data) >= 15 and data[14] == 255:
        is_hpdu = True

    is_ppdu = False
    ppdu_multicast = b'\x01\x80\xc2\x00\x00\x00'
    if dest_mac == ppdu_multicast:
        is_ppdu = True

    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id, vlan_tci, is_hpdu, is_ppdu

def create_vlan_tag(ext_id, vlan_id):
    # Use EtherType = 8200h for our custom 802.1Q-like protocol.
    # PCP and DEI bits are used to extend the original VID.
    #
    # The ext_id should be the sum of all nibbles in the MAC address of the
    # host attached to the access port. Ignore the overflow in the 4-bit
    # accumulator.
    #
    # NOTE: Include these 4 extensions bits only in the check for unicast
    #       frames. For multicasts, assume that you're dealing with 802.1Q.
    return struct.pack('!H', 0x8200) + \
           struct.pack('!H', ((ext_id & 0xF) << 12) | (vlan_id & 0x0FFF))

def function_on_different_thread():
    while True:
        time.sleep(1)

def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]
    MAC_Table = {}
    my_switch = {}
    port_state = {}

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    t_hpdu = threading.Thread(target=send_hpdu, args=(interfaces,), daemon=True)
    t_hpdu.start()

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))


    # Example of running a function on a separate thread.
    t = threading.Thread(target=function_on_different_thread)
    t.start()

    # Printing interface names
    for i in interfaces:
        print(get_interface_name(i))

    file = f"configs/switch{switch_id}.cfg"

    with open(file, 'r') as f:
        lines = f.readlines()

    switch_priority = int(lines[0].strip())

    for line in lines[1:]:
        line = line.strip()
        interface_name, vlan_or_trunk = line.split()
        my_switch[interface_name] = vlan_or_trunk

    t_ppdu = threading.Thread(target=send_ppdu, args=(interfaces, switch_priority, ), daemon=True)
    t_ppdu.start()

    my_mac = get_switch_mac()
    my_mac_int = int.from_bytes(my_mac, byteorder='big')
    my_bid = switch_priority << 48 | my_mac_int
    my_root_bridge = switch_priority << 48 | my_mac_int
    start_port_assignment = False
    ppdu_count = 0

    for i in range(0, 4):
        port_state[i] = 1

    my_cost = float('inf')

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].

        interface, data, length = recv_from_any_link()
        my_interface_name = get_interface_name(interface)

        dest_mac, src_mac, ethertype, vlan_id, vlan_tci, is_hpdu, is_ppdu = parse_ethernet_header(data)

        if is_hpdu == True:
            continue

        if is_ppdu == True:
         
            extracted_bid_data = data[26:34]
            extracted_bid = int.from_bytes(extracted_bid_data, byteorder='big')

            if(my_root_bridge > extracted_bid):
                my_root_bridge = extracted_bid

            extracted_seq_data = data[21:25]
            extracted_seq = int.from_bytes(extracted_seq_data, byteorder='big')

            extracted_cost_data = data[34:38]
            extracted_cost = int.from_bytes(extracted_cost_data, byteorder='big')

            extracted_port_data = data[46:48]
            extracted_port = int.from_bytes(extracted_port_data, byteorder='big')

            if(extracted_cost + 19 < my_cost) :
                my_cost = extracted_cost + 19

            if ppdu_count >= 2:
                bid_bytes = extracted_bid.to_bytes(8, byteorder="big")

            # porturile conectate direct la root bridge devin forwarding
            if ppdu_count >= 2 and extracted_seq == 0:
                port_state[interface] = 1
                mac_sender = get_switch_mac()
                for o in interfaces:
                    if o != interface:
                        packet = create_ppdu(mac_sender, switch_priority, int(o), extracted_seq + 1, bid_bytes, extracted_cost + 19)
                        send_to_link(o, len(packet), packet)

            # tiebreakers
            if ppdu_count >= 2 and extracted_seq != 0:
                my_port_id = (switch_priority & 0xF) << 12 | interface
                if my_cost > extracted_cost:
                    port_state[interface] = 0
                
                elif my_cost == extracted_cost:
                    if my_bid > extracted_bid:
                        port_state[interface] = 0
                        print(f"mor")

                elif my_cost == extracted_cost and my_bid == extracted_bid:
                    if my_port_id > extracted_port:
                        port_state[interface] = 0


            ppdu_count += 1

            if ppdu_count >= 2 and my_bid == my_root_bridge and start_port_assignment == False:
                mac_sender = get_switch_mac()
                bridge_id = struct.pack('!H', switch_priority) + mac_sender
            
                for o in interfaces:
                    packet = create_ppdu(mac_sender, switch_priority, int(o), 0, bridge_id, 0)
                    send_to_link(o, len(packet), packet)

                for i in range(0, 4):
                    port_state[i] = 1
                start_port_assignment = True

            continue

        sum_nibbles_src = 0
        for b in src_mac:
            high_nibble = b >> 4
            low_nibble = b & 0x0F
            sum_nibbles_src += high_nibble + low_nibble

        sum_nibbles_dst = 0
        for b in dest_mac:
            high_nibble = b >> 4
            low_nibble = b & 0x0F
            sum_nibbles_dst += high_nibble + low_nibble

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(5, 10) + data[12:]

        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')

        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        if port_state[interface] == 0:
            continue
        # TODO: Implement forwarding with learning
        # TODO: Implement VLAN support
        # TODO: Implement STP support
        MAC_Table[src_mac] = interface

        if dest_mac in MAC_Table:
            next_hop = MAC_Table[dest_mac]
            next_interface = get_interface_name(next_hop)

            for i in my_switch:
                if i == next_interface:
                    next_vlan = my_switch[i]

        last_vlan = my_switch[my_interface_name]

        if (dest_mac.lower() != 'ff:ff:ff:ff:ff:ff' and dest_mac not in MAC_Table) or dest_mac.lower() == 'ff:ff:ff:ff:ff:ff':
            for o in interfaces:
                if o != interface:
                    next_vlan2 = my_switch[get_interface_name(o)]
                    if next_vlan2 == 'T' and last_vlan == 'T' and port_state[o] == 1:
                        send_to_link(o, length, data)

                    elif next_vlan2 == 'T' and last_vlan != 'T' and port_state[o] == 1:
                        new_vlan_id = int(my_switch[my_interface_name])

                        tagged_frame = data[0:12] + create_vlan_tag(0, new_vlan_id) + data[12:]
                        send_to_link(o, len(tagged_frame), tagged_frame)

                    elif next_vlan2 != 'T' and last_vlan == 'T' and port_state[o] == 1:
                        new_frame = data[0:12] + data[16:]

                        if int(vlan_id) == int(next_vlan2):
                            send_to_link(o, len(new_frame), new_frame)
            continue
        

        if next_vlan == 'T' and last_vlan == 'T':
            if next_hop != interface and port_state[next_hop] == 1:
                send_to_link(next_hop, length, data)
                continue
            
        elif next_vlan == 'T' and last_vlan != 'T':
            new_ext_id = sum_nibbles_src & 0xF
            new_vlan_id = int(my_switch[my_interface_name])

            tagged_frame = data[0:12] + create_vlan_tag(new_ext_id, new_vlan_id) + data[12:]
            if MAC_Table[dest_mac] != interface and port_state[MAC_Table[dest_mac]] == 1:
                send_to_link(MAC_Table[dest_mac], len(tagged_frame), tagged_frame)
                continue

        elif next_vlan != 'T' and last_vlan == 'T':
            new_frame = data[0:12] + data[16:]
            next_hop = MAC_Table[dest_mac]
            
            next_ext_id = sum_nibbles_dst & 0xF
            ext_id = vlan_tci >> 12

            if int(vlan_id) == int(next_vlan) and int(ext_id) == int(next_ext_id) and port_state[next_hop] == 1:
                send_to_link(next_hop, len(new_frame), new_frame)
                continue
            
            else:
                continue

        # data is of type bytes.
        # send_to_link(i, length, data)

if __name__ == "_main_":
    main()