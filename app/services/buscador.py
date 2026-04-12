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

# ── HELPERS ───────────────────────────────────────────────────────────────────

def encode_latin1(texto: str) -> str:
    if not texto:
        return ""
    try:
        return texto.encode("latin-1", errors="replace").decode("latin-1")
    except Exception:
        return texto

def gerar_url(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9\s-]", "", texto.lower())
    texto = re.sub(r"\s+", "-", texto.strip())
    return texto[:100] or "questao"

def get_claude():
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# ── BUSCA NA WEB ──────────────────────────────────────────────────────────────

# SerpApi — Google Search sem bloqueio
SERP_API_KEY = os.getenv("SERP_API_KEY", "7fd3bd7dfd5b4cb4fd478e6797918ac72210a227ed07c4c4c5f6791f2d5ea80a")

def buscar_resultados(query: str, num: int = 8) -> list:
    """
    Busca via SerpApi e retorna lista com url + texto (snippet).
    Usa snippets diretamente — não depende de acessar as páginas.
    """
    resultados = []
    api_key = os.getenv("SERP_API_KEY", SERP_API_KEY)
    print(f"[SERP] query={query[:60]}")
    try:
        params = {
            "api_key": api_key,
            "q":       query,
            "num":     min(10, num),
            "hl":      "pt",
            "gl":      "br",
            "engine":  "google",
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        print(f"[SERP] status={resp.status_code}")
        if not resp.ok:
            print(f"[SERP] erro: {resp.text[:200]}")
            return resultados
        data = resp.json()
        items = data.get("organic_results", [])
        print(f"[SERP] {len(items)} resultados")
        for item in items:
            link = item.get("link", "")
            if not link or not _url_valida(link):
                continue
            # Monta texto com título + snippet
            partes = []
            if item.get("title"):   partes.append(item["title"])
            if item.get("snippet"): partes.append(item["snippet"])
            resultados.append({"url": link, "texto": "\n".join(partes)})
    except Exception as e:
        print(f"[SERP] exception: {e}")
    return resultados

def buscar_urls(query: str, num: int = 8) -> list:
    return [r["url"] for r in buscar_resultados(query, num)]

def _url_valida(url: str) -> bool:
    bloqueados = ["google.", "youtube.", "facebook.", "instagram.",
                  "twitter.", "x.com", "tiktok.", "linkedin.", "wikipedia."]
    return not any(b in url for b in bloqueados)

def buscar_pagina(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "form", "iframe", "noscript"]):
            tag.decompose()
        linhas = [l.strip() for l in soup.get_text(separator="\n").splitlines()
                  if len(l.strip()) > 20]
        return "\n".join(linhas)
    except Exception as e:
        print(f"Erro página {url}: {e}")
        return ""


# ── CLAUDE: INTERPRETAR COMANDO ───────────────────────────────────────────────

PROMPT_INTERPRETACAO = """Você é especialista em concursos públicos brasileiros.

O usuário quer buscar questões com este pedido:
"{comando}"

Gere 3 queries de busca otimizadas para encontrar questões de concurso na internet.
Inclua termos como "questões", "gabarito", "concurso público", "prova" para refinar.

Retorne APENAS JSON válido sem markdown:
{{
  "queries": [
    "query 1",
    "query 2",
    "query 3"
  ]
}}"""

def interpretar_comando(comando: str) -> list:
    """Usa Claude para gerar queries de busca a partir do comando livre do usuário."""
    try:
        client = get_claude()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": PROMPT_INTERPRETACAO.format(comando=comando)}]
        )
        txt = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        m = re.search(r'\{.*\}', txt, re.DOTALL)
        if m:
            dados = json.loads(m.group())
            return dados.get("queries", [])
    except Exception as e:
        print(f"Erro interpretação: {e}")
    # fallback direto
    return [
        f"{comando} questões concurso público gabarito",
        f"{comando} prova concurso alternativas resolução",
        f"{comando} questões resolvidas concurso site:br",
    ]

# ── CLAUDE: EXTRAIR QUESTÕES DA PÁGINA ───────────────────────────────────────

