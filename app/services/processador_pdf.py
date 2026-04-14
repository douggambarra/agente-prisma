import os
import re
import json
import base64
import unicodedata
from typing import Optional
from app.database import get_connection

# ── HELPERS (idênticos ao buscador.py existente) ──────────────────────────────

def encode_latin1(texto: str) -> str:
    if not texto:
        return ""
    # Substituir símbolos que não existem em latin1 por equivalentes legíveis
    substituicoes = {
        # Lógica
        '∧': ' ^ ',   '∨': ' v ',   '¬': '~',
        '→': '->',    '↔': '<->',   '⊕': ' XOR ',
        '∀': '(A)',   '∃': '(E)',   '⊢': '|-',
        # Matemática
        '≤': '<=',    '≥': '>=',    '≠': '!=',
        '≈': '~=',    '∞': 'inf',   '∑': 'E',
        '∏': 'PI',    '√': 'sqrt',  '∫': 'int',
        '∂': 'd',     '∈': ' in ',  '∉': ' !in ',
        '⊂': ' C ',   '⊃': ' D ',  '∩': ' n ',
        '∪': ' U ',   '∅': '{}',    '×': 'x',
        '÷': '/',     '±': '+/-',   '·': '.',
        # Gregas maiúsculas
        'Α': 'A', 'Β': 'B', 'Γ': 'G', 'Δ': 'D', 'Ε': 'E',
        'Ζ': 'Z', 'Η': 'H', 'Θ': 'T', 'Ι': 'I', 'Κ': 'K',
        'Λ': 'L', 'Μ': 'M', 'Ν': 'N', 'Ξ': 'X', 'Ο': 'O',
        'Π': 'P', 'Ρ': 'R', 'Σ': 'S', 'Τ': 'T', 'Υ': 'U',
        'Φ': 'F', 'Χ': 'X', 'Ψ': 'Y', 'Ω': 'W',
        # Gregas minúsculas
        'α': 'alfa',  'β': 'beta',  'γ': 'gama',  'δ': 'delta',
        'ε': 'eps',   'ζ': 'zeta',  'η': 'eta',   'θ': 'teta',
        'ι': 'iota',  'κ': 'kapa',  'λ': 'lambda','μ': 'mi',
        'ν': 'ni',    'ξ': 'xi',    'ο': 'o',     'π': 'pi',
        'ρ': 'ro',    'σ': 'sigma', 'τ': 'tau',   'υ': 'ipsilon',
        'φ': 'fi',    'χ': 'qui',   'ψ': 'psi',   'ω': 'omega',
        # Outros comuns em provas
        '°': 'o',     '²': '2',     '³': '3',     '¹': '1',
        '½': '1/2',   '¼': '1/4',   '¾': '3/4',
        '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-', '\u2026': '...',
    }
    for simbolo, substituto in substituicoes.items():
        texto = texto.replace(simbolo, substituto)
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

# ── PROMPT DE EXTRAÇÃO ────────────────────────────────────────────────────────

