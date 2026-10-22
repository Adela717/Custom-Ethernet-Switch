# Custom Ethernet Switch

A software implementation of a Layer 2 Ethernet switch developed in Python.

The switch supports MAC address learning, frame forwarding, VLAN tagging for access and trunk ports, and a simplified Spanning Tree Protocol for root bridge election and loop prevention. The network topology is simulated using Mininet, while Wireshark can be used for packet inspection and debugging.

## Features

- Dynamic MAC address learning
- Unicast and broadcast frame forwarding
- VLAN support for access and trunk ports
- Simplified Spanning Tree Protocol
- Root bridge election and loop prevention
- Custom Wireshark dissector for STP packets

## Running

```bash
sudo python3 checker/topo.py
```

This will open 9 terminals, 6 hosts and 3 for the switches. On the switch terminal you will run 

```bash
make run_switch SWITCH_ID=X # X is 0,1 or 2
```

The hosts have the following IP addresses.
```
host0 192.168.1.1
host1 192.168.1.2
host2 192.168.1.3
host3 192.168.1.4
host4 192.168.1.5
host5 192.168.1.6
```

We will be testing using the ICMP. For example, from host0 we will run:

```
ping 192.168.1.2
```

Note: We will use wireshark for debugging. From any terminal you can run `wireshark&`.
