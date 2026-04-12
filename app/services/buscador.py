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

        id_pergunta = cursor.lastrowid

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


PROMPT_ANINHAR = """Você é um classificador de questões de concurso público brasileiro.

Dada uma questão e a lista de assuntos disponíveis no sistema, identifique quais assuntos 
da lista se aplicam a esta questão. Considere: matéria/disciplina, banca, ano, região, órgão, 
escolaridade, cargo/área.

Assuntos disponíveis (formato: id | raiz | nome):
{assuntos}

Questão:
{questao}

Retorne APENAS JSON válido sem markdown:
{{
  "ids_assunto": [1, 2, 3],
  "justificativa": "breve explicação"
}}

Selecione apenas os IDs que realmente se aplicam. Se nenhum se aplicar, retorne lista vazia."""

def identificar_assuntos(questao: dict, todos_assuntos: list) -> list:
    """
    Usa Claude para identificar quais assuntos do BD se encaixam na questão.
    Retorna lista de IDs das folhas compatíveis.
    """
    if not todos_assuntos:
        return []

    # Monta mapa de filhos para identificar folhas
    tem_filhos = set()
    for a in todos_assuntos:
        if a.get('id_pai'):
            tem_filhos.add(a['id_pai'])

    # Só folhas são vinculáveis
    folhas = [a for a in todos_assuntos if a['id'] not in tem_filhos]
    if not folhas:
        return []

    # Monta mapa id_raiz -> nome_raiz para contexto
    raiz_por_id = {}
    for a in todos_assuntos:
        if not a.get('id_pai'):
            raiz_por_id[a['id']] = a['nome']

    def get_raiz(assunto):
        pai = assunto.get('id_pai')
        if not pai:
            return assunto['nome']
        # sobe na hierarquia
        visitados = set()
        atual = assunto
        while atual.get('id_pai') and atual['id_pai'] not in visitados:
            visitados.add(atual['id'])
            pai_node = next((x for x in todos_assuntos if x['id'] == atual['id_pai']), None)
            if not pai_node:
                break
            atual = pai_node
        return atual['nome']

    # Lista resumida de folhas para o prompt (max 200 para não estourar contexto)
    folhas_resumo = folhas[:200]
    lista = "\n".join([
        f"{a['id']} | {get_raiz(a)} | {a['nome']}"
        for a in folhas_resumo
    ])

    texto_questao = f"{questao.get('enunciado','')} {questao.get('pergunta','')}".strip()[:1000]

    try:
        client = get_claude()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": PROMPT_ANINHAR.format(
                assuntos=lista,
                questao=texto_questao
            )}]
        )
        txt = msg.content[0].text.strip().replace("```json","").replace("```","").strip()
        import re
        m = re.search(r'\{.*\}', txt, re.DOTALL)
        if m:
            dados = json.loads(m.group())
            ids = [int(x) for x in dados.get("ids_assunto", []) if x]
            # Valida que os IDs existem e são folhas
            ids_validos = [i for i in ids if any(f['id'] == i for f in folhas)]
            return ids_validos
    except Exception as e:
        print(f"Erro identificar_assuntos: {e}")
    return []

def identificar_prova(questao: dict, conn) -> int | None:
    """
    Tenta encontrar uma prova no BD que corresponda à questão.
    Busca por banca + ano extraídos da questão.
    """
    banca = questao.get("banca", "")
    ano   = questao.get("ano", "")
    if not banca and not ano:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        if banca and ano:
            cursor.execute("""
                SELECT id FROM prova 
                WHERE nome LIKE %s AND YEAR(data_da_prova) = %s
                LIMIT 1
            """, (f"%{banca}%", str(ano)))
        elif banca:
            cursor.execute("SELECT id FROM prova WHERE nome LIKE %s LIMIT 1", (f"%{banca}%",))
        elif ano:
            cursor.execute("SELECT id FROM prova WHERE YEAR(data_da_prova) = %s LIMIT 1", (str(ano),))
        row = cursor.fetchone()
        cursor.close()
        return row['id'] if row else None
    except Exception as e:
        print(f"Erro identificar_prova: {e}")
        return None

def vincular_prova(conn, id_usuario: int, id_pergunta: int, id_prova: int):
    """Vincula pergunta à prova — igual ao gerenciador."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id FROM vinculo_prova_pergunta
            WHERE id_pergunta = %s AND id_prova = %s LIMIT 1
        """, (id_pergunta, id_prova))
        if cursor.fetchone():
            return
        cursor.execute("""
            INSERT INTO vinculo_prova_pergunta (id_prova, id_pergunta, id_usuario)
            VALUES (%s, %s, %s)
        """, (id_prova, id_pergunta, id_usuario))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Erro vincular_prova: {e}")
    finally:
        cursor.close()

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

    # Carrega todos os assuntos do BD para o aninhamento automático
    todos_assuntos = []
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, nome, id_assunto AS id_pai, posicao_gerar_nome FROM assunto ORDER BY posicao_gerar_nome ASC, nome ASC")
        todos_assuntos = cur.fetchall()
        cur.close()
        info(f"{len(todos_assuntos)} assuntos carregados para classificação.")
    except Exception as e:
        warn(f"Não foi possível carregar assuntos: {e}")

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

    # fecha conexão usada na busca — cada inserção abre a sua própria
    try: conn.close()
    except: pass

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

            # Abre conexão fresca para cada questão
            conn_ins = get_connection()

            try:
                if questao_duplicada(conn_ins, pergunta_txt):
                    descartadas += 1
                    warn(f"Duplicata: {pergunta_txt[:50]}...")
                    conn_ins.close()
                    continue

                id_pergunta = inserir_pergunta(conn_ins, id_usuario, q)
                inserir_respostas(conn_ins, id_pergunta, q.get("alternativas", []))

                # Identifica e vincula assuntos automaticamente via Claude
                ids_auto = identificar_assuntos(q, todos_assuntos)
                # Combina com os IDs manuais passados pelo usuário (se houver)
                ids_final = list(set(ids_assunto + ids_auto))
                if ids_final:
                    vincular_assuntos(conn_ins, id_usuario, id_pergunta, ids_final)
                    info(f"Vinculados {len(ids_final)} assunto(s).")

                # Tenta vincular a uma prova existente
                id_prova = identificar_prova(q, conn_ins)
                if id_prova:
                    vincular_prova(conn_ins, id_usuario, id_pergunta, id_prova)
                    info(f"Vinculada à prova #{id_prova}.")

                inseridas += 1
                ok(f"Inserida #{id_pergunta}: {pergunta_txt[:60]}...")
            finally:
                try: conn_ins.close()
                except: pass

        except Exception as e:
            descartadas += 1
            err(f"Erro: {str(e)[:80]}")

    ok(f"Concluído. {inseridas} inseridas, {descartadas} descartadas.")

    return {"inseridas": inseridas, "descartadas": descartadas, "log": log}
