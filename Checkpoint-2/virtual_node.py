#!/usr/bin/env python3

import socket
import struct
import select
import time
import sys
import heapq
from math import inf

ON_TCP_PORT = 5000
LSP_BROADCAST_INTERVAL = 15    
PRINT_GRAPH_INTERVAL = 15      
RETRANSMIT_COUNT = 3          


link_state = []     
lsp_db = {}         
seq_num = 0

# Binary formats
TUPLE_FMT = "!cIHH"   
TUPLE_SIZE = struct.calcsize(TUPLE_FMT)
LSP_HEADER_FMT = "!cIH"  
LSP_HEADER_SIZE = struct.calcsize(LSP_HEADER_FMT)


def build_connect_msg(own_ip, udp_port):
    ip_int = struct.unpack("!I", socket.inet_aton(own_ip))[0]
    return struct.pack("!IH2x", ip_int, udp_port)


def build_lsp(origin_id):
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
    for (n, ip, port, _) in link_state:
        if exclude_addr and (ip, port) == exclude_addr:
            continue
        for _ in range(RETRANSMIT_COUNT):
            udp_sock.sendto(lsp_bytes, (ip, port))


def handle_incoming_lsp(udp_sock, data, addr, node_id):
    parsed = parse_lsp(data)
    if not parsed:
        return False
    origin, seq, links = parsed
    prev = lsp_db.get(origin)
    if prev and seq <= prev['seq']:
        return False
    # store and flood
    lsp_db[origin] = {'seq': seq, 'links': links}
    flood_to_neighbors(udp_sock, data, exclude_addr=addr)
    print(f"[RECV] New LSP from {origin} seq={seq} via {addr}; flooded to neighbors")
    compute_and_print_routes(node_id)
    return True


def update_link_state_from_tcp_buffer(tcp_buffer):
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

    global link_state
    link_state = tuples

    node_id = None
    for (n, ip, port, cost) in link_state:
        if cost == 0:
            node_id = n  
            break

    printable = ",".join(f"{n}={cost}" for (n, ip, port, cost) in link_state)
    print(f"[TCP] Received LINK-STATE from ON: {printable}")
    return True, remaining, node_id, printable


def print_graph():
    print("\nCURRENT NETWORK GRAPH (Upper-Triangular Cost Matrix) : \n")
    if not lsp_db:
        print("(empty)")
        print("\n")
        return

    nodes = sorted(lsp_db.keys())
    n = len(nodes)
    if n == 0:
        print("(no nodes)")
        print("\n")
        return

    graph = build_graph_from_lsdb()

    for i in range(n - 1):
        row_node = nodes[i]
        next_nodes = nodes[i + 1:]
        if not next_nodes:
            continue
        # print(f"# Costs from {row_node} to {', '.join(next_nodes)}")
        row_costs = []
        for j in range(i + 1, n):
            col_node = nodes[j]
            cost = graph.get(row_node, {}).get(col_node, graph.get(col_node, {}).get(row_node, -1))
            row_costs.append(str(cost) if cost != -1 else "-1")
        print("\t" * i + "\t".join(row_costs))
    print("n")



def build_graph_from_lsdb():
    graph = {}
    for origin, info in lsp_db.items():
        origin = origin.strip()  
        if origin == "":
            continue
        if origin not in graph:
            graph[origin] = {}
        for (n, ip, port, cost) in info['links']:
            n = n.strip()
            if n == "":
                continue
            prev = graph[origin].get(n)
            if prev is None or cost < prev:
                graph[origin][n] = cost
            if n not in graph:
                graph[n] = {}
    return graph


