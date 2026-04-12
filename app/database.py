import mysql.connector
from mysql.connector import Error
import os

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "prismaconcurso.mysql.dbaas.com.br"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "prismaconcurso"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "prismaconcurso"),
    "charset": "latin1",
    "collation": "latin1_general_ci",
    "use_unicode": True,
}

def get_connection():
    conn = mysql.connector.connect(**DB_CONFIG)
    return conn

def test_connection():
    try:
        conn = get_connection()
        conn.close()
        return True
    except Error as e:
        print(f"Erro de conexão: {e}")
        return False
