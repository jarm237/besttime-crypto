import os
from cryptography.fernet import Fernet

def generate_key():
    """Sinh ra một khóa (key) dùng để mã hóa và giải mã. Giữ khóa này an toàn!"""
    key = Fernet.generate_key()
    print("\n--- KHÓA BẢO MẬT MỚI (ENCRYPTION_KEY) ---")
    print(key.decode('utf-8'))
    print("Vui lòng lưu khóa này vào file .env dưới dạng: ENCRYPTION_KEY=...\n")

def encrypt_message():
    """Nhập một chuỗi văn bản (ví dụ API key) và mã hóa nó."""
    key = input("Nhập khóa bảo mật (ENCRYPTION_KEY): ").encode('utf-8')
    try:
        f = Fernet(key)
    except ValueError:
        print("Khóa không hợp lệ!")
        return

    message = input("Nhập chuỗi cần mã hóa (VD: API_KEY): ").encode('utf-8')
    encrypted = f.encrypt(message)
    print("\n--- CHUỖI ĐÃ MÃ HÓA ---")
    print(encrypted.decode('utf-8'))
    print("------------------------\n")

if __name__ == "__main__":
    while True:
        print("1. Tạo khóa bảo mật mới")
        print("2. Mã hóa một chuỗi")
        print("3. Thoát")
        choice = input("Chọn (1/2/3): ")
        if choice == '1':
            generate_key()
        elif choice == '2':
            encrypt_message()
        elif choice == '3':
            break
        else:
            print("Lựa chọn không hợp lệ.")
