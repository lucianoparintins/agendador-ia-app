# Plano: Interface HTML simples para testar o chat (`client/`)

## Objetivo
Criar um diretório `client/` com um único arquivo HTML que conecta ao `POST /chat` do FastAPI e permite conversar com o assistente, servido por um servidor Python simples (`python -m http.server`) — o mais simples possível, apenas para testar o chat funcionando.

## Decisões confirmadas
1. **Formato:** arquivo único `client/index.html` (HTML + CSS inline + JS puro, sem build, sem frameworks).
2. **Transporte:** `fetch` POST para `http://localhost:8000/chat` com `stream: true`, lendo o corpo via `ReadableStream`/`getReader()` e um parser SSE mínimo.
3. **Estado da conversa:** guardar `sessao_id` (lido do evento `done`) para que as próximas mensagens continuem a mesma sessão.
4. **CORS:** adicionar `CORSMiddleware` no FastAPI (todas as origens, uso local/dev) para permitir que o HTML servido em outra porta (ex.: 8080) chame o `/chat` na porta 8000.

## Contexto
- O `POST /chat` aceita `{sessao_id?, mensagem, stream?}`. Com `stream=true` retorna SSE com eventos: `token` (pedaço ao vivo), `correcao` (reply reprocessada quando o horário é rejeitado), `done` (com `sessao_id`, `agendamento` e `validacao`) e terminador `[DONE]`.
- O `app/main.py` hoje não possui middleware de CORS; sem ele o navegador bloqueia a chamada cross-origin.

## Mudanças por arquivo

### `client/index.html` (novo)
- Campos: uma `caixa de mensagem` + botão "Enviar" + área de conversa com bolhas (user à direita, assistant à esquerda).
- JS:
  - `POST /chat` em `http://localhost:8000` com `{ mensagem, sessao_id, stream: true }`;
  - itera o stream com `getReader()` decodificando pedaços UTF-8, acumulando linhas `data: <json>` e aplicando:
    - `token` → apenda o conteúdo à bolha do assistente em aberto;
    - `correcao` → substitui o texto da bolha em aberto pela `reply` corrigida;
    - `done` → persiste `sessao_id` em variável para a próxima troca e mostra resumo de `agendamento`/`validacao`;
    - `[DONE]` → encerra leitura.
  - Exibe estado "digitando…" enquanto aguarda a resposta.
- CSS inline mínimo (algumas linhas) para visual legível.

### `app/main.py`
- Adicionar `CORSMiddleware` do `fastapi.middleware.cors` com `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]` (somente uso local/dev).

## Testes a validar
1. Subir a API: `uvicorn app.main:app --reload`.
2. Subir o client: `python -m http.server 8080 -d client` e abrir `http://localhost:8080`.
3. Enviar "Bom dia, quero agendar um corte de cabelo" → responder com cliente, data e hora → ver tokens ao vivo, `done`, e o `sessao_id` reutilizado nas mensagens seguintes.
4. Pedir horário no domingo/fora do expediente → exibir a `correcao` (reply pedindo novo horário).

## Documentação
- Atualizar `README.md`: mencionar o diretório `client/` e mover "Frontend/UI de chat" de "Próximas evoluções".