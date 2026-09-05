# Agendador IA — REST + Ollama Local + SQLite

Serviço REST em FastAPI para agendamento de serviços (barbearia/salão), usando o modelo `gemma2:2b` do Ollama local e persistência em SQLite.

> **Estado atual:** validado ponta a ponta, incluindo regras de agenda (expediente, duração de 1h e conflito), tratamento de datas relativas, consolidação de agendamento por sessão, cadastro de clientes por telefone e reinício automático da sessão após confirmação — ver seção [Estado atual](#estado-atual).

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
| GET    | `/clientes`                   | Lista todos os clientes                            |
| GET    | `/clientes/{id}`              | Obtém um cliente por ID                            |
| POST   | `/clientes`                   | Cria um novo cliente (`{nome, telefone}`)          |
| PUT    | `/clientes/{id}`              | Atualiza nome/telefone de um cliente               |
| DELETE | `/clientes/{id}`              | Remove um cliente                                  |
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
- `clientes` — cadastro de clientes, com `telefone` **único** (formato `(NN) NNNN-NNNN`)
- `agendamentos` — agendamentos extraídos e persistidos, com `status` (`confirmado` / `rascunho` / `rejeitado`) e vínculo (`cliente_id`) ao cadastro do cliente

## Regras da agenda

Validação de agendamento no backend (`app/agenda.py`):

- **Expediente:** segunda a sexta das 09h às 18h, sábado das 09h às 13h, domingo fechado.
- **Duração do serviço:** fixa de **1h** por agendamento.
- **Conflito:** rejeita horário que se sobreponha a um agendamento `confirmado` no mesmo dia.
- **Passado:** rejeita data/hora já ocorridas.
- **Datas relativas:** o backend reconhece e resolve `hoje`, `amanhã`, `depois de amanhã`, `ontem` e `próxima <dia da semana>` para a data concreta (`DD/MM/YYYY`), usando a data atual do servidor.
- **Datas improváveis:** datas no passado ou muito distantes no futuro (fora de uma janela de 90 dias) são tratadas como dado **insuficiente** (não são rejeitadas como erro do cliente), pedindo que a data seja confirmada novamente.

Quando os dados são **insuficientes** (faltando data/hora ou data improvável), o agendamento é salvo como `rascunho`. Quando **inválido** (`data_invalida`, `hora_invalida`, `no_passado`, `fora_expediente`, `conflito`), o registro é salvo com `status=rejeitado`, a resposta é reprocessada pelo Ollama e a `reply` pede um novo horário ao cliente. O campo `validacao` da resposta do `/chat` informa `{valido, motivo}`.

### Consolidação de agendamento por sessão

Cada `sessao_id` mantém **no máximo um agendamento ativo** (`rascunho`). A cada mensagem, os dados extraídos são **mesclados** nesse rascunho (campos novos não-nulos sobrescrevem os existentes), permitindo que o cliente informe nome, serviço, data e horário em mensagens separadas sem gerar registros duplicados:

- **Confirmado** → o rascunho evolui para `status=confirmado` (um único registro por intenção).
- **Rejeitado** → grava um registro `rejeitado` no histórico e abre um novo rascunho (herdando `cliente` e `servico`) para o cliente corrigir apenas data/horário.
- **Insuficiente** → mantém/atualiza o rascunho ativo.

## Data e hora atuais para o modelo

O `system prompt` injeta a **data e hora atuais do servidor** (formato `DD/MM/YYYY HH:MM`) a cada chamada, para que o modelo não assuma ano/dia errado ao interpretar pedidos relativos. O prompt também orienta o modelo a calcular datas relativas a partir dessa base, nunca usar anos passados e, se não tiver certeza, deixar o campo `data` como `null` para o backend calcular.

## Estrutura do projeto

```
agendador-ia-app/
├── requirements.txt          # fastapi, uvicorn[standard], httpx, python-dateutil
├── .gitignore                # __pycache__, *.db, .venv
├── README.md
├── CHANGELOG.md              # histórico de alterações do projeto
├── AGENTS.md                 # guia para agentes de IA e pair programming
├── GEMINI.md                 # visão geral, stack e convenções de desenvolvimento
├── spec/
│   ├── 2026-08-30-174308-PLANO.md              # plano do projeto (datado)
│   ├── 2026-08-30-180847-PLANO-VALIDACAO-AGENDA.md  # plano de validação de agenda
│   ├── 2026-08-30-183828-PLANO-STREAMING.md    # plano de streaming de tokens
│   ├── 2026-08-30-214212-PLANO-CLIENT-HTML.md  # plano da interface HTML de chat
│   └── 2026-08-31-165000-PLANO-CLIENTE-TELEFONE.md  # plano de cadastro de clientes
├── app/
│   ├── __init__.py
│   ├── main.py               # App FastAPI, rotas, startup (cria tabelas)
│   ├── db.py                 # sqlite3, conexão, tabelas, CRUD, merge por sessão e verificação de conflito
│   ├── agenda.py             # expediente, parsing/validação de data/hora, datas relativas e plausibilidade
│   ├── ollama_client.py      # chamada assíncrona a /api/chat + parser JSON + data atual no prompt
│   └── schema.py             # Models Pydantic
├── client/
│   └── index.html            # interface web estática para teste do chat (SSE)
├── scripts/
│   └── reset_db.py           # zera o banco sqlite (apaga todos os dados)
```

## Estado atual

Situação em **04/09/2026** — iterações de datas relativas, consolidação por sessão, interface HTML, cadastro de clientes e reinício automático da sessão implementadas:

**Implementado**
- `POST /chat`: recebe mensagem, recupera/cria sessão no SQLite, reconstrói o histórico, consulta o `gemma2:2b` via Ollama local e retorna `{ sessao_id, reply, agendamento?, validacao? }`. Mensagens do usuário e do assistente são persistidas.
- **Streaming de tokens (`stream=True`):** `/chat` aceita `"stream": true` e retorna `text/event-stream` (SSE) transmitindo os tokens ao vivo. Eventos: `token`, `correcao` (rejeição reprocessada), `done` (com `agendamento`/`validacao`) e terminador `[DONE]`. Apenas a reply final é persistida.
- Validação de agendamento no backend (`app/agenda.py`): expediente (seg–sex 9h–18h, sáb 9h–13h, domingo fechado), duração fixa de 1h, rejeição de data passada e de conflito com agendamentos `confirmados`.
- **Datas relativas:** `resolver_data_relativa()` converte `hoje`, `amanhã`, `depois de amanhã`, `ontem` e `próxima <dia>` em data concreta; **plausibilidade** (`data_plausivel()`) trata datas passadas/muito distantes como dado insuficiente em vez de erro do cliente.
- **Data/hora atuais no prompt:** o system prompt injeta a data/hora do servidor a cada chamada, para o modelo não assumir ano/dia errado; o prompt orienta a não inventar datas e a deixar `data: null` quando inseguro.
- **Consolidação por sessão:** no máximo 1 agendamento ativo (`rascunho`) por `sessao_id`, com merge progressivo dos dados entre mensagens; confirmado evolui o rascunho; rejeitado grava histórico e abre novo rascunho (herdando cliente/serviço).
- Novos campos: `status` (`confirmado`/`rascunho`/`rejeitado`) no agendamento e `validacao: {valido, motivo}` na resposta do `/chat`.
- Rejeição com reprocessamento: quando o horário é inválido, o Ollama é reconsultado informando o motivo e a `reply` pede um novo horário; o registro é salvo como `rejeitado`.
- **Datas em DD/MM/YYYY:** datas capturadas são normalizadas e persistidas no formato dia/mês/ano (inclusive em ISO `AAAA-MM-DD`), evitando inversão de dia/mês.
- `GET /health`, `GET /sessoes`, `GET /sessoes/{id}/mensagens`, `GET /agendamentos`.
- **Frontend/UI de chat:** diretório `client/` com `index.html` simples (sem build) que conversa com o `/chat` via SSE. Suba a API (`uvicorn app.main:app --reload`) e sirva o client (`python -m http.server 8080 -d client`), abrindo `http://localhost:8080`.
- **Finalização de sessão e reinício automático:** após um agendamento `confirmado`, o `client/index.html` exibe contagem regressiva de 5 segundos, bloqueia novos inputs e recarrega a página (`window.location.reload()`) para iniciar uma sessão limpa.
- **Script de reset:** `scripts/reset_db.py` zera o banco SQLite (confirma antes de apagar).
- **Cadastro de clientes:** entidade `clientes` com `telefone` único. O LLM extrai nome e telefone (máscara `(NN) NNNN-NNNN`). Na primeira vez que um telefone aparece, o cliente é cadastrado automaticamente; em conversas seguintes, o cliente é reutilizado pelo telefone. Quando o telefone não é informado, o bot solicita ao usuário. CRUD completo em `/clientes`.
- Persistência SQLite completa: sessões, histórico de mensagens e agendamentos (banco `app/agendamento.db`).

**Validado ponta a ponta (curl)**
- Agendamento em dia útil dentro do expediente → `status=confirmado` e `validacao.valido=true`.
- Domingo ou horário fora do expediente → `status=rejeitado` e `validacao.motivo=fora_expediente`, com `reply` pedindo novo horário.
- Horário conflitante com um agendamento `confirmado` → `status=rejeitado` e `validacao.motivo=conflito`.
- Mensagem sem data/hora → `status=rascunho`.
- Data no passado ou improvável → tratada como `insuficiente` (não rejeição indevida).
- Data relativa ("amanhã" etc.) → resolvida para a data concreta correta.
- Informações dadas em mensagens separadas → consolidadas em um único registro confirmado.
- Streaming (`curl -N` com `stream=true`): eventos `token` ao vivo, `done` com `agendamento`/`validacao`, e `correcao` nos casos de rejeição.
- `GET /health` reportou `{"status": "ok", "ollama_reachable": true}`.

**Observações / decisões**
- O histórico completo é reconstruído no servidor a partir do `sessao_id` (fonte da verdade = SQLite).
- No streaming, a validação acontece ao final (depende do texto completo). Quando rejeitado, o texto inicial já transmitido é substituído pela reply reprocessada via evento `correcao`; apenas a reply final é gravada.
- **Correção aplicada durante o build:** o `gemma2:2b` retorna JSON com aspas simples (não compatível com `json.loads` estrito). O parser em `ollama_client.py` tenta `json.loads` e, se falhar, usa `ast.literal_eval` como fallback — normalizando `null`/`true`/`false` do JSON para `None`/`True`/`False`. Isso cobre blocos com campos desconhecidos (`{'data': null}`), comuns nas respostas.
- Parsing de data/hora usa `python-dateutil`. O `parse_data` usa `dayfirst=True` para formatos `DD/MM/AAAA` (e detecta ISO `AAAA-MM-DD` separadamente), garantindo que dia e mês não sejam invertidos.
- A validação acontece apenas em `data` + `hora`; cliente/serviço não são validados (o cliente é identificado apenas pelo telefone).
- O modelo `gemma2:2b` é instável na geração do JSON; o reforço no prompt reduz, mas não elimina, respostas sem bloco JSON.
- **Documentação do projeto:** além deste README, o repositório mantém `AGENTS.md` e `GEMINI.md` (diretrizes para agentes de IA e convenções de desenvolvimento) e `CHANGELOG.md` (histórico de versões). Os commits seguem [Conventional Commits](https://www.conventionalcommits.org/) com mensagens em pt-BR; push automático é proibido (apenas commits locais).

**Próximas evoluções (não implementadas)**
- Disponibilidade injetada no prompt (o modelo já conhece a agenda antes de responder).
- Fluxo de confirmação explícita pelo cliente antes de salvar como `confirmado`.
