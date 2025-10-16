#include <iostream>
#include <vector>
#include <string>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstring>
#include <iomanip>

struct LinkStateTuple {
    char name;
    uint32_t ip;
    uint16_t port;
    uint16_t cost;
} __attribute__((packed));

bool recv_all(int sockfd, char* buffer, size_t len) {
    size_t received = 0;
    while (received < len) {
        ssize_t n = recv(sockfd, buffer + received, len - received, 0);
        if (n <= 0) return false;
        received += n;
    }
    return true;
}

void print_link_state(const std::vector<LinkStateTuple>& tuples) {
    for (size_t i = 0; i < tuples.size(); ++i) {
        in_addr ip_addr{};
        ip_addr.s_addr = tuples[i].ip;

        std::cout << "(" << tuples[i].name << ", " 
                  << inet_ntoa(ip_addr) << ", "
                  << ntohs(tuples[i].port) << ", "
                  << ntohs(tuples[i].cost) << ")";
        if (i + 1 < tuples.size()) std::cout << ", ";
    }
    std::cout << std::endl;
}

int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0] << " <ON_IP> <UDP_PORT> <OWN_IP>\n";
        return 1;
    }

    std::string on_ip = argv[1];
    int udp_port = std::stoi(argv[2]);
    std::string own_ip = (argc >= 4) ? argv[3] : "0.0.0.0";

    // Create UDP socket
    int udp_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (udp_sock < 0) { perror("UDP socket"); return 1; }

    sockaddr_in udp_addr{};
    udp_addr.sin_family = AF_INET;
    udp_addr.sin_port = htons(udp_port);
    udp_addr.sin_addr.s_addr = inet_addr(own_ip.c_str());

    if (bind(udp_sock, (struct sockaddr*)&udp_addr, sizeof(udp_addr)) < 0) {
        perror("bind UDP"); return 1;
    }

    std::cout << "UDP socket bound to port " << udp_port << "\n";

    int tcp_sock = socket(AF_INET, SOCK_STREAM, 0);
    if (tcp_sock < 0) { perror("TCP socket"); return 1; }

    sockaddr_in on_addr{};
    on_addr.sin_family = AF_INET;
    on_addr.sin_port = htons(5000);
    on_addr.sin_addr.s_addr = inet_addr(on_ip.c_str());

    if (connect(tcp_sock, (struct sockaddr*)&on_addr, sizeof(on_addr)) < 0) {
        perror("connect"); return 1;
    }

    std::cout << "Connected to Oracle Node at " << on_ip << ":5000\n";

    struct {
        uint32_t ip;
        uint16_t port;
    } connect_msg;

    connect_msg.ip = inet_addr(own_ip.c_str());
    connect_msg.port = htons(udp_port);

    if (send(tcp_sock, &connect_msg, sizeof(connect_msg), 0) != sizeof(connect_msg)) {
        perror("send CONNECT"); return 1;
    }

    std::cout << "CONNECT message sent\n";

    // Receive LINK-STATE message
    while (true) {
        LinkStateTuple buffer[27];
        if (!recv_all(tcp_sock, reinterpret_cast<char*>(buffer), sizeof(LinkStateTuple))) {
            std::cerr << "Failed to receive LINK-STATE\n";
            break;
        }

        ssize_t n = recv(tcp_sock, reinterpret_cast<char*>(buffer) + sizeof(LinkStateTuple), sizeof(buffer) - sizeof(LinkStateTuple), MSG_DONTWAIT);
        size_t tuples_count = 1;
        if (n > 0) {
            tuples_count += n / sizeof(LinkStateTuple);
        }

        std::vector<LinkStateTuple> tuples(buffer, buffer + tuples_count);
        print_link_state(tuples);
    }

    close(tcp_sock);
    close(udp_sock);
    return 0;
}
