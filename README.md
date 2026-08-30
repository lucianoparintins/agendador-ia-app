# Agendador IA — REST + Ollama Local + SQLite

Serviço REST em FastAPI para agendamento de serviços (barbearia/salão), usando o modelo `gemma2:2b` do Ollama local e persistência em SQLite.

> **Estado atual:** validado ponta a ponta, incluindo regras de agenda (expediente, duração de 1h e conflito) — ver seção [Estado atual](#estado-atual).

## Pré-requisitos

- Python 3.10+
- Servidor [Ollama](https://ollama.com) rodando em `http://localhost:11434` com o modelo `gemma2:2b` baixado (`ollama pull gemma2:2b`)

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Execução

```bash
uvicorn app.main:app --reload
```

Acesse a documentação interativa (Swagger) em http://localhost:8000/docs

## Endpoints

| Método | Rota                          | Descrição                                          |
|--------|-------------------------------|----------------------------------------------------|
| POST   | `/chat`                       | Envia mensagem, retorna resposta + agendamento JSON. Aceita `stream` para tokens ao vivo (SSE) |
| GET    | `/sessoes`                    | Lista sessões                                      |
| GET    | `/sessoes/{id}/mensagens`     | Histórico de mensagens de uma sessão               |
| GET    | `/agendamentos`               | Lista agendamentos persistidos                     |
| GET    | `/health`                     | Verifica disponibilidade do Ollama                 |

## Exemplo (curl)

Criar a primeira troca de mensagem:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"mensagem": "Bom dia, quero agendar um corte de cabelo"}'
```

A resposta inclui `sessao_id`. Continue a conversa informando `sessao_id`:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"sessao_id": 1, "mensagem": "Sou o João, e gostaria de amanhã às 10h"}'
```

### Streaming de tokens (SSE)

Envie `"stream": true` para receber os tokens ao vivo via `text/event-stream`:

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"sessao_id": 1, "stream": true, "mensagem": "Quero agendar um corte amanhã às 10h"}'
```

Eventos emitidos (cada um como `data: <json>`):

- `{"type":"token","content":"..."}` — um pedaço da resposta, ao vivo.
- `{"type":"correcao","reply":"..."}` — opcional, quando o horário é rejeitado e a resposta é reprocessada pelo Ollama pedindo novo horário.
- `{"type":"done","sessao_id":N,"agendamento":{...},"validacao":{...}}` — final.
- Terminador `data: [DONE]`.

## Banco de dados

Arquivo SQLite em `app/agendamento.db` (criado automaticamente na inicialização). Tabelas:

- `sessoes` — sessões de conversa
- `mensagens` — histórico (role user/assistant)
- `agendamentos` — agendamentos extraídos e persistidos, com `status` (`confirmado` / `rascunho` / `rejeitado`)

## Regras da agenda

Validação de agendamento no backend (`app/agenda.py`):

- **Expediente:** segunda a sexta das 09h às 18h, sábado das 09h às 13h, domingo fechado.
- **Duração do serviço:** fixa de **1h** por agendamento.
- **Conflito:** rejeita horário que se sobreponha a um agendamento `confirmado` no mesmo dia.
- **Passado:** rejeita data/hora já ocorridas.

Quando os dados são **insuficientes** (faltando data/hora), o agendamento é salvo como `rascunho`. Quando **inválido** (`data_invalida`, `hora_invalida`, `no_passado`, `fora_expediente`, `conflito`), o registro é salvo com `status=rejeitado`, a resposta é reprocessada pelo Ollama e a `reply` pede um novo horário ao cliente. O campo `validacao` da resposta do `/chat` informa `{valido, motivo}`.

## Estrutura do projeto

```
agendador-ia-app/
├── requirements.txt          # fastapi, uvicorn[standard], httpx, python-dateutil
├── .gitignore                # __pycache__, *.db, .venv
├── spec/
│   ├── 2026-08-30-174308-PLANO.md              # plano do projeto (datado)
│   ├── 2026-08-30-180847-PLANO-VALIDACAO-AGENDA.md  # plano de validação de agenda
│   └── 2026-08-30-183828-PLANO-STREAMING.md    # plano de streaming de tokens
├── app/
│   ├── __init__.py
│   ├── main.py               # App FastAPI, rotas, startup (cria tabelas)
│   ├── db.py                 # sqlite3, conexão, tabelas, CRUD e verificação de conflito
│   ├── agenda.py             # expediente, parsing e validação de data/hora
│   ├── ollama_client.py      # chamada assíncrona a /api/chat + parser JSON + reprocessamento
│   └── schema.py             # Models Pydantic
└── README.md
```

## Estado atual

Situação em **30/08/2026** — terceira iteração (streaming de tokens) implementada:

**Implementado**
- `POST /chat`: recebe mensagem, recupera/cria sessão no SQLite, reconstrói o histórico, consulta o `gemma2:2b` via Ollama local e retorna `{ sessao_id, reply, agendamento?, validacao? }`. Mensagens do usuário e do assistente são persistidas.
- **Streaming de tokens (`stream=True`):** `/chat` passa a aceitar `"stream": true` e retorna `text/event-stream` (SSE) transmitindo os tokens ao vivo. Eventos: `token` (cada pedaço), `correcao` (quando o horário é rejeitado e a reply é reprocessada), `done` (com `agendamento`/`validacao`) e terminador `[DONE]`. Apenas a reply final é persistida no histórico.
- Validação de agendamento no backend (`app/agenda.py`): expediente (seg–sex 9h–18h, sáb 9h–13h, domingo fechado), duração fixa de 1h, rejeição de data passada e de conflito com agendamentos `confirmados`.
- Novos campos: `status` (`confirmado`/`rascunho`/`rejeitado`) no agendamento e `validacao: {valido, motivo}` na resposta do `/chat`.
- Rejeição com reprocessamento: quando o horário é inválido, o Ollama é reconsultado informando o motivo e a `reply` pede um novo horário ao cliente; o registro é salvo como `rejeitado`.
- `GET /health`, `GET /sessoes`, `GET /sessoes/{id}/mensagens`, `GET /agendamentos`.
- Persistência SQLite completa: sessões, histórico de mensagens e agendamentos (banco `app/agendamento.db`).

**Validado ponta a ponta (curl)**
- Agendamento em dia útil dentro do expediente → `status=confirmado` e `validacao.valido=true`.
- Domingo ou horário fora do expediente → `status=rejeitado` e `validacao.motivo=fora_expediente`, com `reply` pedindo novo horário.
- Horário conflitante com um agendamento `confirmado` → `status=rejeitado` e `validacao.motivo=conflito`.
- Mensagem sem data/hora → `status=rascunho`.
- Data no passado → `status=rejeitado` e `validacao.motivo=no_passado`.
- Streaming (`curl -N` com `stream=true`): eventos `token` ao vivo, `done` com `agendamento`/`validacao`, e `correcao` nos casos de rejeição.
- `GET /health` reportou `{"status": "ok", "ollama_reachable": true}`.

**Observações / decisões**
- O histórico completo é reconstruído no servidor a partir do `sessao_id` (fonte da verdade = SQLite).
- No streaming, a validação acontece ao final (depende do texto completo). Quando rejeitado, o texto inicial já transmitido é substituído pela reply reprocessada via evento `correcao`; apenas a reply final é gravada.
- **Correção aplicada durante o build:** o `gemma2:2b` retorna JSON com aspas simples (não compatível com `json.loads` estrito). O parser em `ollama_client.py` tenta `json.loads` e, se falhar, usa `ast.literal_eval` como fallback — normalizando `null`/`true`/`false` do JSON para `None`/`True`/`False`. Isso cobre blocos com campos desconhecidos (`{'data': null}`), comuns nas respostas.
- Parsing de data/hora usa `python-dateutil` (aceita AAAA-MM-DD, DD/MM/AAAA, HH:MM, HHhMM etc.). Atenção: datas ambíguas como `06/09/2026` são interpretadas em formato mês/dia; para evitar surpresa, prefira o formato ISO `AAAA-MM-DD`.
- A validação acontece apenas em `data` + `hora`; cliente/serviço não são validados.

**Próximas evoluções (não implementadas)**
- Disponibilidade injetada no prompt (o modelo já conhece a agenda antes de responder).
- Fluxo de confirmação explícita pelo cliente antes de salvar como `confirmado`.
- Frontend/UI de chat.