PROMPT_EXTRACAO_PDF = """Você é um especialista em processar provas de concursos públicos brasileiros.

Analise o(s) PDF(s) enviado(s) e extraia todas as informações.

Pode haver 1 ou 2 PDFs:
- 2 PDFs: um é o caderno de questões e outro é o gabarito separado.
- 1 PDF: pode conter questões + gabarito juntos, ou apenas as questões.

Retorne APENAS JSON válido, sem markdown, neste formato exato:

{
  "dados_prova": {
    "nome": "nome completo da prova (ex: Escrivão e Inspetor de Polícia - FUNDATEC 2026)",
    "banca": "nome da banca (ex: FUNDATEC, CESPE, FCC, VUNESP)",
    "id_orgao": null,
    "data_da_prova": "YYYY-MM-DD ou string vazia se não identificada"
  },
  "questoes": [
    {
      "numero": 1,
      "enunciado": "texto do enunciado/contexto (se houver texto base antes da questão, senão string vazia)",
      "pergunta": "texto completo do comando da questão",
      "gabarito": "A",
      "anulada": false,
      "disciplina": "nome da disciplina (ex: Língua Portuguesa, Informática, Direito Penal)",
      "alternativas": [
        {"letra": "A", "texto": "texto da alternativa A", "correta": true},
        {"letra": "B", "texto": "texto da alternativa B", "correta": false},
        {"letra": "C", "texto": "texto da alternativa C", "correta": false},
        {"letra": "D", "texto": "texto da alternativa D", "correta": false},
        {"letra": "E", "texto": "texto da alternativa E", "correta": false}
      ]
    }
  ]
}

Regras:
- Extraia TODAS as questões numeradas da prova
- Marque "correta: true" apenas na alternativa do gabarito
- Se gabarito não identificado: todas as alternativas com "correta: false" e "gabarito": ""
- Questões Certo/Errado: apenas 2 alternativas [{"letra":"C","texto":"Certo",...},{"letra":"E","texto":"Errado",...}]
- QUESTÕES ANULADAS: se no gabarito a questão aparecer marcada como "ANULADA", "Anulada", "*" (asterisco no número), "A" com indicação especial, ou qualquer outra marcação que indique anulação, defina "gabarito": "ANULADA" e "anulada": true
- PRESERVE todos os caracteres especiais exatamente como aparecem no PDF: símbolos matemáticos (∑, √, π, ≤, ≥, ≠, ×, ÷), lógicos (∧, ∨, ¬, →, ↔, ∀, ∃), letras gregas (α, β, γ, θ), acentos e cedilha do português (ã, ç, é, etc.), e qualquer outro símbolo especial
- NUNCA substitua símbolos especiais por texto (ex: não escreva "nao-p" no lugar de "¬p", nem "V" no lugar de "∨")
- Retorne JSON puro sem nenhum texto antes ou depois"""


PROMPT_TEXTO_LOTE = """Você é um especialista em processar provas de concursos públicos brasileiros.

Abaixo está o TEXTO EXTRAÍDO de uma prova de concurso. Extraia APENAS as questões de número {inicio} até {fim}.
{gabarito_texto}

TEXTO DA PROVA:
{texto_prova}

Retorne APENAS JSON válido, sem markdown:

{{
  "questoes": [
    {{
      "numero": {inicio},
      "enunciado": "texto do enunciado/contexto ou string vazia",
      "pergunta": "texto completo do comando da questão",
      "gabarito": "A",
      "anulada": false,
      "disciplina": "nome da disciplina",
      "alternativas": [
        {{"letra": "A", "texto": "texto", "correta": true}},
        {{"letra": "B", "texto": "texto", "correta": false}},
        {{"letra": "C", "texto": "texto", "correta": false}},
        {{"letra": "D", "texto": "texto", "correta": false}},
        {{"letra": "E", "texto": "texto", "correta": false}}
      ]
    }}
  ]
}}

Regras:
- Extraia SOMENTE questões do {inicio} ao {fim}
- Marque "correta: true" apenas na alternativa do gabarito
- QUESTÕES ANULADAS: defina "gabarito": "ANULADA" e "anulada": true
- PRESERVE todos os caracteres especiais (matematicos, logicos, gregos)
- Questoes Certo/Errado: apenas 2 alternativas [Certo, Errado]
- Retorne JSON puro sem nenhum texto antes ou depois"""

PROMPT_DADOS_PROVA = """Analise o texto abaixo de uma prova de concurso e extraia os dados.
Retorne APENAS JSON sem markdown:
{{"nome":"nome completo da prova","banca":"nome da banca","id_orgao":null,"data_da_prova":"YYYY-MM-DD ou vazio"}}

TEXTO:
{texto}"""


def _extrair_texto_pdf(conteudo: bytes) -> str:
    """Extrai texto de um PDF usando pypdf."""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(conteudo))
        texto = ""
        for page in reader.pages:
            texto += page.extract_text() + "\n"
        return texto
    except Exception as e:
        print(f"Erro ao extrair texto do PDF: {e}")
        return ""


