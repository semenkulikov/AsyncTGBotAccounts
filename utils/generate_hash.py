from cryptography.fernet import Fernet

def generate_hash():
    """ Функция для генерации хеша """
    return Fernet.generate_key().decode()

if __name__ == "__main__":
    print(generate_hash())
