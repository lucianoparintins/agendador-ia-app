# CHANGELOG

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

---

## [1.1.0] - 2026-08-31

### Adicionado
- **Cadastro de Clientes com Telefone Único**:
  - Nova tabela `clientes` no SQLite vinculada aos agendamentos (`cliente_id`).
  - Identificação e reuso automático de cadastro através do telefone único.
  - Endpoints CRUD em `/clientes` (`GET`, `POST`, `PUT`, `DELETE`).
  - Solicitação automática de telefone no fluxo do chat caso o usuário não informe.
- **Documento de Especificação**: `spec/2026-08-31-165000-PLANO-CLIENTE-TELEFONE.md`.

---

## [1.0.0] - 2026-08-30

### Adicionado
- **Streaming de Tokens e SSE**:
  - Parâmetro `stream: true` na rota `POST /chat`.
  - Eventos de Server-Sent Events (`token`, `correcao`, `done`, `[DONE]`).
- **Validação de Agenda e Conflitos**:
  - Validação de horário de expediente comercial e sábados.
  - Bloqueio de agendamento em datas no passado.
  - Detecção e prevenção de conflitos de horário com agendamentos confirmados (duração de 60 min).
  - Reprocessamento automático de resposta pelo Ollama quando um agendamento é rejeitado.
- **Resolução de Datas Relativas e Plausibilidade**:
  - Conversão inteligente de termos como "hoje", "amanhã", "depois de amanhã" e "próxima `<dia>`".
  - Verificação de plausibilidade com janela de 90 dias para evitar recusas indevidas.
  - Injeção da data/hora atual do sistema no system prompt do Ollama.
- **Consolidação de Agendamento por Sessão**:
  - Merge automático de informações enviadas em múltiplas mensagens na mesma sessão.
  - Gerenciamento de ciclo de vida com status (`rascunho`, `confirmado`, `rejeitado`).
- **Interface de Teste Web (Frontend)**:
  - Arquivo `client/index.html` consumindo a API com streaming em tempo real via Fetch API ReadableStream.
- **Utilitários e Scripts**:
  - Script `scripts/reset_db.py` para limpeza completa do banco SQLite com confirmação prévia.

---

## [0.1.0] - 2026-08-30

### Adicionado
- Estrutura inicial do projeto com FastAPI e Uvicorn.
- Integração básica com Ollama local (`gemma2:2b`) através de `httpx`.
- Persistência inicial em SQLite (`sessoes`, `mensagens`, `agendamentos`).
- Endpoints básicos: `POST /chat`, `GET /sessoes`, `GET /sessoes/{id}/mensagens`, `GET /agendamentos` e `GET /health`.
- Documentação inicial no `README.md`.