def processar_pdfs(conteudo_prova: bytes, conteudo_gabarito: Optional[bytes] = None, modelo: str = "sonnet", progresso: dict = None) -> dict:
    """
    Extrai texto do PDF uma única vez e processa em lotes de texto.
    Evita reenviar o PDF inteiro a cada lote — resolve o rate limit.
    """
    import time

    def atualizar(etapa, lote_atual=0, total_lotes=0, questoes=0):
        if progresso is not None:
            progresso["etapa"] = etapa
            progresso["lote_atual"] = lote_atual
            progresso["total_lotes"] = total_lotes
            progresso["questoes"] = questoes
        print(etapa)

    modelos = {
        "haiku":  "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "opus":   "claude-opus-4-6",
    }
    model_id = modelos.get(modelo, "claude-sonnet-4-6")
    print(f"Modelo: {model_id}")
    client = get_claude()

    # Passo 1: extrai texto dos PDFs (uma única vez)
    atualizar("Extraindo texto dos PDFs...")
    texto_prova = _extrair_texto_pdf(conteudo_prova)
    texto_gabarito = _extrair_texto_pdf(conteudo_gabarito) if conteudo_gabarito else ""

    print(f"Texto extraído: {len(texto_prova)} caracteres")
    print(f"Primeiros 500 chars: {texto_prova[:500]}")
    print(f"Últimos 500 chars: {texto_prova[-500:]}")

    if not texto_prova:
        # Fallback: PDF é imagem, usa visão do Claude (só 1 chamada)
        atualizar("PDF é imagem — usando visão da IA (1 chamada)...")
        return _processar_pdf_visao(client, model_id, conteudo_prova, conteudo_gabarito, progresso)

    # Passo 2: extrai dados da prova a partir do texto
    atualizar("Identificando dados da prova...")
    dados_prova = _extrair_dados_texto(client, model_id, texto_prova[:3000])

    # Passo 3: conta questões
    atualizar("Contando questões...")
    total = _contar_questoes_texto(texto_prova)
    print(f"Total detectado: {total} questões")

    # Passo 4: processa em lotes de texto (sem reenviar PDF)
    LOTE = 50
    total_lotes = max(1, (total + LOTE - 1) // LOTE)
    todas_questoes = []

    gabarito_texto = f"\nGABARITO:\n{texto_gabarito[:5000]}" if texto_gabarito else ""

    # Passo 3.5: divide texto em blocos por questão
    atualizar("Dividindo texto por questões...")
    blocos = _dividir_texto_por_questoes(texto_prova, total, LOTE)
    print(f"Blocos encontrados: {len(blocos)}")

    for idx, inicio in enumerate(range(1, total + 1, LOTE), start=1):
        fim = min(inicio + LOTE - 1, total)
        atualizar(
            f"Extraindo questões {inicio} a {fim}...",
            lote_atual=idx, total_lotes=total_lotes,
            questoes=len(todas_questoes)
        )

        # Monta texto apenas com as questões deste lote
        if blocos and len(blocos) > 1:
            texto_lote = ""
            for n in range(inicio, fim + 1):
                if n in blocos:
                    texto_lote += blocos[n] + "\n"
            if not texto_lote:
                texto_lote = texto_prova  # fallback
        else:
            texto_lote = texto_prova

        questoes = _processar_lote_texto(
            client, model_id,
            texto_lote, gabarito_texto,
            inicio, fim
        )
        todas_questoes.extend(questoes)
        atualizar(
            f"Lote {idx}/{total_lotes} concluído — {len(todas_questoes)} questões",
            lote_atual=idx, total_lotes=total_lotes,
            questoes=len(todas_questoes)
        )

        # Pequena pausa entre lotes (texto é muito menor que PDF)
        if idx < total_lotes:
            time.sleep(5)

    atualizar(f"Pronto! {len(todas_questoes)} questões extraídas.", total_lotes, total_lotes, len(todas_questoes))
    return {"dados_prova": dados_prova, "questoes": todas_questoes}


def _contar_questoes_texto(texto: str) -> int:
    """Conta questões pelo maior número de questão encontrado no texto."""
    # Padrões específicos de questão — evita pegar anos, valores, etc.
    padroes = [
        r'QUEST[ÃA]O\s+(\d+)',           # QUESTÃO 70
        r'Quest[ãa]o\s+(\d+)',            # Questão 70
        r'^\s*(\d{1,3})\s*[–\-]\s+[A-Z]', # 70 – Assinale
        r'^\s*(\d{1,3})\s*\.\s+[A-Z]',    # 70. Assinale
        r'^\s*(\d{1,3})\s*\)\s*[A-Z]',    # 70) Assinale
    ]
    maior = 0
    for padrao in padroes:
        nums = re.findall(padrao, texto, re.MULTILINE)
        if nums:
            try:
                m = max(int(n) for n in nums if int(n) <= 1000)
                if m > maior:
                    maior = m
            except Exception:
                pass

    # Fallback: conta ocorrências de "QUESTÃO" no texto
    if maior == 0:
        ocorrencias = re.findall(r'QUEST[ÃA]O\s+\d+', texto, re.IGNORECASE)
        maior = len(ocorrencias) if ocorrencias else 50

    print(f"Total de questões detectado: {maior}")
    return maior


def _extrair_dados_texto(client, model_id: str, texto: str) -> dict:
    """Extrai nome, banca e data da prova a partir do texto."""
    try:
        msg = client.messages.create(
            model=model_id,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": PROMPT_DADOS_PROVA.format(texto=texto)
            }]
        )
        txt = msg.content[0].text.strip()
        txt = re.sub(r"^```json\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt).strip()
        return json.loads(txt)
    except Exception as e:
        print(f"Erro dados prova: {e}")
        return {"nome": "", "banca": "", "id_orgao": None, "data_da_prova": ""}


def _processar_lote_texto(client, model_id: str, texto_prova: str,
                           gabarito_texto: str, inicio: int, fim: int) -> list:
    """Processa um lote enviando apenas texto — sem PDF."""
    import time

    # Limita o texto para não estourar tokens (~12k chars por lote)
    prompt = PROMPT_TEXTO_LOTE.format(
        inicio=inicio, fim=fim,
        gabarito_texto=gabarito_texto,
        texto_prova=texto_prova[:40000]
    )

    for tentativa in range(3):
        try:
            msg = client.messages.create(
                model=model_id,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}]
            )
            txt = msg.content[0].text.strip()
            txt = re.sub(r"^```json\s*", "", txt)
            txt = re.sub(r"\s*```$", "", txt).strip()
            try:
                return json.loads(txt).get("questoes", [])
            except json.JSONDecodeError:
                m = re.search(r'\{.*\}', txt, re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group()).get("questoes", [])
                    except Exception:
                        pass
                return _recuperar_questoes_parciais(txt)
        except Exception as e:
            if 'rate_limit' in str(e).lower() and tentativa < 2:
                print(f"Rate limit, aguardando 30s (tentativa {tentativa+1}/3)...")
                time.sleep(30)
                continue
            print(f"Erro lote {inicio}-{fim}: {e}")
            return []
    return []


