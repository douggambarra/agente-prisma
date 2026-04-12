import requests
from bs4 import BeautifulSoup
import re
import time
import json
import os
import unicodedata
from app.database import get_connection

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── HELPERS ──────────────────────────────────────────────────────────────────

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

def get_claude():
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# ── BUSCA NO GOOGLE ───────────────────────────────────────────────────────────

def buscar_urls_google(query: str, num_resultados: int = 10) -> list:
    """
    Busca no Google e retorna lista de URLs de resultados orgânicos.
    Usa a versão leve do Google (sem JS).
    """
    urls = []
    try:
        search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num={num_resultados}&hl=pt-BR"
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Extrai links dos resultados orgânicos
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            # Google envolve os links em /url?q=...
            match = re.search(r"/url\?q=(https?://[^&]+)", href)
            if match:
                url = requests.utils.unquote(match.group(1))
                # Filtra domínios irrelevantes
                if any(skip in url for skip in ["google.com", "youtube.com", "facebook.com",
                                                 "instagram.com", "twitter.com", "wikipedia.org"]):
                    continue
                if url not in urls:
                    urls.append(url)
            if len(urls) >= num_resultados:
                break
    except Exception as e:
        print(f"Erro Google search: {e}")

    # Fallback: tenta Bing se Google não retornou nada
    if not urls:
        urls = buscar_urls_bing(query, num_resultados)

    return urls


def buscar_urls_bing(query: str, num_resultados: int = 10) -> list:
    urls = []
    try:
        search_url = f"https://www.bing.com/search?q={requests.utils.quote(query)}&count={num_resultados}&setlang=pt-BR"
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("li.b_algo a[href]"):
            href = a.get("href", "")
            if href.startswith("http") and href not in urls:
                if not any(skip in href for skip in ["bing.com", "microsoft.com",
                                                      "youtube.com", "facebook.com"]):
                    urls.append(href)
            if len(urls) >= num_resultados:
                break
    except Exception as e:
        print(f"Erro Bing search: {e}")
    return urls

# ── EXTRAÇÃO DE QUESTÕES VIA CLAUDE ──────────────────────────────────────────

PROMPT_EXTRACAO = """Você é um extrator de questões de concurso público brasileiro.

Analise o texto abaixo (HTML convertido em texto) e extraia TODAS as questões de concurso que encontrar.

Para cada questão, retorne um JSON com este formato exato:
{{
  "questoes": [
    {{
      "enunciado": "texto do enunciado/contexto (se houver)",
      "pergunta": "texto completo da questão",
      "alternativas": [
        {{"letra": "A", "texto": "texto da alternativa", "correta": false}},
        {{"letra": "B", "texto": "texto da alternativa", "correta": false}},
        {{"letra": "C", "texto": "texto da alternativa", "correta": true}},
        {{"letra": "D", "texto": "texto da alternativa", "correta": false}},
        {{"letra": "E", "texto": "texto da alternativa", "correta": false}}
      ],
      "gabarito": "C",
      "banca": "nome da banca se identificável",
      "ano": "ano se identificável"
    }}
  ]
}}

Regras:
- Extraia APENAS questões de concurso público (não vestibular, não exercício escolar)
- Se não conseguir identificar o gabarito, deixe "gabarito" como ""
- Se não houver alternativas identificáveis, não inclua a questão
- Retorne APENAS o JSON, sem explicações

Texto:
{texto}"""


def extrair_questoes_com_claude(texto_pagina: str) -> list:
    """Usa o Claude para extrair questões estruturadas de um texto de página."""
    if not texto_pagina or len(texto_pagina.strip()) < 100:
        return []

    # Limita o texto para não estourar o contexto
    texto = texto_pagina[:12000]

    try:
        client = get_claude()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": PROMPT_EXTRACAO.format(texto=texto)
            }]
        )
        resposta = msg.content[0].text.strip()
        resposta = resposta.replace("```json", "").replace("```", "").strip()

        # Extrai só o JSON mesmo que venha com texto em volta
        match = re.search(r'\{.*\}', resposta, re.DOTALL)
        if match:
            dados = json.loads(match.group())
            return dados.get("questoes", [])
    except Exception as e:
        print(f"Erro Claude extração: {e}")

    return []


