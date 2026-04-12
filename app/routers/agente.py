from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from app.services.buscador import processar_busca
from app.database import get_connection

router = APIRouter()
jobs = {}

# ── MODELS ────────────────────────────────────────────────────────────────────

class BuscaLivreRequest(BaseModel):
    id_usuario: int
    comando: str                          # texto livre: "busque questões de matemática nível médio"
    limite: int = 50
    ids_assunto: Optional[List[int]] = [] # IDs das folhas selecionadas nos dropdowns

# mantido para compatibilidade
class BuscaTematicaRequest(BaseModel):
    id_usuario: int
    disciplina: str = "Todas"
    banca: str = "Todas"
    ano_ini: int = 2018
    limite: int = 50
    id_assunto: Optional[int] = None
    ids_assunto: Optional[List[int]] = []

# ── BACKGROUND ────────────────────────────────────────────────────────────────

def executar_busca_bg(job_id: str, params: dict):
    try:
        jobs[job_id]["status"] = "executando"
        resultado = processar_busca(**params)
        jobs[job_id]["status"] = "concluido"
        jobs[job_id]["resultado"] = resultado
        jobs[job_id]["log"] = resultado.get("log", [])
    except Exception as e:
        jobs[job_id]["status"] = "erro"
        jobs[job_id]["erro"] = str(e)

# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@router.post("/buscar")
def buscar(data: BuscaLivreRequest, background_tasks: BackgroundTasks):
    """Endpoint principal — recebe comando livre em linguagem natural."""
    import uuid
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "aguardando", "resultado": None, "log": []}

    params = {
        "id_usuario": data.id_usuario,
        "comando":    data.comando,
        "limite":     data.limite,
        "ids_assunto": data.ids_assunto or [],
    }
    background_tasks.add_task(executar_busca_bg, job_id, params)
    return {"job_id": job_id, "status": "iniciado"}

@router.post("/busca-tematica")
def busca_tematica(data: BuscaTematicaRequest, background_tasks: BackgroundTasks):
    """Mantido para compatibilidade — redireciona para busca livre."""
    import uuid
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "aguardando", "resultado": None, "log": []}

    # Monta comando a partir dos campos antigos
    comando = f"questões de {data.disciplina}"
    if data.banca and data.banca.lower() != "todas":
        comando += f" banca {data.banca}"
    if data.ano_ini:
        comando += f" a partir de {data.ano_ini}"

    ids_assunto = data.ids_assunto or ([data.id_assunto] if data.id_assunto else [])

    params = {
        "id_usuario":  data.id_usuario,
        "comando":     comando,
        "limite":      data.limite,
        "ids_assunto": ids_assunto,
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

        cursor.execute("SELECT COUNT(*) as total FROM prova")
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
            SELECT id, nome, id_assunto AS id_pai, posicao_gerar_nome
            FROM assunto
            ORDER BY posicao_gerar_nome ASC, nome ASC
        """)
        return {"assuntos": cursor.fetchall()}
    finally:
        cursor.close()
        conn.close()

@router.get("/questoes-inseridas")
def questoes_inseridas(limite: int = 500):
    """
    Retorna questões inseridas ou alteradas pelo agente (id_personalizado numérico = gerado pelo agente).
    Inclui os assuntos vinculados para exibição na listagem.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Busca questões inseridas pelo agente ordenadas pelas mais recentes
        cursor.execute("""
            SELECT
                p.id,
                p.id_personalizado,
                p.nome,
                LEFT(p.pergunta, 120) AS pergunta,
                p.finalizada,
                p.data_cadastro
            FROM pergunta p
            WHERE p.id_personalizado REGEXP '^[0-9]+$'
            ORDER BY p.id DESC
            LIMIT %s
        """, (limite,))
        questoes = cursor.fetchall()

        # Para cada questão, busca os assuntos vinculados
        ids = [q['id'] for q in questoes]
        assuntos_map = {}
        if ids:
            formato = ','.join(['%s'] * len(ids))
            cursor.execute(f"""
                SELECT vap.id_pergunta, a.nome
                FROM vinculo_assunto_pergunta vap
                INNER JOIN assunto a ON a.id = vap.id_assunto
                WHERE vap.id_pergunta IN ({formato})
                ORDER BY a.posicao_gerar_nome ASC, a.nome ASC
            """, ids)
            for row in cursor.fetchall():
                pid = row['id_pergunta']
                if pid not in assuntos_map:
                    assuntos_map[pid] = []
                assuntos_map[pid].append(row['nome'])

        for q in questoes:
            q['assuntos'] = assuntos_map.get(q['id'], [])
            # Converte data para string ISO
            if q.get('data_cadastro'):
                q['data_cadastro'] = str(q['data_cadastro'])

        return {"questoes": questoes, "total": len(questoes)}
    finally:
        cursor.close()
        conn.close()

@router.get("/testar-busca")
def testar_busca():
    """Testa se a Google Custom Search API está funcionando."""
    import requests, os
    api_key = os.getenv("GOOGLE_API_KEY", "")
    cx      = os.getenv("GOOGLE_CX", "")
    if not api_key or not cx:
        return {"ok": False, "erro": "Variáveis GOOGLE_API_KEY ou GOOGLE_CX não configuradas"}
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": "questões concurso público", "num": 1},
            timeout=10
        )
        data = resp.json()
        if not resp.ok:
            return {"ok": False, "status": resp.status_code, "erro": data.get("error", {}).get("message", str(data))}
        items = data.get("items", [])
        return {
            "ok": True,
            "status": resp.status_code,
            "total_results": data.get("searchInformation", {}).get("totalResults"),
            "primeiro_resultado": items[0].get("link") if items else None
        }
    except Exception as e:
        return {"ok": False, "erro": str(e)}
