import os
import math
import time
import socket
import threading
import select

class FileDownloader:
    def __init__(self, server_host="localhost", server_port=5000, input_file="input.txt"):
        self.host = server_host         # Địa chỉ IP của server
        self.server_port = server_port  # Cổng kết nối đến server
        self.input_file = input_file    # Tên file chứa danh sách các file cần tải về
        self.download_progress = {}     # Lưu tiến trình tải từng phần của file

        self.download_lock = threading.Lock()   # Khóa để đồng bộ hóa truy cập vào biến download_progress
        self.active_downloads = set()           # Set lưu danh sách các file đang tải
        self.current_filename = ""              # Tên file hiện tại đang tải
        self.stop_progress_update = threading.Event()   # Cờ để dừng cập nhật tiến trình tải

    def get_available_files(self):
        # Yêu cầu danh sách file từ server
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)    # Tạo socket UDP client
        client_socket.settimeout(5)                            # Thiết lập timeout cho socket
        client_socket.sendto(b'LIST', (self.host, self.server_port)) # Gửi yêu cầu danh sách file đến server

        try:
            files, _ = client_socket.recvfrom(4096)         # Nhận danh sách file từ server
            print("\nAvailable Files:\n" + files.decode())  # In ra danh sách file
        
        except socket.timeout:
            print("Timeout getting file list")  # Nếu timeout, in ra thông báo lỗi
        
        finally:
            client_socket.close()   # Đóng socket client

    def read_input_file(self):
        # Đọc danh sách file cần tải từ input.txt
        if not os.path.exists(self.input_file): # Kiểm tra nếu file không tồn tại
            open(self.input_file, 'w').close()  # Tạo file nếu không tồn tại
        
        with open(self.input_file, 'r') as file:
            filenames = [line.strip() for line in file.readlines()] # Đọc từng dòng và loại bỏ khoảng trắng

        # Trả về danh sách file hợp lệ (loại bỏ file trùng lặp)
        return [f for f in filenames if f and f not in self.active_downloads]

    def remove_downloaded_file(self, filename):
        # Xóa tên file đã tải xong khỏi input.txt
        with open(self.input_file, 'r') as file:
            lines = file.readlines()    # Đọc nội dung file input.txt

            # Ghi lại những dòng không chứa tên file đã tải xong
        with open(self.input_file, 'w') as file:
            file.writelines(line for line in lines if line.strip() != filename) 
            
        if filename in self.active_downloads:
            self.active_downloads.remove(filename) # Xóa tên file khỏi danh sách tải

    def update_progress_display(self):
        # Cập nhật tiến trình của từng file
        if self.download_progress:
            print("\033[K", end="")  # Xóa dòng hiện tại trên console
            for i in range(1, 5):
                if i in self.download_progress:
                    progress = self.download_progress[i]
                    print(f"Downloading {self.current_filename} part {i} .... {progress:.2f}%")
                else:
                    print(f"Downloading {self.current_filename} part {i} .... 0.00%")
                
            # Đưa con trỏ lên lại trên đầu dòng để cập nhật
            print(f"\033[{4}A", end="", flush=True)

    def download_file_part(self, filename, part_number, start_offset, end_offset, file_size):
        # Tải một phần của file từ server
        # Tạo socket UDP client riêng cho mỗi phần
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_socket.settimeout(None)  # Không dùng timeout, sẽ dùng poll
        temp_filename = f"{filename}.part{part_number}" # Tên file tạm thời để lưu phần tải về
        chunk_size = 8192               # Kích thước mỗi chunk tải về (8KB)
        current_offset = start_offset   # Vị trí bắt đầu tải
        received_size = 0               # Số byte đã tải về
        total_part_size = end_offset - start_offset # Kích thước phần tải về
        poller = select.poll()
        poller.register(client_socket, select.POLLIN)
        try:
            with open(temp_filename, 'wb') as file: # Mở file tạm thời để ghi dữ liệu
                while current_offset < end_offset:
                    request_chunk = f"{filename}|{current_offset}|{min(chunk_size, end_offset - current_offset)}".encode()
                    client_socket.sendto(request_chunk, (self.host, self.server_port)) # Gửi yêu cầu tải về chunk
                    events = poller.poll(5000)  # Đợi tối đa 5 giây
                    if not events:
                        continue  # Nếu timeout, gửi lại request
                    for fd, event in events:
                        if fd == client_socket.fileno() and event & select.POLLIN:
                            chunk, _ = client_socket.recvfrom(chunk_size + 1024)    # Nhận dữ liệu từ server
                            if not chunk or chunk == b"File not found" or chunk == b"Error reading file":
                                print(f"\nError downloading {filename} part {part_number}")
                                return False, temp_filename
                            file.write(chunk)               # Ghi chunk vào file tạm thời
                            current_offset += len(chunk)    # Cập nhật vị trí tải tiếp theo
                            received_size += len(chunk)     # Cập nhật số byte đã tải về
                            # Cập nhật tiến trình tải
                            progress = (received_size / total_part_size) * 100
                            with self.download_lock:
                                self.download_progress[part_number] = min(progress, 100.0)  # Giới hạn 100%
            # Khi tải xong, cập nhật tiến trình là 100%
            with self.download_lock:
                self.download_progress[part_number] = 100.0
            return True, temp_filename
        except Exception as e:
            print(f"\nError in part {part_number}: {e}")
            return False, temp_filename
        finally:
            poller.unregister(client_socket)
            client_socket.close() # Đóng socket client

    def progress_updater(self):
        # Cập nhật tiến trình tải về
        try:
            while not self.stop_progress_update.is_set():
                with self.download_lock:
                    if self.current_filename:
                        self.update_progress_display()
                time.sleep(0.3)

        except Exception as e:
            print(f"\nProgress updater error: {e}")

    def combine_parts(self, filename, temp_files):
        # Ghép các phần đã tải thành file hoàn chỉnh
        try:
            with open(filename, 'wb') as outfile:
                for temp_file in temp_files:
                    if os.path.exists(temp_file): # Kiểm tra nếu file tạm tồn tại
                        with open(temp_file, 'rb') as infile:
                            outfile.write(infile.read())    # Ghi nội dung file tạm vào file hoàn chỉnh
                        os.remove(temp_file)                # Xóa file tạm sau khi ghép xong
                return True

        except Exception as e:
            print(f"\nFailed to combine file parts: {e}")
            return False

    def download_file(self, filename):
        # Tải file bằng 4 luồng song song
        self.active_downloads.add(filename)
        self.current_filename = filename
        self.download_progress = {}
        self.stop_progress_update.clear()
        
        # Tạo khoảng trống trên console để hiển thị tiến trình tải
        print("\n\n\n\n")         # Tạo 4 dòng trống
        print("\033[4A", end="")  # Di chuyển con trỏ lên 4 dòng
        for i in range(1, 5):
            print(f"Downloading {filename} part {i} .... 0.00%")
        print("\033[4A", end="", flush=True)  # Đưa con trỏ lên lại trên đầu dòng để cập nhật
        
        # Tạo socket để lấy kích thước file từ server
        init_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        init_socket.settimeout(5)
        
        try:
            # Bắt đầu luồng cập nhật tiến trình tải
            progress_thread = threading.Thread(target=self.progress_updater)
            progress_thread.daemon = True
            progress_thread.start()
            
            # Gửi yêu cầu lấy kích thước file từ server
            init_socket.sendto(f"{filename}|0|0".encode(), (self.host, self.server_port))
            metadata, _ = init_socket.recvfrom(1024)
            metadata_parts = metadata.decode().split('|')
            
            if len(metadata_parts) < 2 or metadata == b"File not found":
                print(f"\nFile {filename} not found or invalid metadata")
                self.active_downloads.remove(filename)
                self.stop_progress_update.set()
                return
                
            file_size = int(metadata_parts[1])      # Kích thước file từ server            
            part_size = math.ceil(file_size / 4)    # Chia file thành 4 phần bằng nhau
            
            # Tạo các luồng để tải file
            threads = []
            temp_files = []
            
            for i in range(4):
                start_offset = i * part_size
                end_offset = min((i + 1) * part_size, file_size)
                
                thread = threading.Thread(
                    target=self.download_file_part,
                    args=(filename, i+1, start_offset, end_offset, file_size)
                )
                temp_files.append(f"{filename}.part{i+1}")
                threads.append(thread)
                thread.start()
            
            # Chờ tất cả các luồng hoàn thành
            for thread in threads:
                thread.join()
                
            # Dừng cập nhật tiến trình
            self.stop_progress_update.set()
            time.sleep(0.5)  # Dành thời gian chờ cho cập nhật cuối cùng
            
            # Xóa các dòng hiển thị tiến trình
            print("\033[4B")  # Di chuyển con trỏ xuống 4 dòng
            print("\n")
            
            # Ghép các phần đã tải thành file hoàn chỉnh
            if self.combine_parts(filename, temp_files):
                print(f"{filename} downloaded successfully!")
                self.remove_downloaded_file(filename)
            else:
                print(f"Failed to combine parts for {filename}")
                
        except Exception as e:
            print(f"\nDownload failed: {e}")

        finally:
            self.stop_progress_update.set()  # Double check dừng cập nhật tiến trình
            init_socket.close()
            if filename in self.active_downloads:
                self.active_downloads.remove(filename)
            self.current_filename = ""

    def run(self):
        # Kiểm tra input.txt và tải file khi có yêu cầu
        print("Type the name of file you want to download in input.txt\n")
        try:
            while True:
                files_to_download = self.read_input_file()
                for filename in files_to_download:
                    self.download_file(filename)
                time.sleep(5)  # Kiểm tra lại mỗi 5s

        except KeyboardInterrupt:
            print("\nExiting downloader...")
            self.stop_progress_update.set()  # Double check dừng cập nhật tiến trình
            return

def main():

    # Cần thay đổi IP server mỗi lần chạy
    downloader = FileDownloader(server_host="192.168.0.101", server_port=5000)
    try:
        downloader.get_available_files()    # Lấy danh sách file từ server
        downloader.run()                    # Bắt đầu tải file từ input.txt
    except KeyboardInterrupt:
        print("\nExiting downloader...")

if __name__ == "__main__":
    main()