def buscar_pagina(url: str) -> str:
    """Busca uma página e retorna o texto limpo."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove scripts, estilos, menus, rodapés
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        texto = soup.get_text(separator="\n", strip=True)
        # Remove linhas muito curtas (menus, breadcrumbs)
        linhas = [l for l in texto.splitlines() if len(l.strip()) > 20]
        return "\n".join(linhas)
    except Exception as e:
        print(f"Erro ao buscar {url}: {e}")
        return ""

# ── BANCO DE DADOS ────────────────────────────────────────────────────────────

def inserir_questao(conn, id_usuario: int, questao: dict) -> int:
    cursor = conn.cursor()
    try:
        enunciado = encode_latin1(questao.get("enunciado", "") or "")
        pergunta  = encode_latin1(questao.get("pergunta", "") or "")
        gabarito  = encode_latin1(questao.get("gabarito", "") or "")
        nome      = encode_latin1((questao.get("pergunta", "")[:80] or "questao"))
        url       = gerar_url(questao.get("pergunta", "questao"))
        id_pers   = str(questao.get("id_personalizado", "0"))[:50]

        cursor.execute("""
            INSERT INTO pergunta
              (id_usuario, finalizada, id_personalizado, nome, url, pergunta, enunciado, gabarito)
            VALUES (%s, 1, %s, %s, %s, %s, %s, %s)
        """, (id_usuario, id_pers, nome, url, pergunta, enunciado, gabarito))

        id_pergunta = cursor.lastrowid

        for i, alt in enumerate(questao.get("alternativas", [])):
            correta  = 1 if alt.get("correta") else 0
            nome_alt = encode_latin1(alt.get("texto", "") or "")
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
    """Vincula a pergunta a todos os assuntos selecionados (matéria, banca, região, ano...)."""
    if not ids_assunto:
        return
    cursor = conn.cursor()
    try:
        for id_assunto in ids_assunto:
            if not id_assunto:
                continue
            cursor.execute("""
                SELECT id FROM vinculo_assunto_pergunta
                WHERE id_pergunta = %s AND id_assunto = %s LIMIT 1
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

# ── PROCESSO PRINCIPAL ────────────────────────────────────────────────────────

def processar_busca(
    id_usuario: int,
    disciplina: str,
    banca: str,
    ano_ini: int,
    limite: int,
    ids_assunto: list = None
) -> dict:
    log = []
    inseridas = 0
    descartadas = 0
    ids_assunto = ids_assunto or []

    def info(msg):  log.append({"tipo": "info", "msg": msg})
    def ok(msg):    log.append({"tipo": "ok",   "msg": msg})
    def warn(msg):  log.append({"tipo": "warn", "msg": msg})
    def err(msg):   log.append({"tipo": "err",  "msg": msg})

    info("Conectando ao banco MySQL...")
    conn = get_connection()
    ok("Conexão estabelecida.")

    # Monta queries de busca variadas para cobrir mais fontes
    banca_q = banca if banca and banca.lower() != "todas" else "concurso público"
    queries = [
        f'questões concurso "{disciplina}" {banca_q} {ano_ini} gabarito site:br',
        f'questões de {disciplina} {banca_q} concurso {ano_ini} alternativas gabarito',
        f'{disciplina} questões resolvidas {banca_q} {ano_ini} concurso público',
    ]

    todas_questoes = []
    urls_visitadas = set()

    for query in queries:
        if len(todas_questoes) >= limite:
            break

        info(f'Buscando: "{query[:60]}..."')
        urls = buscar_urls_google(query, num_resultados=8)
        ok(f"{len(urls)} páginas encontradas.")

        for url in urls:
            if len(todas_questoes) >= limite * 2:  # busca extra para compensar descartes
                break
            if url in urls_visitadas:
                continue
            urls_visitadas.add(url)

            info(f"Lendo: {url[:70]}...")
            texto = buscar_pagina(url)
            if not texto:
                warn("Página inacessível, pulando.")
                continue

            info("Extraindo questões com IA...")
            questoes = extrair_questoes_com_claude(texto)
            ok(f"{len(questoes)} questões extraídas desta página.")
            todas_questoes.extend(questoes)
            time.sleep(1)  # respeita rate limit

    ok(f"Total bruto: {len(todas_questoes)} questões coletadas.")

    # Processa e insere
    for q in todas_questoes:
        if inseridas >= limite:
            break
        try:
            pergunta_txt = q.get("pergunta", "")
            if not pergunta_txt or len(pergunta_txt.strip()) < 30:
                descartadas += 1
                continue

            if questao_duplicada(conn, pergunta_txt):
                descartadas += 1
                warn(f"Duplicata ignorada: {pergunta_txt[:50]}...")
                continue

            if not q.get("alternativas"):
                descartadas += 1
                warn(f"Sem alternativas: {pergunta_txt[:50]}...")
                continue

            id_pergunta = inserir_questao(conn, id_usuario, q)
            vincular_assuntos(conn, id_usuario, id_pergunta, ids_assunto)

            inseridas += 1
            ok(f"Inserida: {pergunta_txt[:60]}...")

        except Exception as e:
            descartadas += 1
            err(f"Erro ao inserir: {str(e)[:80]}")

    conn.close()
    ok(f"Concluído. {inseridas} inseridas, {descartadas} descartadas.")

    return {
        "inseridas": inseridas,
        "descartadas": descartadas,
        "log": log
    }
