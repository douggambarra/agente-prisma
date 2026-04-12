from fastapi import APIRouter
from app.database import get_connection
from app.services.validador import validar_questao

router = APIRouter()

@router.get("/verificar-gabaritos")
def verificar_gabaritos(limite: int = 500):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    problemas = []
    corrigidas = 0

    try:
        cursor.execute(f"""
            SELECT p.id, p.pergunta, p.gabarito
            FROM pergunta p
            WHERE p.finalizada = 1
            ORDER BY p.id DESC
            LIMIT {limite}
        """)
        questoes = cursor.fetchall()

        for q in questoes:
            id_q = q["id"]

            cursor2 = conn.cursor(dictionary=True)
            cursor2.execute(
                "SELECT id, correta, posicao FROM resposta WHERE id_pergunta = %s",
                (id_q,)
            )
            respostas = cursor2.fetchall()
            cursor2.close()

            tem_correta = any(r["correta"] == 1 for r in respostas)
            multiplas_corretas = sum(r["correta"] == 1 for r in respostas) > 1

            if not respostas:
                problemas.append({
                    "id": id_q,
                    "tipo": "sem_alternativas",
                    "descricao": "Questão sem nenhuma alternativa cadastrada"
                })
            elif not tem_correta:
                problemas.append({
                    "id": id_q,
                    "tipo": "sem_gabarito",
                    "descricao": "Nenhuma alternativa marcada como correta"
                })
            elif multiplas_corretas:
                problemas.append({
                    "id": id_q,
                    "tipo": "multiplos_gabaritos",
                    "descricao": "Mais de uma alternativa marcada como correta"
                })

        return {
            "verificadas": len(questoes),
            "problemas": len(problemas),
            "corrigidas": corrigidas,
            "lista": problemas[:100]
        }
    finally:
        cursor.close()
        conn.close()

@router.get("/verificar-duplicatas")
def verificar_duplicatas(limite: int = 1000):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    duplicatas = []

    try:
        cursor.execute(f"""
            SELECT id, LEFT(pergunta, 120) as trecho
            FROM pergunta
            WHERE finalizada = 1
            ORDER BY id DESC
            LIMIT {limite}
        """)
        questoes = cursor.fetchall()

        vistos = {}
        for q in questoes:
            trecho = (q["trecho"] or "").strip()[:80]
            if trecho in vistos:
                duplicatas.append({
                    "id_1": vistos[trecho],
                    "id_2": q["id"],
                    "trecho": trecho
                })
            else:
                vistos[trecho] = q["id"]

        return {
            "verificadas": len(questoes),
            "pares_duplicados": len(duplicatas),
            "lista": duplicatas[:50]
        }
    finally:
        cursor.close()
        conn.close()

@router.get("/verificar-encoding")
def verificar_encoding(limite: int = 500):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    problemas = []

    try:
        cursor.execute(f"""
            SELECT id, LEFT(pergunta, 300) as texto
            FROM pergunta
            WHERE finalizada = 1
            ORDER BY id DESC
            LIMIT {limite}
        """)
        questoes = cursor.fetchall()

        for q in questoes:
            texto = q["texto"] or ""
            if "?" * 3 in texto or "\ufffd" in texto:
                problemas.append({
                    "id": q["id"],
                    "tipo": "encoding_corrompido",
                    "descricao": "Possíveis caracteres corrompidos detectados"
                })

        return {
            "verificadas": len(questoes),
            "com_problema": len(problemas),
            "lista": problemas[:50]
        }
    finally:
        cursor.close()
        conn.close()

@router.get("/resumo")
def resumo_auditoria():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) as t FROM pergunta WHERE finalizada=1")
        total = cursor.fetchone()["t"]

        cursor.execute("""
            SELECT COUNT(DISTINCT p.id) as t FROM pergunta p
            LEFT JOIN resposta r ON r.id_pergunta = p.id AND r.correta = 1
            WHERE p.finalizada = 1 AND r.id IS NULL
        """)
        sem_gabarito = cursor.fetchone()["t"]

        cursor.execute("""
            SELECT COUNT(*) as t FROM pergunta p
            WHERE finalizada = 1
            AND (pergunta IS NULL OR LENGTH(TRIM(pergunta)) < 30)
        """)
        enunciado_curto = cursor.fetchone()["t"]

        return {
            "total": total,
            "sem_gabarito": sem_gabarito,
            "enunciado_curto": enunciado_curto,
            "saude_pct": round((1 - (sem_gabarito + enunciado_curto) / max(total, 1)) * 100, 1)
        }
    finally:
        cursor.close()
        conn.close()
