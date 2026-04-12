import anthropic
import os
import json

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

PROMPT_VALIDACAO = """Você é um validador de questões de concurso público brasileiro.

Analise a questão abaixo e responda APENAS com um JSON no formato:
{{"valida": true/false, "motivo": "explicação breve"}}

Critérios para ser VÁLIDA:
- Ser uma questão real de concurso público (não exercício escolar ou vestibular)
- Ter enunciado compreensível com pelo menos 20 palavras
- Ter pelo menos 2 alternativas identificáveis (A, B, C...)
- Não ser apenas fragmento de texto sem sentido

Critérios para ser INVÁLIDA:
- Texto claramente incompleto ou cortado
- Sem alternativas identificáveis
- Conteúdo adulto ou inapropriado
- Apenas números ou caracteres especiais sem sentido

Questão:
{texto}"""

def validar_questao(questao: dict) -> tuple[bool, str]:
    texto = questao.get("pergunta", "") or questao.get("enunciado", "")
    if not texto or len(texto.strip()) < 30:
        return False, "texto muito curto"
    try:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return validar_heuristico(questao)

        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": PROMPT_VALIDACAO.format(texto=texto[:2000])
            }]
        )
        resposta = msg.content[0].text.strip()
        resposta = resposta.replace("```json", "").replace("```", "").strip()
        dados = json.loads(resposta)
        return dados.get("valida", False), dados.get("motivo", "")
    except Exception as e:
        return validar_heuristico(questao)

def validar_heuristico(questao: dict) -> tuple[bool, str]:
    texto = questao.get("pergunta", "") + questao.get("enunciado", "")
    if len(texto) < 50:
        return False, "texto muito curto"
    letras = sum(c.isalpha() for c in texto)
    if letras < len(texto) * 0.4:
        return False, "texto sem conteúdo suficiente"
    tem_alternativa = any(f"{l})" in texto or f"{l} )" in texto
                          for l in ["A", "B", "C", "a", "b", "c"])
    if not tem_alternativa:
        return False, "sem alternativas identificáveis"
    return True, "válida (heurística)"