def _processar_pdf_visao(client, model_id: str, conteudo_prova: bytes,
                          conteudo_gabarito: Optional[bytes], progresso: dict) -> dict:
    """
    Fallback para PDFs que são imagens (sem texto extraível).
    Usa visão do Claude com 1 única chamada — aceita truncamento.
    """
    def atualizar(etapa, **kw):
        if progresso is not None:
            progresso["etapa"] = etapa
        print(etapa)

    atualizar("PDF é imagem — processando com visão da IA...")

    content = [{
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(conteudo_prova).decode("utf-8")
        },
        "title": "Prova"
    }]
    if conteudo_gabarito:
        content.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(conteudo_gabarito).decode("utf-8")
            },
            "title": "Gabarito"
        })
    content.append({"type": "text", "text": PROMPT_EXTRACAO_PDF})

    try:
        msg = client.messages.create(
            model=model_id,
            max_tokens=16000,
            messages=[{"role": "user", "content": content}]
        )
        txt = msg.content[0].text.strip()
        txt = re.sub(r"^```json\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt).strip()
        try:
            return json.loads(txt)
        except Exception:
            m = re.search(r'\{.*\}', txt, re.DOTALL)
            if m:
                try:
                    dados = json.loads(m.group())
                    return dados
                except Exception:
                    pass
            questoes = _recuperar_questoes_parciais(txt)
            return {"dados_prova": {"nome": "", "banca": "", "id_orgao": None, "data_da_prova": ""}, "questoes": questoes}
    except Exception as e:
        raise ValueError(f"Erro ao processar PDF como imagem: {e}")


def _dividir_texto_por_questoes(texto: str, total: int, lote: int) -> dict:
    """
    Divide o texto em blocos por questão para enviar apenas
    o trecho relevante a cada lote.
    Retorna dict: {numero_questao: trecho_texto}
    """
    blocos = {}

    # Padrões de início de questão
    padrao = re.compile(
        r'(QUEST[ÃA]O\s+\d+|^\s*\d{1,3}\s*[–\-\.]\s)',
        re.MULTILINE | re.IGNORECASE
    )

    # Encontra todas as posições de início de questão
    matches = list(padrao.finditer(texto))

    if not matches:
        # Não achou padrão — retorna texto inteiro como bloco único
        blocos[1] = texto
        return blocos

    for i, m in enumerate(matches):
        # Extrai número da questão
        nums = re.findall(r'\d+', m.group())
        if not nums:
            continue
        num = int(nums[0])
        if num > total:
            continue

        inicio_pos = m.start()
        fim_pos = matches[i+1].start() if i+1 < len(matches) else len(texto)
        blocos[num] = texto[inicio_pos:fim_pos]

    return blocos
    """Recupera questões de um JSON truncado."""
    questoes = []
    arr_match = re.search(r'"questoes"\s*:\s*\[(.+)', txt, re.DOTALL)
    if arr_match:
        arr_txt = arr_match.group(1)
        depth = 0; start = None
        for i, ch in enumerate(arr_txt):
            if ch == '{':
                if depth == 0: start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    try: questoes.append(json.loads(arr_txt[start:i+1]))
                    except Exception: pass
                    start = None
    return questoes


# ── SALVAR NO BANCO (fiel ao gerenciador PHP) ─────────────────────────────────

def salvar_prova_completa(id_usuario: int, dados_prova: dict, questoes: list) -> dict:
    """
    Salva questões no banco vinculando à prova selecionada.
    Se id_prova_existente for fornecido, usa a prova já cadastrada no gerenciador
    e copia os assuntos dela para cada questão.
    """
    conn = get_connection()
    inseridas = 0
    erros = 0

    try:
        id_prova_existente = dados_prova.get("id_prova_existente")

        if id_prova_existente:
            # Usa prova já cadastrada no gerenciador
            id_prova = int(id_prova_existente)
            print(f"Usando prova existente id={id_prova}")

            # Busca assuntos vinculados à prova para replicar nas questões
            ids_assunto = _buscar_assuntos_prova(conn, id_prova)
            print(f"Assuntos da prova: {ids_assunto}")

            # Gera nome da questão a partir dos assuntos da prova
            nome_base = _gerar_nome_por_assuntos(conn, ids_assunto)
            print(f"Nome base das questões: {nome_base!r}")
        else:
            # Cria nova prova (fluxo antigo)
            id_prova = _inserir_prova(conn, id_usuario, dados_prova)
            ids_assunto = []
            nome_base = None

        # Insere cada questão
        for i, q in enumerate(questoes):
            try:
                id_pergunta = _inserir_pergunta_passo1(conn, id_usuario)
                _inserir_pergunta_passo2(conn, id_pergunta, q, nome_base)
                _inserir_respostas(conn, id_pergunta, q.get("alternativas", []))
                _marcar_correta(conn, id_pergunta, q.get("alternativas", []))
                anulada = q.get("anulada", False)
                _vincular_prova_pergunta(conn, id_prova, id_pergunta, id_usuario, i + 1, anulada)

                # Replica assuntos da prova para a questão
                if ids_assunto:
                    _vincular_assuntos_pergunta(conn, id_pergunta, id_usuario, ids_assunto)

                inseridas += 1

            except Exception as e:
                erros += 1
                import traceback
                print(f"Erro questão {q.get('numero', i+1)}: {traceback.format_exc()}")
                conn.rollback()

        conn.commit()

        return {
            "sucesso": True,
            "id_prova": id_prova,
            "questoes_inseridas": inseridas,
            "questoes_com_erro": erros,
            "total": len(questoes)
        }

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def _buscar_assuntos_prova(conn, id_prova: int) -> list:
    """Busca os ids de assuntos vinculados a uma prova."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id_assunto FROM vinculo_assunto_prova
            WHERE id_prova = %s
        """, (id_prova,))
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()


