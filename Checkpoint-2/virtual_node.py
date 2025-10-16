#!/usr/bin/env python3
"""
vn_node_select.py
Single-process, select-based Virtual Node for Link-State Emulator.

Usage:
    python3 vn_node_select.py <ON_IP> <UDP_PORT> <OWN_IP> [NODE_ID]

If ON provides a zero-cost tuple, that tuple's alphabet overrides NODE_ID.
"""
import socket
import struct
import select
import time
import sys

# ======== CONFIG ========
ON_TCP_PORT = 5000
LSP_BROADCAST_INTERVAL = 10    # seconds
PRINT_GRAPH_INTERVAL = 10      # seconds
RETRANSMIT_COUNT = 3           # send each LSP this many times
# =========================

# Global state (single-threaded -> no locks)
link_state = []     # list of (name, ip_str, port, cost)
lsp_db = {}         # origin -> {'seq': int, 'links': [(name, ip_str, port, cost), ...]}
seq_num = 0

# Binary formats
TUPLE_FMT = "!cIHH"    # neighbor tuple: char + uint32(ip) + uint16(port) + uint16(cost)
TUPLE_SIZE = struct.calcsize(TUPLE_FMT)
LSP_HEADER_FMT = "!cIH"  # origin char (1), seq uint32 (4), count uint16 (2) => 7 bytes
LSP_HEADER_SIZE = struct.calcsize(LSP_HEADER_FMT)


def build_connect_msg(own_ip, udp_port):
    """8-byte connect msg: uint32 ip + uint16 port + 2 bytes padding (to match typical C struct)."""
    ip_int = struct.unpack("!I", socket.inet_aton(own_ip))[0]
    return struct.pack("!IH2x", ip_int, udp_port)


def build_lsp(origin_id):
    """Create LSP bytes and increment local sequence number."""
    global seq_num
    seq_num += 1
    seq = seq_num
    count = len(link_state)
    header = struct.pack(LSP_HEADER_FMT, origin_id.encode('ascii'), seq, count)
    body = b''.join(
        struct.pack(TUPLE_FMT,
                    n.encode('ascii'),
                    struct.unpack("!I", socket.inet_aton(ip))[0],
                    port,
                    cost)
        for (n, ip, port, cost) in link_state
    )
    return header + body, seq


def parse_lsp(data):
    """Return (origin(str), seq(int), links(list of tuples)) or None."""
    if len(data) < LSP_HEADER_SIZE:
        return None
    origin_b, seq, count = struct.unpack(LSP_HEADER_FMT, data[:LSP_HEADER_SIZE])
    origin = origin_b.decode('ascii', errors='replace')
    links = []
    offset = LSP_HEADER_SIZE
    for _ in range(count):
        if offset + TUPLE_SIZE > len(data):
            break
        name_b, ip_int, port, cost = struct.unpack(TUPLE_FMT, data[offset:offset + TUPLE_SIZE])
        name = name_b.decode('ascii', errors='replace')
        ip_str = socket.inet_ntoa(struct.pack("!I", ip_int))
        links.append((name, ip_str, port, cost))
        offset += TUPLE_SIZE
    return origin, seq, links


def flood_to_neighbors(udp_sock, lsp_bytes, exclude_addr=None):
    """Send LSP to all neighbors, optionally excluding the sender address."""
    for (n, ip, port, _) in link_state:
        if exclude_addr and (ip, port) == exclude_addr:
            continue
        for _ in range(RETRANSMIT_COUNT):
            udp_sock.sendto(lsp_bytes, (ip, port))


def handle_incoming_lsp(udp_sock, data, addr):
    parsed = parse_lsp(data)
    if not parsed:
        return
    origin, seq, links = parsed
    prev = lsp_db.get(origin)
    if prev and seq <= prev['seq']:
        # old/duplicate -> ignore
        return
    # store and flood
    lsp_db[origin] = {'seq': seq, 'links': links}
    flood_to_neighbors(udp_sock, data, exclude_addr=addr)
    print(f"[RECV] New LSP from {origin} seq={seq} via {addr}; flooded to neighbors")


def update_link_state_from_tcp_buffer(tcp_buffer):
    """
    Parse whole neighbor tuples from tcp_buffer and update link_state.
    Returns (updated_flag, remaining_buffer, node_id_if_found_or_None, printable_str_or_None)
    """
    tuples = []
    offset = 0
    while len(tcp_buffer) - offset >= TUPLE_SIZE:
        chunk = tcp_buffer[offset: offset + TUPLE_SIZE]
        name_b, ip_int, port, cost = struct.unpack(TUPLE_FMT, chunk)
        name = name_b.decode('ascii', errors='replace')
        ip_str = socket.inet_ntoa(struct.pack("!I", ip_int))
        tuples.append((name, ip_str, port, cost))
        offset += TUPLE_SIZE
    remaining = tcp_buffer[offset:]
    if not tuples:
        return False, remaining, None, None

    # Update global link_state
    global link_state
    link_state = tuples

    # Extract node_id from tuple with cost == 0 if present
    node_id = None
    for (n, ip, port, cost) in link_state:
        if cost == 0:
            node_id = n  # alphabet-ID assigned by ON
            break

    # Printable format e.g. "E=0,C=1,D=7" -- keep order as sent by ON
    printable = ",".join(f"{n}={cost}" for (n, ip, port, cost) in link_state)
    print(f"[TCP] Received LINK-STATE from ON: {printable}")
    return True, remaining, node_id, printable


