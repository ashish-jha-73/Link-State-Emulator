#include <iostream>
#include <algorithm>
#include <iomanip>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/select.h>
#include <unistd.h>
#include <vector>
#include <cstring>
#include <filesystem>
#include "file_reader.hpp"

const int PORT = 5000;

struct VirtualNode {
    char name;
    int sockfd;
    std::string ip;
    int udpPort;
};

// Binary LINK-STATE tuple
#pragma pack(push,1)
struct LinkStateTuple {
    char name;
    uint32_t ip;
    uint16_t port;
    uint16_t cost;
};
#pragma pack(pop)

// Print adjacency matrix
void print_matrix(const std::vector<std::vector<int>>& mat) {
    size_t n = mat.size();
    std::cout << "\nAdjacency Matrix (" << n << " nodes):\n    ";
    for (size_t j = 0; j < n; ++j) std::cout << "  " << static_cast<char>('A'+j);
    std::cout << "\n";
    for (size_t i = 0; i < n; ++i) {
        std::cout << " " << static_cast<char>('A'+i) << "  ";
        for (size_t j=0;j<n;++j) std::cout << std::setw(3) << mat[i][j] << " ";
        std::cout << "\n";
    }
    std::cout << std::endl;
}

// Send all bytes over TCP
bool send_all(int sockfd, const char* data, size_t len) {
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(sockfd, data + sent, len - sent, 0);
        if (n <= 0) return false;
        sent += n;
    }
    return true;
}

// Safe receive function to get exact number of bytes
bool recv_all(int sockfd, char* buffer, size_t len) {
    size_t received = 0;
    while (received < len) {
        ssize_t n = recv(sockfd, buffer + received, len - received, 0);
        if (n <= 0) return false; 
        received += n;
    }
    return true;
}

// Send LINK-STATE to a VN
bool send_link_state(VirtualNode &vn, const std::vector<VirtualNode> &nodes,
                     const std::vector<std::vector<int>> &matrix) {
    std::vector<LinkStateTuple> tuples;
    for (size_t i=0;i<nodes.size();++i) {
        if (matrix[vn.name-'A'][i]>=0) {
            LinkStateTuple t;
            t.name = nodes[i].name;
            t.ip = inet_addr(nodes[i].ip.c_str());
            t.port = htons(nodes[i].udpPort);
            t.cost = htons(matrix[vn.name-'A'][i]);
            tuples.push_back(t);
        }
    }
    return send_all(vn.sockfd, reinterpret_cast<char*>(tuples.data()), tuples.size()*sizeof(LinkStateTuple));
}

int main(int argc, char* argv[]) {
    if (argc != 2) { std::cerr << "Usage: " << argv[0] << " <config-file>\n"; return 1; }

    std::string configFilePath = argv[1];
    auto matrix = read_file(configFilePath);
    if (matrix.empty()) { std::cerr << "Wrong Format in config file\n"; return 1; }

    size_t numNodes = matrix.size();
    print_matrix(matrix);

    int listenSock = socket(AF_INET, SOCK_STREAM, 0);
    if (listenSock < 0) { perror("socket"); return 1; }

    int opt=1;
    setsockopt(listenSock,SOL_SOCKET,SO_REUSEADDR,&opt,sizeof(opt));

    sockaddr_in serverAddr{};
    serverAddr.sin_family = AF_INET;
    serverAddr.sin_addr.s_addr = INADDR_ANY;
    serverAddr.sin_port = htons(PORT);

    if (bind(listenSock,(struct sockaddr*)&serverAddr,sizeof(serverAddr))<0) { perror("bind"); return 1; }
    if (listen(listenSock,5)<0) { perror("listen"); return 1; }

    std::cout << "Oracle Node listening on port " << PORT << " for " << numNodes << " VNs\n";

    std::vector<VirtualNode> nodes;
    std::filesystem::file_time_type lastWriteTime = std::filesystem::last_write_time(configFilePath);

    fd_set readfds;
    int maxfd = listenSock;

    while (true) {
        FD_ZERO(&readfds);
        FD_SET(listenSock, &readfds);
        maxfd = listenSock;

        for (auto &vn : nodes) if (vn.sockfd != -1) { 
            FD_SET(vn.sockfd, &readfds);
            if (vn.sockfd > maxfd) maxfd = vn.sockfd;
        }

        struct timeval tv{1, 0}; 
        int activity = select(maxfd+1, &readfds, nullptr, nullptr, &tv);
        if (activity < 0) { perror("select"); break; }

        if (FD_ISSET(listenSock,&readfds)) {
            sockaddr_in clientAddr{};
            socklen_t clientLen = sizeof(clientAddr);
            int clientSock = accept(listenSock,(struct sockaddr*)&clientAddr,&clientLen);
            if (clientSock >= 0) {
                if (nodes.size() < numNodes) {
                    VirtualNode vn;
                    vn.name = 'A'+nodes.size();
                    vn.sockfd = clientSock;

                    vn.ip = inet_ntoa(clientAddr.sin_addr);
                    vn.udpPort = 0;
                    std::cout << "Connected VN " << vn.name << " from " << vn.ip << "\n";

                    struct { uint32_t ip; uint16_t port; } connectMsg;
                    if (recv_all(vn.sockfd, reinterpret_cast<char*>(&connectMsg), sizeof(connectMsg))) {
                        vn.udpPort = ntohs(connectMsg.port);
                        nodes.push_back(vn);
                        std::cout << "VN " << vn.name << " UDP Port: " << vn.udpPort 
                                  << ", IP: " << inet_ntoa(*(in_addr*)&connectMsg.ip) << "\n";

                        if(!send_link_state(vn, nodes, matrix)) {
                            std::cerr << "Failed to send LINK-STATE to VN " << vn.name << "\n";
                            close(vn.sockfd); vn.sockfd = -1;
                        }
                    } else {
                        std::cerr << "Failed to receive CONNECT message from VN " << vn.name << "\n";
                        close(vn.sockfd); vn.sockfd = -1;
                    }
                } else {
                    std::cout << "Extra VN connected. Closing socket.\n";
                    close(clientSock);
                }
            }
        }

        // Check existing VN sockets
        for (auto &vn : nodes) {
            if (vn.sockfd != -1 && FD_ISSET(vn.sockfd, &readfds)) {
                char buffer[1024];
                ssize_t n = recv(vn.sockfd, buffer, sizeof(buffer), MSG_DONTWAIT);
                if(n <= 0) { 
                    std::cout << "VN " << vn.name << " disconnected\n"; 
                    close(vn.sockfd); vn.sockfd = -1; 
                } 
            }
        }

        // Monitor config file changes
        auto currentWriteTime = std::filesystem::last_write_time(configFilePath);
        if(currentWriteTime != lastWriteTime) {
            lastWriteTime = currentWriteTime;
            auto newMatrix = read_file(configFilePath);
            if(!newMatrix.empty()) {
                matrix = newMatrix;
                std::cout << "Config file updated. Resending LINK-STATE to all VNs.\n";
                for (auto &vn : nodes) if(vn.sockfd != -1) send_link_state(vn, nodes, matrix);
            }
        }
    }

    close(listenSock);
    return 0;
}
