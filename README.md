# Prisma Concursos — Agente IA

Backend em Python/FastAPI para busca, validação e inserção automática de questões no banco MySQL da Prisma Concursos.

## Estrutura

```
prisma-agente/
├── app/
│   ├── main.py              # Entrada da API
│   ├── database.py          # Conexão MySQL
│   ├── routers/
│   │   ├── auth.py          # Login e usuários
│   │   ├── agente.py        # Busca e inserção
│   │   └── auditoria.py     # Verificação da base
│   └── services/
│       ├── buscador.py      # Scraping e inserção
│       └── validador.py     # Validação com IA
├── requirements.txt
├── Procfile                 # Para Railway
├── railway.toml
└── .env.example
```

## Variáveis de ambiente (configurar no Railway)

| Variável | Descrição |
|---|---|
| `DB_HOST` | Host do MySQL da Locaweb |
| `DB_PORT` | Porta (padrão 3306) |
| `DB_USER` | Usuário do banco |
| `DB_PASSWORD` | Senha do banco |
| `DB_NAME` | Nome do banco |
| `ANTHROPIC_API_KEY` | Chave da API do Claude |

## Endpoints principais

| Método | Rota | Descrição |
|---|---|---|
| GET | `/status` | Verifica API e conexão com banco |
| POST | `/auth/login` | Autenticação do usuário |
| GET | `/agente/metricas` | Total de questões, hoje, histórico |
| GET | `/agente/assuntos` | Lista disciplinas/assuntos |
| POST | `/agente/busca-tematica` | Inicia busca por tema |
| GET | `/agente/job/{id}` | Status de uma busca em andamento |
| GET | `/auditoria/resumo` | Saúde geral da base |
| GET | `/auditoria/verificar-gabaritos` | Questões sem gabarito |
| GET | `/auditoria/verificar-duplicatas` | Pares duplicados |
| GET | `/auditoria/verificar-encoding` | Caracteres corrompidos |

## Deploy no Railway

1. Criar conta em railway.app
2. Novo projeto → Deploy from GitHub
3. Adicionar as variáveis de ambiente acima
4. Railway detecta o Procfile automaticamente e faz o deploy

## Testar localmente

```bash
pip install -r requirements.txt
cp .env.example .env
# editar .env com as credenciais reais
uvicorn app.main:app --reload
# abrir http://localhost:8000/status
```