PROMPT_EXTRACAO = """Você é um extrator de questões de concurso público brasileiro.

Analise o texto abaixo e extraia TODAS as questões de concurso que encontrar.

Retorne APENAS JSON válido neste formato exato, sem markdown, sem texto extra:
{{
  "questoes": [
    {{
      "enunciado": "texto do enunciado/contexto se houver, senão string vazia",
      "pergunta": "texto completo da questão/comando",
      "gabarito": "letra do gabarito se identificável, senão string vazia",
      "alternativas": [
        {{"letra": "A", "texto": "texto da alternativa", "correta": false}},
        {{"letra": "B", "texto": "texto da alternativa", "correta": false}},
        {{"letra": "C", "texto": "texto da alternativa", "correta": true}},
        {{"letra": "D", "texto": "texto da alternativa", "correta": false}},
        {{"letra": "E", "texto": "texto da alternativa", "correta": false}}
      ]
    }}
  ]
}}

Regras importantes:
- Extraia SOMENTE questões de concurso público com alternativas (A, B, C...)
- Questões Certo/Errado são válidas: alternativas [{{"letra":"C","texto":"Certo","correta":...}},{{"letra":"E","texto":"Errado","correta":...}}]
- Se não identificar o gabarito, deixe como string vazia ""
- Não inclua questões sem alternativas identificáveis
- Retorne JSON puro, sem nenhum texto antes ou depois

Texto:
{texto}"""

def extrair_questoes_com_claude(texto: str) -> list:
    if not texto or len(texto.strip()) < 100:
        return []
    try:
        client = get_claude()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
            messages=[{"role": "user",
                       "content": PROMPT_EXTRACAO.format(texto=texto[:6000])}]
        )
        txt = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        m = re.search(r'\{.*\}', txt, re.DOTALL)
        if m:
            dados = json.loads(m.group())
            return dados.get("questoes", [])
    except Exception as e:
        print(f"Erro extração Claude: {e}")
    return []

# ── BANCO: INSERÇÃO COMPATÍVEL COM O GERENCIADOR ──────────────────────────────

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

def inserir_pergunta(conn, id_usuario: int, questao: dict) -> int:
    """
    Segue exatamente o fluxo do gerenciador (cadastrar_pergunta_com_assunto.php):
    1. INSERT INTO pergunta (nome=timestamp, id_usuario)
    2. UPDATE com dados reais
    """
    cursor = conn.cursor()
    try:
        pergunta_txt = encode_latin1(questao.get("pergunta", ""))
        enunciado    = encode_latin1(questao.get("enunciado", "") or "")
        gabarito     = encode_latin1(questao.get("gabarito", "") or "")
        nome         = encode_latin1(pergunta_txt[:255])
        url          = gerar_url(pergunta_txt)

        # Passo 1: INSERT mínimo igual ao gerenciador
        cursor.execute("""
            INSERT INTO pergunta (nome, id_usuario)
            VALUES (%s, %s)
        """, (nome, id_usuario))

        id_pergunta = conn.insert_id()

        # Passo 2: UPDATE com todos os campos reais
        cursor.execute("""
            UPDATE pergunta SET
                id_personalizado = %s,
                nome             = %s,
                url              = %s,
                pergunta         = %s,
                enunciado        = %s,
                gabarito         = %s,
                finalizada       = 1,
                destaque         = 0
            WHERE id = %s
        """, (str(id_pergunta), nome, url, pergunta_txt, enunciado, gabarito, id_pergunta))

        conn.commit()
        return id_pergunta
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def inserir_respostas(conn, id_pergunta: int, alternativas: list):
    """
    Insere respostas exatamente como o gerenciador:
    - 2 alternativas → "Certo" / "Errado"
    - Mais → texto da alternativa com posição
    """
    cursor = conn.cursor()
    try:
        # Se não veio alternativas estruturadas, cria padrão 5 alternativas vazias
        if not alternativas:
            for i in range(1, 6):
                cursor.execute("""
                    INSERT INTO resposta (id_pergunta, nome, posicao, correta)
                    VALUES (%s, %s, %s, 0)
                """, (id_pergunta, str(i), i))
            conn.commit()
            return

        # Detecta se é questão Certo/Errado
        letras = [a.get("letra", "").upper() for a in alternativas]
        is_certo_errado = set(letras) <= {"C", "E", "CERTO", "ERRADO"} and len(alternativas) == 2

        for i, alt in enumerate(alternativas, start=1):
            if is_certo_errado:
                nome = "Certo" if i == 1 else "Errado"
            else:
                nome = encode_latin1(alt.get("texto", "") or str(i))

            correta = 1 if alt.get("correta") else 0
            cursor.execute("""
                INSERT INTO resposta (id_pergunta, nome, posicao, correta)
                VALUES (%s, %s, %s, %s)
            """, (id_pergunta, nome, i, correta))

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def vincular_assuntos(conn, id_usuario: int, id_pergunta: int, ids_assunto: list):
    """
    Vincula a pergunta aos assuntos — um INSERT por id_assunto,
    exatamente como o loop do gerenciador em cadastrar_pergunta_com_assunto.php
    """
    if not ids_assunto:
        return
    cursor = conn.cursor()
    try:
        for id_assunto in ids_assunto:
            if not id_assunto:
                continue
            # Evita duplicata
            cursor.execute("""
                SELECT id FROM vinculo_assunto_pergunta
                WHERE id_pergunta = %s AND id_assunto = %s LIMIT 1
            """, (id_pergunta, id_assunto))
            if cursor.fetchone():
                continue
            cursor.execute("""
                INSERT INTO vinculo_assunto_pergunta (id_assunto, id_pergunta, id_usuario)
                VALUES (%s, %s, %s)
            """, (id_assunto, id_pergunta, id_usuario))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

