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
- Retorne JSON puro sem nenhum texto antes ou depois"""


def processar_pdfs(conteudo_prova: bytes, conteudo_gabarito: Optional[bytes] = None) -> dict:
    """
    Usa Claude para extrair questões e dados da prova a partir dos PDFs.
    Retorna dict com dados_prova e lista de questoes para o preview.
    """
    client = get_claude()

    content = []

    content.append({
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(conteudo_prova).decode("utf-8")
        },
        "title": "Caderno de Questões"
    })

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

    content.append({
        "type": "text",
        "text": PROMPT_EXTRACAO_PDF
    })

    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": content}]
    )

    txt = msg.content[0].text.strip()
    txt = re.sub(r"^```json\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    txt = txt.strip()

    m = re.search(r'\{.*\}', txt, re.DOTALL)
    if not m:
        raise ValueError("Claude não retornou JSON válido.")

    dados = json.loads(m.group())

    if "dados_prova" not in dados or "questoes" not in dados:
        raise ValueError("Estrutura JSON incompleta retornada pelo Claude.")

    return dados


# ── SALVAR NO BANCO (fiel ao gerenciador PHP) ─────────────────────────────────

def salvar_prova_completa(id_usuario: int, dados_prova: dict, questoes: list) -> dict:
    """
    Salva a prova e todas as questões no banco.
    Segue exatamente a mesma lógica do gerenciador PHP.
    """
    conn = get_connection()
    inseridas = 0
    erros = 0

    try:
        # 1. Inserir a prova
        id_prova = _inserir_prova(conn, id_usuario, dados_prova)

        # 2. Inserir cada questão
        for i, q in enumerate(questoes):
            try:
                # PASSO 1: INSERT mínimo (igual ao cadastrar_pergunta_com_assunto.php)
                id_pergunta = _inserir_pergunta_passo1(conn, id_usuario)

                # PASSO 2: UPDATE com dados reais (igual ao alterar_pergunta.php)
                _inserir_pergunta_passo2(conn, id_pergunta, q)

                # PASSO 3: INSERT respostas (igual ao cadastrar_pergunta_com_assunto.php)
                _inserir_respostas(conn, id_pergunta, q.get("alternativas", []))

                # PASSO 4: Marcar resposta correta (igual ao alterar_pergunta.php)
                _marcar_correta(conn, id_pergunta, q.get("alternativas", []))

                # PASSO 5: Vincular à prova com posição (igual ao cadastrar_multipla_pergunta_prova.php)
                _vincular_prova_pergunta(conn, id_prova, id_pergunta, id_usuario, i + 1)

                inseridas += 1

            except Exception as e:
                erros += 1
                print(f"Erro ao inserir questão {q.get('numero', i+1)}: {e}")
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


def _inserir_prova(conn, id_usuario: int, dados: dict) -> int:
    """
    Insere a prova. A tabela prova usa: id_orgao, nome, url, banca, banca_link,
    data_da_prova, finalizada, corrigida, etc.
    Campos não obrigatórios ficam com valor padrão do banco.
    """
    cursor = conn.cursor()
    try:
        nome        = encode_latin1(dados.get("nome", ""))
        banca       = encode_latin1(dados.get("banca", ""))
        data_prova  = dados.get("data_da_prova", "") or None
        id_orgao    = dados.get("id_orgao") or None
        url         = gerar_url(nome)

        cursor.execute("""
            INSERT INTO prova (nome, url, banca, data_da_prova, id_orgao, id_usuario)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (nome, url, banca, data_prova, id_orgao, id_usuario))

        conn.commit()
        return conn.insert_id()
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
        return conn.insert_id()
    finally:
        cursor.close()


def _inserir_pergunta_passo2(conn, id_pergunta: int, questao: dict):
    """
    PASSO 2 — UPDATE com dados reais, igual ao alterar_pergunta.php:
        UPDATE pergunta SET url, finalizada, destaque, pergunta, enunciado, gabarito
    O campo 'nome' é gerado a partir dos assuntos no gerenciador.
    Aqui usamos a disciplina como nome (será atualizado quando assuntos forem vinculados).
    """
    cursor = conn.cursor()
    try:
        pergunta_txt = encode_latin1(questao.get("pergunta", ""))
        enunciado    = encode_latin1(questao.get("enunciado", "") or "")
        gabarito     = encode_latin1(questao.get("gabarito", "") or "")
        disciplina   = encode_latin1(questao.get("disciplina", "") or "")
        nome         = encode_latin1(disciplina[:255]) if disciplina else encode_latin1(pergunta_txt[:255])
        url          = gerar_url(pergunta_txt)

        cursor.execute("""
            UPDATE pergunta SET
                url        = %s,
                finalizada = 1,
                destaque   = 0,
                pergunta   = %s,
                enunciado  = %s,
                gabarito   = %s,
                nome       = %s
            WHERE id = %s
        """, (url, pergunta_txt, enunciado, gabarito, nome, id_pergunta))

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


def _vincular_prova_pergunta(conn, id_prova: int, id_pergunta: int, id_usuario: int, posicao: int):
    """
    Vincula pergunta à prova com posição.
    Igual ao cadastrar_multipla_pergunta_prova.php e cadastrar_pergunta_com_assunto.php:
        INSERT INTO vinculo_prova_pergunta (id_prova, id_pergunta, id_usuario, posicao, id_topico)
    """
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO vinculo_prova_pergunta
                (id_prova, id_pergunta, id_usuario, posicao, id_topico)
            VALUES
                (%s, %s, %s, %s, 0)
        """, (id_prova, id_pergunta, id_usuario, posicao))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Aviso vinculo_prova_pergunta: {e}")
    finally:
        cursor.close()
