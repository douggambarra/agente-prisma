# Prisma Concursos — Agente IA

Backend Python/FastAPI + frontend SPA (vanilla JS) para automatizar busca e inserção de questões de concurso no banco MySQL da Prisma Concursos.

---

## Stack

- **Backend:** Python + FastAPI, rodando no Railway
- **Banco:** MySQL na Locaweb — charset `latin1` / `latin1_general_ci`
- **IA:** Anthropic SDK (Claude) — haiku para tarefas leves, sonnet/opus para extração de PDF
- **Busca web:** SerpApi (Google Search)
- **Frontend:** único arquivo `frontend/index.html` (SPA vanilla JS, dark theme)

---

## Estrutura de arquivos

```
app/
  main.py                    # FastAPI app, CORS, routers
  database.py                # Conexão MySQL (latin1)
  routers/
    auth.py                  # Login (MD5+SHA1) + listar usuários
    agente.py                # Busca temática na web + métricas + assuntos
    auditoria.py             # Verificar gabaritos, duplicatas, encoding
    upload_prova.py          # Upload PDF + preview + confirmação
  services/
    buscador.py              # SerpApi + extração Claude + inserção no banco
    processador_pdf.py       # Extração de questões de PDF via Claude
    validador.py             # Validação de questões com Claude (heurística fallback)
frontend/
  index.html                 # SPA completa — única fonte do frontend
requirements.txt
Procfile                     # Railway: web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
railway.toml
.env.example
```

---

## Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `DB_HOST` | prismaconcurso.mysql.dbaas.com.br |
| `DB_PORT` | 3306 |
| `DB_USER` | prismaconcurso |
| `DB_PASSWORD` | senha do banco |
| `DB_NAME` | prismaconcurso |
| `ANTHROPIC_API_KEY` | chave da API do Claude |
| `SERP_API_KEY` | chave do SerpApi (Google Search) |

---

## Rodar local

```bash
pip install -r requirements.txt
cp .env.example .env        # preencher ANTHROPIC_API_KEY e DB_PASSWORD
uvicorn app.main:app --reload
# abrir frontend/index.html no browser
```

O `index.html` detecta automaticamente o ambiente:
- `localhost` / `127.0.0.1` → `http://localhost:8000`
- qualquer outro host → `https://web-production-cc8e1.up.railway.app`

Deploy: apenas fazer push para o GitHub — Railway detecta e deploya automaticamente.

---

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| GET | `/status` | Verifica API e conexão com banco |
| POST | `/auth/login` | Login (retorna id_usuario) |
| GET | `/auth/usuarios` | Lista usuários |
| GET | `/agente/metricas` | Total questões, hoje, histórico 7 dias |
| GET | `/agente/assuntos` | Árvore de assuntos do banco |
| GET | `/agente/questoes-inseridas` | Questões inseridas pelo agente |
| POST | `/agente/buscar` | Inicia busca temática (background job) |
| GET | `/agente/job/{id}` | Status de um job de busca |
| GET | `/auditoria/resumo` | Saúde geral da base |
| GET | `/auditoria/verificar-gabaritos` | Questões sem/múltiplos gabaritos |
| GET | `/auditoria/verificar-duplicatas` | Pares duplicados |
| GET | `/auditoria/verificar-encoding` | Caracteres corrompidos |
| GET | `/upload-prova/provas` | Lista provas cadastradas |
| POST | `/upload-prova/processar` | Fase 1: análise rápida (conta questões, dados da prova) |
| GET | `/upload-prova/job/{id}` | Status do processamento |
| POST | `/upload-prova/iniciar/{id}` | Fase 2: inicia extração completa após confirmação |
| POST | `/upload-prova/confirmar` | Salva questões revisadas no banco |

---

## Fluxo: Upload de Prova (2 fases)

**Fase 1 — Análise rápida** (`POST /upload-prova/processar`)
1. Extrai texto do PDF, conta questões, identifica nome/banca/data da prova (1-2 chamadas Claude)
2. Job fica em `aguardando_inicio` com `preview: {total_questoes, dados_prova}`
3. Frontend exibe tela de confirmação: **"X questões encontradas — [nome da prova]"**
4. Usuário confirma se o número está correto antes de gastar tokens na extração completa

**Fase 2 — Extração completa** (`POST /upload-prova/iniciar/{job_id}`)
1. `processador_pdf.py` escolhe estratégia:
   - **1 coluna** → processa por texto em lotes de 15 questões (barato, rápido)
   - **2 ou 3 colunas** → divide PDF em grupos de páginas e envia ao Claude (mais preciso)
2. Claude extrai todas as questões (enunciado, pergunta, alternativas, gabarito, disciplina, anuladas)
3. Job fica em `aguardando_confirmacao` — frontend exibe preview editável
4. Usuário revisa → `POST /upload-prova/confirmar` → `salvar_prova_completa()`

