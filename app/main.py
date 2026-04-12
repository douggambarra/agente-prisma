from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, agente, auditoria
from app.database import test_connection

app = FastAPI(title="Prisma Concursos - Agente IA", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(agente.router, prefix="/agente", tags=["Agente"])
app.include_router(auditoria.router, prefix="/auditoria", tags=["Auditoria"])

@app.get("/")
def root():
    return {"status": "ok", "sistema": "Prisma Agente IA"}

@app.get("/status")
def status():
    db_ok = test_connection()
    return {
        "api": "online",
        "banco": "conectado" if db_ok else "erro de conexão"
    }
