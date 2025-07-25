import os
import socket
import select

class FileServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host    # Địa chỉ IP mà server sẽ kết nối
        self.port = port    # Cổng mà server sẽ kết nối
        self.available_files = self.load_available_files() # Tải danh sách file có sẵn
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # Tạo socket UDP
        self.server_socket.bind((self.host, self.port))    # Liên kết socket với địa chỉ và cổng đã chỉ định
        self.server_socket.setblocking(False)  # Đặt socket ở chế độ non-blocking

    def load_available_files(self):
        # Đọc danh sách các tệp có sẵn từ server_files.txt
        files = {}

        try:
            with open('server_files.txt', 'r') as f:
                for line in f:
                    parts = line.strip().split() # Loại bỏ khoảng trắng và lấy danh sách

                    if len(parts) == 2:
                        filename, size_str = parts
                        if size_str.endswith("MB"):   # Nếu kích thước là MB
                            size = int(size_str.replace("MB", "")) * 1024 * 1024
                        elif size_str.endswith("GB"): # Nếu kích thước là GB
                            size = int(size_str.replace("GB", "")) * 1024 * 1024 * 1024
                        else:
                            continue    # Bỏ qua nếu không đúng định dạng
                        files[filename] = size 

        except FileNotFoundError:
            print("No available files list found.")

        return files

    def send_file_list(self, client_address):
        # Gửi danh sách các file cho client
        # Tạo danh sách dưới dạng chuỗi
        file_list = '\n'.join([f"{name} {size/1024/1024}MB" for name, size in self.available_files.items()])
        self.server_socket.sendto(file_list.encode(), client_address)   # Gửi danh sách file cho client

    def send_file_chunk(self, filename, offset, chunk_size, client_address):
        # Gửi một chunk của file được yêu cầu cho client
        try:
            if filename not in self.available_files:
                self.server_socket.sendto(b"File not found", client_address)
                return

            file_size = os.path.getsize(filename)   # Lấy kích thước file
            if chunk_size == 0: # Nếu chunk_size là 0, gửi kích thước file
                size_info = f"{filename}|{file_size}".encode()       # Tạo thông tin kích thước file
                self.server_socket.sendto(size_info, client_address) # Gửi thông tin kích thước file
                return

            with open(filename, 'rb') as f: # Mở file để đọc
                f.seek(offset)              # Di chuyển con trỏ đến vị trí offset
                chunk = f.read(min(chunk_size, 8192))  # Giới hạn chunk size
                self.server_socket.sendto(chunk, client_address)

        except Exception as e:
            print(f"Error sending chunk: {e}")
            self.server_socket.sendto(b"Error sending file.", client_address)

    def run(self):
        print(f"Server listening on {self.host}:{self.port}")
        while True:
            try:
                readable, _, _ = select.select([self.server_socket], [], [], 1.0)
                if not readable:
                    continue
                data, client_address = self.server_socket.recvfrom(1024)
                request = data.decode()
                if request == 'LIST':
                    self.send_file_list(client_address)
                else:
                    parts = request.split('|')
                    if len(parts) < 3:
                        self.server_socket.sendto(b"Invalid request format", client_address)
                        continue
                    filename, offset, chunk_size = parts[0], int(parts[1]), int(parts[2])
                    self.send_file_chunk(filename, offset, chunk_size, client_address)
            except Exception as e:
                print(f"Error in server loop: {e}")

def main():
    server = FileServer()
    server.run()

if __name__ == "__main__":
    main()