def print_graph():
    print("\n=== CURRENT NETWORK GRAPH (LSDB) ===")
    if not lsp_db:
        print("(empty)")
    else:
        for node, info in lsp_db.items():
            links_str = ", ".join(f"({n},{ip},{port},{cost})" for (n, ip, port, cost) in info['links'])
            print(f"{node} (seq={info['seq']}): {links_str}")
    print("====================================\n")


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <ON_IP> <UDP_PORT> <OWN_IP> [NODE_ID]")
        sys.exit(1)

    oracle_ip = sys.argv[1]
    udp_port = int(sys.argv[2])
    own_ip = sys.argv[3]
    node_id_cli = sys.argv[4] if len(sys.argv) >= 5 else None

    # 1) Connect to Oracle Node (TCP) non-blocking
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setblocking(False)
    try:
        tcp_sock.connect((oracle_ip, ON_TCP_PORT))
    except BlockingIOError:
        # normal for non-blocking
        pass

    # wait for writable -> connect done
    _, writable, _ = select.select([], [tcp_sock], [], 5.0)
    if tcp_sock not in writable:
        print("[ERROR] TCP connect to Oracle Node timed out")
        tcp_sock.close()
        sys.exit(1)

    # Send CONNECT message (8 bytes)
    connect_msg = build_connect_msg(own_ip, udp_port)
    total_sent = 0
    while total_sent < len(connect_msg):
        sent = tcp_sock.send(connect_msg[total_sent:])
        total_sent += sent
    print(f"[INFO] CONNECT message sent to Oracle ({oracle_ip}:{ON_TCP_PORT})")

    # Make TCP non-blocking and have a buffer
    tcp_sock.setblocking(False)
    tcp_buffer = b""

    # 2) Setup UDP socket and bind
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setblocking(False)
    try:
        udp_sock.bind((own_ip, udp_port))
    except Exception as e:
        print(f"[ERROR] UDP bind failed: {e}")
        tcp_sock.close()
        sys.exit(1)
    print(f"[INFO] UDP socket bound on {own_ip}:{udp_port}")

    # Node id initial: prefer ON-provided zero-cost mapping; otherwise CLI; otherwise fallback computed
    node_id = node_id_cli if node_id_cli else chr(ord('A') + (udp_port % 26))

    # Timers
    now = time.time()
    next_broadcast = now + LSP_BROADCAST_INTERVAL
    next_print = now + PRINT_GRAPH_INTERVAL

    print("[INFO] Waiting for LINK-STATE from Oracle (over TCP)...")

    try:
        while True:
            now = time.time()
            timeout = max(0.0, min(next_broadcast - now, next_print - now))

            # Prepare read list dynamically (don't pass closed/None sockets)
            rlist = [udp_sock]
            if tcp_sock:
                rlist.append(tcp_sock)

            r_ready, _, _ = select.select(rlist, [], [], timeout)

            # TCP readable: receive link-state updates from ON
            if tcp_sock and tcp_sock in r_ready:
                try:
                    chunk = tcp_sock.recv(4096)
                except BlockingIOError:
                    chunk = b""
                if not chunk:
                    # TCP closed by ON -> ON won't notify further; continue using UDP only
                    print("[TCP] Oracle connection closed")
                    try:
                        tcp_sock.close()
                    except:
                        pass
                    tcp_sock = None
                else:
                    tcp_buffer += chunk
                    updated, tcp_buffer, new_node_id, printable = update_link_state_from_tcp_buffer(tcp_buffer)
                    if updated:
                        if new_node_id:
                            node_id = new_node_id  # adopt alphabet from ON
                            print(f"[INFO] Node id set to '{node_id}' from ON (zero-cost tuple)")
                        # Immediately broadcast LSP reflecting this change
                        lsp_bytes, seq = build_lsp(node_id)
                        flood_to_neighbors(udp_sock, lsp_bytes)
                        lsp_db[node_id] = {'seq': seq, 'links': list(link_state)}
                        print(f"[ACTION] Sent immediate LSP seq={seq} due to ON update")

            # UDP readable: incoming LSPs
            if udp_sock in r_ready:
                try:
                    data, addr = udp_sock.recvfrom(4096)
                    handle_incoming_lsp(udp_sock, data, addr)
                except BlockingIOError:
                    pass

            # Periodic broadcast
            now = time.time()
            if now >= next_broadcast:
                lsp_bytes, seq = build_lsp(node_id)
                flood_to_neighbors(udp_sock, lsp_bytes)
                lsp_db[node_id] = {'seq': seq, 'links': list(link_state)}
                print(f"[TIMER] Periodic LSP seq={seq} broadcast")
                next_broadcast += LSP_BROADCAST_INTERVAL

            # Periodic print
            if now >= next_print:
                print_graph()
                next_print += PRINT_GRAPH_INTERVAL

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down VN")
    finally:
        try:
            udp_sock.close()
        except:
            pass
        try:
            if tcp_sock:
                tcp_sock.close()
        except:
            pass


if __name__ == "__main__":
    main()