**Opção de prova existente:** se `id_prova_existente` for passado, vincula as questões à prova já cadastrada no gerenciador PHP e replica os assuntos dela.

**Views do frontend (upload):** `pdf-view-upload` → `pdf-view-loading` → `pdf-view-confirmacao` → `pdf-view-loading` → `pdf-view-preview` → `pdf-view-success`

---

## Fluxo: Busca Temática na Web

1. Usuário digita comando livre, ex: "questões de direito penal CESPE 2023"
2. Claude Haiku interpreta e gera 3 queries otimizadas para busca
3. SerpApi busca no Google; para cada resultado: tenta baixar a página completa, usa snippet como fallback
4. Claude Haiku extrai questões do texto de cada página
5. Filtra textos curtos e questões sem alternativas
6. Verifica duplicatas (por trecho de 100 chars) antes de inserir
7. Claude Haiku classifica automaticamente os assuntos de cada questão pela hierarquia do banco
8. Insere no banco seguindo o fluxo do gerenciador PHP

---

## Regra crítica de inserção no banco

Segue **exatamente** o fluxo do gerenciador PHP (`cadastrar_pergunta_com_assunto.php` + `alterar_pergunta.php`):

1. `INSERT INTO pergunta (nome=timestamp, id_usuario)` — INSERT mínimo
2. `UPDATE pergunta SET url, finalizada, pergunta, enunciado, gabarito, nome WHERE id=X`
3. `INSERT INTO resposta` — todas com `correta=0`
4. `UPDATE resposta SET correta=1 WHERE id=Y` — só a correta
5. `INSERT INTO vinculo_assunto_pergunta` — um por assunto
6. `INSERT INTO vinculo_prova_pergunta (id_prova, id_pergunta, id_usuario, posicao, id_topico=0, status)`

**Encoding:** banco é latin1. Todo texto passa por `encode_latin1()` antes de inserir. Símbolos matemáticos/gregos sem equivalente latin1 são substituídos por versões ASCII legíveis.

---

## Tabelas principais do banco

| Tabela | Descrição |
|---|---|
| `pergunta` | Questões (pergunta, enunciado, gabarito, finalizada, nome, url) |
| `resposta` | Alternativas (nome, posicao, correta, id_pergunta) |
| `assunto` | Árvore hierárquica de assuntos (id_assunto=pai, posicao_gerar_nome) |
| `vinculo_assunto_pergunta` | Relaciona questão ↔ assuntos |
| `prova` | Provas cadastradas (nome, banca, data_da_prova, id_orgao) |
| `vinculo_prova_pergunta` | Relaciona questão ↔ prova (posicao, status: 0=válida, 1=anulada) |
| `vinculo_assunto_prova` | Relaciona prova ↔ assuntos |
| `usuario` | Usuários do sistema |

---

## Modelos Claude utilizados

| Uso | Modelo |
|---|---|
| Interpretar comando de busca | `claude-haiku-4-5-20251001` |
| Extrair questões de página web | `claude-haiku-4-5-20251001` |
| Classificar assuntos automaticamente | `claude-haiku-4-5-20251001` |
| Validar questão | `claude-haiku-4-5-20251001` |
| Extrair questões de PDF (padrão) | `claude-sonnet-4-6` |
| Extrair questões de PDF (premium) | `claude-opus-4-6` |

---

## Bugs críticos já corrigidos

- **LOTE 50→15 em `_processar_por_texto`:** 50 questões × ~300 tokens = ~15k tokens de saída, mas `max_tokens=8192` cortava na questão ~25, corrompendo o JSON. Com LOTE=15 o output fica em ~4.5k tokens.
- **Regex com bytes UTF-8 em vez de Unicode (`_contar_questoes_texto` e `_dividir_texto_por_questoes`):** `\xc3\x83`, `\xc3\xa3`, `\xe2\x80\x93` eram interpretados como chars individuais errados em Python 3. Corrigido para `Ã`, `ã`, `–`.
- **NameError em `_chamar_claude_pdf`:** variáveis `inicio`/`fim` referenciadas no catch sem existir nesse escopo.
- **Deduplicação por número de questão** adicionada ao final de `_processar_por_texto` e `_processar_por_paginas`.

## Observações importantes

- O frontend é um único arquivo HTML — ao alterar, basta subir via FTP para produção
- Questões inseridas pelo agente têm `id_personalizado` numérico (gerado automaticamente)
- Questões anuladas: `gabarito="ANULADA"`, `finalizada=0`, `status=1` no vínculo com a prova
- O campo `posicao_gerar_nome` na tabela `assunto` define a ordem no nome gerado (0 = não entra no nome)
- O nome da questão é gerado pela concatenação dos assuntos-folha ordenados por `posicao_gerar_nome` das raízes: Matéria (1), Banca (2), Órgão (3), Ano (4)