def _gerar_nome_por_assuntos(conn, ids_assunto: list) -> str:
    """
    Gera o nome da questão a partir dos assuntos vinculados.
    Igual ao alterar_pergunta.php: pega folhas na ordem de posicao_gerar_nome das raízes.
    Raízes com posicao_gerar_nome = 0 não entram no nome.
    Raízes conhecidas que entram no nome: Matéria e Assunto(1), Banca(2), Órgão(3), Ano(4)
    """
    if not ids_assunto:
        return ""
    cursor = conn.cursor(dictionary=True)
    try:
        # Busca as raízes ordenadas por posicao_gerar_nome (só as que != 0)
        cursor.execute("""
            SELECT id FROM assunto
            WHERE id_assunto IS NULL AND posicao_gerar_nome != 0
            ORDER BY posicao_gerar_nome ASC
        """)
        raizes = [row["id"] for row in cursor.fetchall()]

        # Busca nomes das folhas selecionadas
        fmt = ','.join(['%s'] * len(ids_assunto))
        cursor.execute(f"""
            SELECT a.id, a.nome, a.id_assunto
            FROM assunto a
            WHERE a.id IN ({fmt})
        """, ids_assunto)
        folhas = {row["id"]: row for row in cursor.fetchall()}

        # Para cada folha, descobre qual raiz pertence
        def achar_raiz(id_assunto):
            cursor2 = conn.cursor(dictionary=True)
            try:
                visited = set()
                atual = id_assunto
                while atual:
                    if atual in visited:
                        break
                    visited.add(atual)
                    cursor2.execute("SELECT id, id_assunto FROM assunto WHERE id = %s", (atual,))
                    row = cursor2.fetchone()
                    if not row or row["id_assunto"] is None:
                        return atual
                    atual = row["id_assunto"]
                return atual
            finally:
                cursor2.close()

        # Mapa raiz_id → nome da folha
        raiz_para_folha = {}
        for id_folha, folha in folhas.items():
            raiz_id = achar_raiz(id_folha)
            raiz_para_folha[raiz_id] = folha["nome"]

        # Monta nome na ordem das raízes
        partes = []
        for raiz_id in raizes:
            if raiz_id in raiz_para_folha:
                partes.append(raiz_para_folha[raiz_id])

        return " | ".join(partes)
    finally:
        cursor.close()


