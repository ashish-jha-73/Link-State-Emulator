import socket

SERVER_IP = "10.51.7.253" 
PORT = 7084

def main():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client_socket.connect((SERVER_IP, PORT))
        print(f"Connected to server {SERVER_IP}:{PORT}")

        message = "I am Satwik as client"
        client_socket.sendall(message.encode())
        print("Sent:", message)

        data = client_socket.recv(1024)
        print("Server says:", data.decode())

    except Exception as e:
        print("Error:", e)

    finally:
        client_socket.close()
        print("Connection closed.")

if __name__ == "__main__":
    main()
