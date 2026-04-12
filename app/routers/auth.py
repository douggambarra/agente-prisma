from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database import get_connection
import hashlib

router = APIRouter()

class LoginRequest(BaseModel):
    login: str
    senha: str

def md5(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8")).hexdigest()

@router.post("/login")
def login(data: LoginRequest):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        senha_hash = md5(data.senha)
        cursor.execute(
            "SELECT id, nome, email, cargo FROM usuario WHERE login = %s AND senha = %s",
            (data.login, senha_hash)
        )
        usuario = cursor.fetchone()
        if not usuario:
            raise HTTPException(status_code=401, detail="Login ou senha incorretos")
        return {
            "autenticado": True,
            "usuario": usuario
        }
    finally:
        cursor.close()
        conn.close()

@router.get("/usuarios")
def listar_usuarios():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nome, email, login, cargo FROM usuario ORDER BY nome")
        usuarios = cursor.fetchall()
        return {"usuarios": usuarios, "total": len(usuarios)}
    finally:
        cursor.close()
        conn.close()