def _vincular_assuntos_pergunta(conn, id_pergunta: int, id_usuario: int, ids_assunto: list):
    """
    Vincula assuntos à pergunta — igual ao alterar_pergunta.php:
    DELETE os existentes, depois INSERT um por um.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM vinculo_assunto_pergunta WHERE id_pergunta = %s", (id_pergunta,))
        for id_assunto in ids_assunto:
            cursor.execute("""
                INSERT INTO vinculo_assunto_pergunta (id_assunto, id_pergunta, id_usuario)
                VALUES (%s, %s, %s)
            """, (id_assunto, id_pergunta, id_usuario))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Erro vincular assuntos: {e}")
    finally:
        cursor.close()


def _inserir_prova(conn, id_usuario: int, dados: dict) -> int:
    cursor = conn.cursor()
    try:
        nome       = encode_latin1(dados.get("nome", "") or "")
        banca      = encode_latin1(dados.get("banca", "") or "")
        data_prova = dados.get("data_da_prova") or None
        # data_da_prova precisa ser NULL ou formato YYYY-MM-DD
        if data_prova and len(data_prova) < 8:
            data_prova = None
        id_orgao   = dados.get("id_orgao") or None
        url        = gerar_url(nome)

        print(f"INSERT prova: nome={nome!r} banca={banca!r} data={data_prova!r} id_orgao={id_orgao!r} id_usuario={id_usuario!r}")

        cursor.execute("""
            INSERT INTO prova (nome, url, banca, data_da_prova, id_orgao, id_usuario)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (nome, url, banca, data_prova, id_orgao, id_usuario))

        conn.commit()
        id_inserido = cursor.lastrowid
        print(f"Prova inserida id={id_inserido}")
        return id_inserido
    except Exception as e:
        import traceback
        print("ERRO _inserir_prova:", traceback.format_exc())
        raise
    finally:
        cursor.close()


def _inserir_pergunta_passo1(conn, id_usuario: int) -> int:
    """
    PASSO 1 — INSERT mínimo, igual ao cadastrar_pergunta_com_assunto.php:
        INSERT INTO pergunta (nome, id_usuario) VALUES (date(), id_usuario)
    """
    from datetime import datetime
    cursor = conn.cursor()
    try:
        nome = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        cursor.execute("""
            INSERT INTO pergunta (nome, id_usuario)
            VALUES (%s, %s)
        """, (nome, id_usuario))
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()


