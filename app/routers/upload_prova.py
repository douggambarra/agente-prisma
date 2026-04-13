from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
import uuid
from app.database import get_connection
from app.services.processador_pdf import processar_pdfs, salvar_prova_completa

router = APIRouter()
jobs = {}

class DadosProva(BaseModel):
    nome: str
    banca: str
    data_da_prova: Optional[str] = None
    id_orgao: Optional[int] = None
    id_prova_existente: Optional[int] = None

class AlternativaPreview(BaseModel):
    letra: str
    texto: str
    correta: bool

class QuestaoPreview(BaseModel):
    numero: int
    enunciado: str
    pergunta: str
    gabarito: str
    anulada: bool = False
    disciplina: str
    alternativas: List[AlternativaPreview]

class ConfirmarSalvamentoRequest(BaseModel):
    id_usuario: int
    job_id: str
    dados_prova: DadosProva
    questoes: List[QuestaoPreview]

def executar_processamento(job_id: str, conteudo_prova: bytes, conteudo_gabarito: Optional[bytes], modelo: str):
    try:
        jobs[job_id]["status"] = "processando"
        resultado = processar_pdfs(conteudo_prova, conteudo_gabarito, modelo)
        jobs[job_id]["status"] = "aguardando_confirmacao"
        jobs[job_id]["resultado"] = resultado
    except Exception as e:
        jobs[job_id]["status"] = "erro"
        jobs[job_id]["erro"] = str(e)

@router.get("/provas")
def listar_provas(busca: str = ""):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        if busca:
            cursor.execute("""
                SELECT id, nome, banca, data_da_prova
                FROM prova
                WHERE nome LIKE %s OR banca LIKE %s
                ORDER BY data_cadastro DESC
                LIMIT 100
            """, (f"%{busca}%", f"%{busca}%"))
        else:
            cursor.execute("""
                SELECT id, nome, banca, data_da_prova
                FROM prova
                ORDER BY data_cadastro DESC
                LIMIT 100
            """)
        provas = cursor.fetchall()
        for p in provas:
            if p.get("data_da_prova"):
                p["data_da_prova"] = str(p["data_da_prova"])
        return {"provas": provas}
    finally:
        cursor.close()
        conn.close()

@router.post("/processar")
async def processar_upload(
    background_tasks: BackgroundTasks,
    prova: UploadFile = File(...),
    gabarito: Optional[UploadFile] = File(None),
    modelo: str = "sonnet"
):
    if not prova.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Arquivo de prova deve ser PDF.")
    conteudo_prova = await prova.read()
    conteudo_gabarito = None
    if gabarito and gabarito.filename:
        if not gabarito.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Gabarito deve ser PDF.")
        conteudo_gabarito = await gabarito.read()
    if modelo not in ("haiku", "sonnet", "opus"):
        modelo = "sonnet"
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "aguardando", "resultado": None, "erro": None}
    background_tasks.add_task(executar_processamento, job_id, conteudo_prova, conteudo_gabarito, modelo)
    return {"job_id": job_id, "status": "iniciado"}

@router.get("/job/{job_id}")
def status_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return jobs[job_id]

@router.post("/confirmar")
def confirmar_salvamento(data: ConfirmarSalvamentoRequest):
    if data.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    job = jobs[data.job_id]
    if job["status"] != "aguardando_confirmacao":
        raise HTTPException(status_code=400, detail=f"Job em status inválido: {job['status']}")
    try:
        resultado = salvar_prova_completa(
            id_usuario=data.id_usuario,
            dados_prova=data.dados_prova.dict(),
            questoes=[q.dict() for q in data.questoes]
        )
        jobs[data.job_id]["status"] = "salvo"
        return resultado
    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print("ERRO CONFIRMAR:", erro_completo)
        raise HTTPException(status_code=500, detail=erro_completo)