# ── PROCESSO PRINCIPAL ────────────────────────────────────────────────────────

def processar_busca(
    id_usuario: int,
    comando: str,            # texto livre do usuário
    limite: int = 50,
    ids_assunto: list = None # IDs das folhas selecionadas nos dropdowns
) -> dict:
    log = []
    inseridas = 0
    descartadas = 0
    ids_assunto = ids_assunto or []

    def info(msg): log.append({"tipo": "info", "msg": msg})
    def ok(msg):   log.append({"tipo": "ok",   "msg": msg})
    def warn(msg): log.append({"tipo": "warn", "msg": msg})
    def err(msg):  log.append({"tipo": "err",  "msg": msg})

    def get_conn():
        """Retorna conexão fresca — reconecta se necessário."""
        try:
            c = get_connection()
            c.ping(reconnect=True)
            return c
        except Exception as e:
            raise Exception(f"Falha ao conectar ao banco: {e}")

    info("Conectando ao banco...")
    conn = get_conn()
    ok("Conexão estabelecida.")

    # 1. Claude interpreta o comando e gera queries
    info(f'Interpretando: "{comando}"')
    queries = interpretar_comando(comando)
    ok(f"{len(queries)} queries geradas.")

    todas_questoes = []
    urls_visitadas = set()

    # 2. Para cada query, busca e extrai questões
    for query in queries:
        if len(todas_questoes) >= limite * 3:
            break

        info(f'Buscando: "{query[:70]}"')
        try:
            resultados = buscar_resultados(query, num=5)
        except Exception as e:
            err(f"Erro na busca: {str(e)[:100]}")
            resultados = []

        if not resultados:
            warn("Nenhum resultado encontrado para esta query.")
            api_key = os.getenv("SERP_API_KEY", SERP_API_KEY)
            info(f"SERP API Key: {'Sim' if api_key else 'NÃO'}")
        ok(f"{len(resultados)} páginas encontradas.")

        for r in resultados:
            if len(todas_questoes) >= limite * 3:
                break
            url   = r["url"]
            texto = r["texto"]  # snippet do SerpApi

            if url in urls_visitadas:
                continue
            urls_visitadas.add(url)

            # Tenta ler a página — se falhar usa o snippet
            info(f"Lendo: {url[:80]}")
            texto_pagina = buscar_pagina(url)
            if texto_pagina and len(texto_pagina) > 200:
                texto = texto_pagina  # página completa disponível
            elif not texto:
                warn("Página inacessível e sem snippet.")
                continue

            info("Extraindo questões com IA...")
            questoes = extrair_questoes_com_claude(texto)
            ok(f"{len(questoes)} questões encontradas.")
            todas_questoes.extend(questoes)
            time.sleep(0.5)

    ok(f"Total coletado: {len(todas_questoes)} questões brutas.")

    # 3. Filtra, valida e insere
    for q in todas_questoes:
        if inseridas >= limite:
            break
        try:
            pergunta_txt = (q.get("pergunta") or "").strip()

            if len(pergunta_txt) < 30:
                descartadas += 1
                continue

            if not q.get("alternativas"):
                descartadas += 1
                warn(f"Sem alternativas: {pergunta_txt[:50]}...")
                continue

            if questao_duplicada(conn, pergunta_txt):
                descartadas += 1
                warn(f"Duplicata: {pergunta_txt[:50]}...")
                continue

            # Reconecta antes de inserir (evita timeout após busca longa)
            try:
                conn.ping(reconnect=True)
            except Exception:
                conn = get_conn()

            # Insere pergunta
            id_pergunta = inserir_pergunta(conn, id_usuario, q)

            # Insere respostas
            inserir_respostas(conn, id_pergunta, q.get("alternativas", []))

            # Vincula assuntos (um por raiz, como o gerenciador)
            vincular_assuntos(conn, id_usuario, id_pergunta, ids_assunto)

            inseridas += 1
            ok(f"Inserida #{id_pergunta}: {pergunta_txt[:60]}...")

        except Exception as e:
            descartadas += 1
            err(f"Erro: {str(e)[:80]}")

    conn.close()
    ok(f"Concluído. {inseridas} inseridas, {descartadas} descartadas.")

    return {"inseridas": inseridas, "descartadas": descartadas, "log": log}
