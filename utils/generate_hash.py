from cryptography.fernet import Fernet

def generate_hash():
    return Fernet.generate_key().decode()

if __name__ == "__main__":
    print(generate_hash())