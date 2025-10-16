#!/usr/bin/env python3
import socket
import struct
import sys
import select
import time

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <ON_IP> <ON_TCP_PORT>")
    sys.exit(1)

ON_IP = sys.argv[1]
ON_PORT = int(sys.argv[2])
VN_IP = socket.gethostbyname(socket.gethostname())

tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
tcp_sock.connect((ON_IP, ON_PORT))

udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.bind((VN_IP, 0))  
VN_UDP_PORT = udp_sock.getsockname()[1]

connect_msg = struct.pack('!IH', struct.unpack("!I", socket.inet_aton(VN_IP))[0], VN_UDP_PORT)
tcp_sock.sendall(connect_msg)

print(f"Connected to ON at {ON_IP}:{ON_PORT} from VN {VN_IP}:{VN_UDP_PORT}")

# --- State ---
link_state = {}      
originID = None      
neighbors = set()    
sequence_number = 1
lsp_interval = 15    

last_lsp_time = time.time()

def print_graph():
    if originID:
        state_str = ','.join(f"{k}={v}" for k,v in link_state.items())
        print(f"{originID}: {state_str}")

def send_lsp():
    global sequence_number
    if not originID or not neighbors:
        return
    num_neighbors = len(link_state)
    neighbors_bin = b''
    for n, c in link_state.items():
        neighbors_bin += struct.pack('!cH', n.encode(), c)
    msg = struct.pack(f"!cIB{len(neighbors_bin)}s", originID.encode(), sequence_number, num_neighbors, neighbors_bin)
    sequence_number += 1
    for addr in neighbors:
        udp_sock.sendto(msg, addr)

def handle_link_state(data):
    global originID, link_state
    tuple_size = 9  # name(1)+IP(4)+port(2)+cost(2)
    for i in range(0, len(data), tuple_size):
        chunk = data[i:i+tuple_size]
        if len(chunk) < tuple_size:
            continue
        name, ip_bin, port_bin, cost_bin = struct.unpack('!cIHH', chunk)
        name = name.decode()
        ip_str = socket.inet_ntoa(struct.pack('!I', ip_bin))
        port = port_bin
        cost = cost_bin
        if originID is None:
            originID = name
        if cost != 0:
            link_state[name] = cost
            neighbors.add((ip_str, port))
        else:
            link_state[name] = 0
    print_graph()
    send_lsp()

try:
    # --- Main loop using select ---
    while True:
        now = time.time()
        timeout = max(0, lsp_interval - (now - last_lsp_time))
        rlist, _, _ = select.select([tcp_sock, udp_sock], [], [], timeout)

        # TCP: LINK-STATE from ON
        if tcp_sock in rlist:
            data = tcp_sock.recv(1024)
            if data:
                handle_link_state(data)
            else:
                print("ON disconnected. Exiting.")
                break

        # UDP: LSP from neighbors
        if udp_sock in rlist:
            data, addr = udp_sock.recvfrom(1024)
            if len(data) < 6:
                continue
            origin, seq, num = struct.unpack('!cIB', data[:6])
            origin = origin.decode()
            pos = 6
            for _ in range(num):
                if pos + 3 > len(data):
                    break
                n, c = struct.unpack('!cH', data[pos:pos+3])
                n = n.decode()
                link_state[n] = c
                pos += 3
            print_graph()

        # Periodic LSP sending
        if now - last_lsp_time >= lsp_interval:
            send_lsp()
            last_lsp_time = now

except KeyboardInterrupt:
    print("\nVN interrupted by user. Exiting.")

finally:
    print("Closing sockets...")
    tcp_sock.close()
    udp_sock.close()
    print("Sockets closed. Goodbye!")