def dijkstra(graph, source):
    dist = {node: inf for node in graph}
    prev = {node: None for node in graph}
    if source not in graph:
        return dist, prev
    dist[source] = 0
    pq = [(0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in graph[u].items():
            nd = d + w
            if nd < dist.get(v, inf):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def compute_next_hop_from_prev(prev, source, dest):
    if dest == source:
        return '-'
    if prev.get(dest) is None:
        return None 
    cur = dest
    last = cur
    while prev.get(cur) is not None and prev[cur] != source:
        cur = prev[cur]
        if cur == last:
            break
        last = cur

    if prev.get(cur) == source:
        return cur 
    
    if prev.get(dest) == source:
        return dest
    return None


def print_routing_table(node_id, dist, prev):

    print(f"\n ROUTING TABLE for {node_id} : \n")
    nodes = sorted(list(set(list(dist.keys()) + [node_id])))
    for n in nodes:
        if n == "":
            continue
        d = dist.get(n, inf)
        if d == inf:
            nh = '*'
            cost_str = 'INF'
        else:
            nh = compute_next_hop_from_prev(prev, node_id, n)
            nh = nh if (nh is not None) else '*'
            cost_str = str(int(d))
        print(f"Dest {n}  NextHop {nh}  Cost {cost_str}")
    print("\n")


def compute_and_print_routes(node_id):

    graph = build_graph_from_lsdb()
    dist, prev = dijkstra(graph, node_id)
    print_routing_table(node_id, dist, prev)


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <ON_IP> <UDP_PORT> <OWN_IP> <optional NodeID>")
        sys.exit(1)

    oracle_ip = sys.argv[1]
    udp_port = int(sys.argv[2])
    own_ip = sys.argv[3]
    node_id_cli = sys.argv[4] if len(sys.argv) >= 5 else None

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setblocking(False)
    try:
        tcp_sock.connect((oracle_ip, ON_TCP_PORT))
    except BlockingIOError:
        pass

    _, writable, _ = select.select([], [tcp_sock], [], 5.0)
    if tcp_sock not in writable:
        print("[ERROR] TCP connect to Oracle Node timed out")
        tcp_sock.close()
        sys.exit(1)

    connect_msg = build_connect_msg(own_ip, udp_port)
    total_sent = 0
    while total_sent < len(connect_msg):
        sent = tcp_sock.send(connect_msg[total_sent:])
        total_sent += sent
    print(f"[INFO] CONNECT message sent to Oracle ({oracle_ip}:{ON_TCP_PORT})")

    tcp_sock.setblocking(False)
    tcp_buffer = b""

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setblocking(False)
    try:
        udp_sock.bind((own_ip, udp_port))
    except Exception as e:
        print(f"[ERROR] UDP bind failed: {e}")
        tcp_sock.close()
        sys.exit(1)
    print(f"[INFO] UDP socket bound on {own_ip}:{udp_port}")

    node_id = node_id_cli if node_id_cli else chr(ord('A') + (udp_port % 26))

    now = time.time()
    next_broadcast = None 
    next_print = now + PRINT_GRAPH_INTERVAL

    print("[INFO] Waiting for LINK-STATE from Oracle (over TCP)...")

    try:
        while True:
            now = time.time()
            if next_broadcast:
                timeout = max(0.0, min(next_broadcast - now, next_print - now))
            else:
                timeout = max(0.0, next_print - now)

            rlist = [udp_sock]
            if tcp_sock:
                rlist.append(tcp_sock)

            r_ready, _, _ = select.select(rlist, [], [], timeout)

            if tcp_sock and tcp_sock in r_ready:
                try:
                    chunk = tcp_sock.recv(4096)
                except BlockingIOError:
                    chunk = b""
                if not chunk:
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
                            node_id = new_node_id  
                            print(f"[INFO] Node id set to '{node_id}' from ON (zero-cost tuple)")
                            next_broadcast = time.time() + LSP_BROADCAST_INTERVAL   

                        lsp_bytes, seq = build_lsp(node_id)
                        flood_to_neighbors(udp_sock, lsp_bytes)
                        lsp_db[node_id] = {'seq': seq, 'links': list(link_state)}
                        print(f"[ACTION] Sent immediate LSP seq={seq} due to ON update")
                        compute_and_print_routes(node_id)


            if udp_sock in r_ready:
                try:
                    data, addr = udp_sock.recvfrom(4096)
                    handle_incoming_lsp(udp_sock, data, addr, node_id)
                except BlockingIOError:
                    pass

            now = time.time()
            if next_broadcast and now >= next_broadcast:
                lsp_bytes, seq = build_lsp(node_id)
                flood_to_neighbors(udp_sock, lsp_bytes)
                lsp_db[node_id] = {'seq': seq, 'links': list(link_state)}
                print(f"[TIMER] Periodic LSP seq={seq} broadcast")
                compute_and_print_routes(node_id)
                next_broadcast += LSP_BROADCAST_INTERVAL
            
            if now >= next_print:
                print_graph()
                compute_and_print_routes(node_id)
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
