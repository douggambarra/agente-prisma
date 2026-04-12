import requests
from bs4 import BeautifulSoup
import re
import time
from app.database import get_connection
from app.services.validador import validar_questao
import unicodedata

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    return texto.strip()

def encode_latin1(texto: str) -> str:
    try:
        return texto.encode("latin-1", errors="replace").decode("latin-1")
    except Exception:
        return texto

def gerar_url(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9\s-]", "", texto.lower())
    texto = re.sub(r"\s+", "-", texto.strip())
    return texto[:100]

def inserir_questao(conn, id_usuario: int, questao: dict) -> int:
    cursor = conn.cursor()
    try:
        enunciado = encode_latin1(questao.get("enunciado", ""))
        pergunta  = encode_latin1(questao.get("pergunta", ""))
        gabarito  = encode_latin1(questao.get("gabarito", ""))
        nome      = encode_latin1(questao.get("nome", "")[:255])
        url       = gerar_url(questao.get("nome", "questao"))
        id_pers   = questao.get("id_personalizado", "0")[:50]

        cursor.execute("""
            INSERT INTO pergunta
              (id_usuario, finalizada, id_personalizado, nome, url, pergunta, enunciado, gabarito)
            VALUES (%s, 1, %s, %s, %s, %s, %s, %s)
        """, (id_usuario, id_pers, nome, url, pergunta, enunciado, gabarito))

        id_pergunta = cursor.lastrowid

        for i, alt in enumerate(questao.get("alternativas", [])):
            correta = 1 if alt.get("correta") else 0
            nome_alt = encode_latin1(alt.get("texto", ""))
            cursor.execute("""
                INSERT INTO resposta (posicao, correta, id_pergunta, nome)
                VALUES (%s, %s, %s, %s)
            """, (i + 1, correta, id_pergunta, nome_alt))

        conn.commit()
        return id_pergunta
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def vincular_assuntos(conn, id_usuario: int, id_pergunta: int, ids_assunto: list):
    """
    Vincula a pergunta a TODOS os assuntos selecionados (matéria, banca, região, ano, etc.)
    seguindo a mesma hierarquia do BD — cada id é um nó folha da árvore de assunto.
    """
    if not ids_assunto:
        return
    cursor = conn.cursor()
    try:
        for id_assunto in ids_assunto:
            if not id_assunto:
                continue
            # Evita duplicata de vínculo
            cursor.execute("""
                SELECT id FROM vinculo_assunto_pergunta
                WHERE id_pergunta = %s AND id_assunto = %s
                LIMIT 1
            """, (id_pergunta, id_assunto))
            if cursor.fetchone():
                continue
            cursor.execute("""
                INSERT INTO vinculo_assunto_pergunta (id_usuario, id_assunto, id_pergunta)
                VALUES (%s, %s, %s)
            """, (id_usuario, id_assunto, id_pergunta))
        conn.commit()
    finally:
        cursor.close()

def questao_duplicada(conn, pergunta_texto: str) -> bool:
    cursor = conn.cursor()
    try:
        trecho = encode_latin1(pergunta_texto[:100])
        cursor.execute(
            "SELECT id FROM pergunta WHERE pergunta LIKE %s LIMIT 1",
            (f"%{trecho}%",)
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()

def buscar_pci_concursos(disciplina: str, banca: str, ano_ini: int, limite: int) -> list:
    questoes = []
    try:
        query = f"{disciplina} {banca} concurso {ano_ini}"
        url = f"https://www.pciconcursos.com.br/questoes/?q={requests.utils.quote(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        blocos = soup.select(".questao, .question, article")[:limite]
        for bloco in blocos:
            texto = bloco.get_text(separator=" ", strip=True)
            if len(texto) > 50:
                questoes.append({
                    "nome": texto[:80],
                    "pergunta": texto,
                    "enunciado": "",
                    "gabarito": "",
                    "id_personalizado": "pci",
                    "alternativas": [],
                    "fonte": "pci_concursos"
                })
            time.sleep(0.5)
    except Exception as e:
        print(f"Erro PCI: {e}")
    return questoes

def processar_busca(
    id_usuario: int,
    disciplina: str,
    banca: str,
    ano_ini: int,
    limite: int,
    ids_assunto: list = None   # lista com todos os IDs de assunto selecionados
) -> dict:
    log = []
    inseridas = 0
    descartadas = 0

    ids_assunto = ids_assunto or []

    log.append({"tipo": "info", "msg": "Conectando ao banco MySQL..."})
    conn = get_connection()
    log.append({"tipo": "ok", "msg": "Conexão estabelecida."})

    log.append({"tipo": "info", "msg": f"Buscando questões: {disciplina} | {banca} | a partir de {ano_ini}..."})
    questoes_brutas = buscar_pci_concursos(disciplina, banca, ano_ini, limite)
    log.append({"tipo": "ok", "msg": f"{len(questoes_brutas)} questões encontradas."})

    for q in questoes_brutas:
        try:
            if questao_duplicada(conn, q["pergunta"]):
                descartadas += 1
                log.append({"tipo": "warn", "msg": f"Duplicata ignorada: {q['nome'][:60]}"})
                continue

            valida, motivo = validar_questao(q)
            if not valida:
                descartadas += 1
                log.append({"tipo": "warn", "msg": f"Descartada ({motivo}): {q['nome'][:50]}"})
                continue

            id_pergunta = inserir_questao(conn, id_usuario, q)

            # Vincula TODOS os assuntos selecionados (matéria, banca, região, ano, etc.)
            vincular_assuntos(conn, id_usuario, id_pergunta, ids_assunto)

            inseridas += 1
            log.append({"tipo": "ok", "msg": f"Inserida: {q['nome'][:60]}"})

        except Exception as e:
            descartadas += 1
            log.append({"tipo": "err", "msg": f"Erro ao inserir: {str(e)[:80]}"})

    conn.close()
    log.append({"tipo": "ok", "msg": f"Concluído. {inseridas} inseridas, {descartadas} descartadas."})

    return {
        "inseridas": inseridas,
        "descartadas": descartadas,
        "log": log
    }