def _inserir_pergunta_passo2(conn, id_pergunta: int, questao: dict, nome_base: str = None):
    """
    PASSO 2 — UPDATE com dados reais, igual ao alterar_pergunta.php.
    Questões anuladas: gabarito = "ANULADA", finalizada = 0
    """
    cursor = conn.cursor()
    try:
        pergunta_txt = encode_latin1(questao.get("pergunta", ""))
        enunciado    = encode_latin1(questao.get("enunciado", "") or "")
        anulada      = questao.get("anulada", False)

        # Gabarito: ANULADA se anulada, senão letra normal
        if anulada:
            gabarito = "ANULADA"
        else:
            gabarito = encode_latin1(questao.get("gabarito", "") or "")

        # finalizada: 0 se anulada, 1 se normal
        finalizada = 0 if anulada else 1

        # Nome da questão
        if nome_base:
            nome = encode_latin1(nome_base[:255])
        else:
            disciplina = encode_latin1(questao.get("disciplina", "") or "")
            nome = encode_latin1(disciplina[:255]) if disciplina else encode_latin1(pergunta_txt[:255])

        url = gerar_url(pergunta_txt)

        cursor.execute("""
            UPDATE pergunta SET
                url        = %s,
                finalizada = %s,
                destaque   = 0,
                pergunta   = %s,
                enunciado  = %s,
                gabarito   = %s,
                nome       = %s
            WHERE id = %s
        """, (url, finalizada, pergunta_txt, enunciado, gabarito, nome, id_pergunta))

        conn.commit()
    finally:
        cursor.close()


def _inserir_respostas(conn, id_pergunta: int, alternativas: list):
    """
    Insere respostas igual ao cadastrar_pergunta_com_assunto.php.
    quantidade_resposta == 2 → "Certo" / "Errado"
    caso contrário → texto da alternativa com posição
    """
    cursor = conn.cursor()
    try:
        qtd = len(alternativas) if alternativas else 5
        is_certo_errado = qtd == 2

        if not alternativas:
            # fallback: 5 respostas vazias com posição numérica
            for i in range(1, 6):
                cursor.execute("""
                    INSERT INTO resposta (id_pergunta, nome, posicao, correta)
                    VALUES (%s, %s, %s, 0)
                """, (id_pergunta, str(i), i))
        else:
            for i, alt in enumerate(alternativas, start=1):
                if is_certo_errado:
                    nome = "Certo" if i == 1 else "Errado"
                else:
                    nome = encode_latin1(alt.get("texto", "") or str(i))

                cursor.execute("""
                    INSERT INTO resposta (id_pergunta, nome, posicao, correta)
                    VALUES (%s, %s, %s, 0)
                """, (id_pergunta, nome, i))

        conn.commit()
    finally:
        cursor.close()


def _marcar_correta(conn, id_pergunta: int, alternativas: list):
    """
    Marca a resposta correta, igual ao alterar_pergunta.php:
    1. UPDATE resposta SET correta = 0 WHERE id_pergunta = X  (todas erradas)
    2. UPDATE resposta SET correta = 1 WHERE id = Y           (só a certa)
    """
    cursor = conn.cursor(dictionary=True)
    try:
        # Zera todas
        cursor.execute("""
            UPDATE resposta SET correta = 0 WHERE id_pergunta = %s
        """, (id_pergunta,))

        # Acha qual é a correta
        correta_idx = None
        for i, alt in enumerate(alternativas, start=1):
            if alt.get("correta"):
                correta_idx = i
                break

        if correta_idx is not None:
            # Busca o id da resposta pela posição
            cursor.execute("""
                SELECT id FROM resposta
                WHERE id_pergunta = %s AND posicao = %s
                LIMIT 1
            """, (id_pergunta, correta_idx))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE resposta SET correta = 1 WHERE id = %s
                """, (row["id"],))

        conn.commit()
    finally:
        cursor.close()


def _vincular_prova_pergunta(conn, id_prova: int, id_pergunta: int, id_usuario: int, posicao: int, anulada: bool = False):
    """
    Vincula pergunta à prova.
    status: 0 = Válida, 1 = Anulada, 2 = Desatualizada
    """
    cursor = conn.cursor()
    try:
        status = 1 if anulada else 0
        cursor.execute("""
            INSERT INTO vinculo_prova_pergunta
                (id_prova, id_pergunta, id_usuario, posicao, id_topico, status)
            VALUES
                (%s, %s, %s, %s, 0, %s)
        """, (id_prova, id_pergunta, id_usuario, posicao, status))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Aviso vinculo_prova_pergunta: {e}")
    finally:
        cursor.close()
