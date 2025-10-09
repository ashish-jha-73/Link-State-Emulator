#include <iostream>
#include <unistd.h>
#include <arpa/inet.h>

#define PORT 8089

struct sockaddr_in sr;

int main(int argc, char *args[]) {
    // initialization of socket 
    int sFD = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sFD < 0) {
        std::cout << "Socket did not opened !!" << std::endl;
        exit(EXIT_FAILURE);
    } else {
        std::cout << "Socket opened sucessfully." << std::endl;
    }

    // socket addr
    sr.sin_family = AF_INET;
    sr.sin_port = htons(PORT);
    sr.sin_addr.s_addr = INADDR_ANY;
    for (int i{0}; i<8; ++i) sr.sin_zero[i] = 0;

    // bind the local port
    int nRet = 0;
    nRet = bind(sFD, (sockaddr*)&sr, sizeof(sr));
    if (nRet < 0) {
        std::cout << "Failed to bind" << std::endl;
        exit(EXIT_FAILURE);
    } else {
        std::cout << "Sucesfully bind" << std::endl;
    }

    // Listen
    nRet = listen(sFD, 1); 
    if (nRet < 0) {
        std::cout << "Failed to listen" << std::endl;
        exit(EXIT_FAILURE);
    } else {
        std::cout << "Sucesfully listening" << std::endl;
    }

    // client accept
    sockaddr_in client_addr;
    socklen_t client_len = sizeof(client_addr);
    int new_socket = accept(sFD, (sockaddr*)&client_addr, &client_len);
    if (new_socket < 0) {
        perror("accept failed");
        exit(EXIT_FAILURE);
    } else {
        std::cout << "Client connected: " << inet_ntoa(client_addr.sin_addr) << std::endl;
    }

    // reading if client sends
    char buffer[1024] = {0};
    ssize_t bytesRead = read(new_socket, buffer, sizeof(buffer));
    if (bytesRead > 0) {
        std::cout << "Client says: " << buffer << std::endl;
    }

    // sending to client
    std::string msg = "I am Ashish as server";
    send(new_socket, msg.c_str(), msg.size(), 0);
    std::cout << "Reply sent to client." << std::endl;

    close(new_socket);
    close(sFD);

    std::cout << "Connection closed." << std::endl;
    return 0;
}