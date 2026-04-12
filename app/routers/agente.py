from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.buscador import processar_busca
from app.database import get_connection

router = APIRouter()

jobs = {}

class BuscaTematicaRequest(BaseModel):
    id_usuario: int
    disciplina: str
    banca: str = "Todas"
    ano_ini: int = 2018
    limite: int = 200
    id_assunto: Optional[int] = None

class ProvaRequest(BaseModel):
    id_usuario: int
    banca: str
    orgao: str
    cargo: str
    ano: int

class FilaProvasRequest(BaseModel):
    id_usuario: int
    provas: list[ProvaRequest]

def executar_busca_bg(job_id: str, params: dict):
    try:
        jobs[job_id]["status"] = "executando"
        resultado = processar_busca(**params)
        jobs[job_id]["status"] = "concluido"
        jobs[job_id]["resultado"] = resultado
    except Exception as e:
        jobs[job_id]["status"] = "erro"
        jobs[job_id]["erro"] = str(e)

@router.post("/busca-tematica")
def busca_tematica(data: BuscaTematicaRequest, background_tasks: BackgroundTasks):
    import uuid
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "aguardando", "resultado": None}

    params = {
        "id_usuario": data.id_usuario,
        "disciplina": data.disciplina,
        "banca": data.banca,
        "ano_ini": data.ano_ini,
        "limite": data.limite,
        "id_assunto": data.id_assunto,
    }
    background_tasks.add_task(executar_busca_bg, job_id, params)
    return {"job_id": job_id, "status": "iniciado"}

@router.get("/job/{job_id}")
def status_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return jobs[job_id]

@router.get("/metricas")
def metricas():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) as total FROM pergunta")
        total = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COUNT(*) as hoje FROM pergunta
            WHERE DATE(data_cadastro) = CURDATE()
        """)
        hoje = cursor.fetchone()["hoje"]

        cursor.execute("""
            SELECT COUNT(*) as total FROM prova
        """)
        provas = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT DATE(data_cadastro) as dia, COUNT(*) as qtd
            FROM pergunta
            WHERE data_cadastro >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY dia ORDER BY dia
        """)
        historico = cursor.fetchall()

        return {
            "total_questoes": total,
            "inseridas_hoje": hoje,
            "total_provas": provas,
            "historico_7dias": historico
        }
    finally:
        cursor.close()
        conn.close()

@router.get("/assuntos")
def listar_assuntos():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id, nome, id_assunto as id_pai
            FROM assunto ORDER BY nome
        """)
        return {"assuntos": cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()
