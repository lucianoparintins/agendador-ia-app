# GEMINI.md

Este documento fornece diretrizes de contexto, padrões de desenvolvimento e instruções operacionais para agentes de inteligência artificial e desenvolvedores que trabalham no projeto **Agendador IA**.

---

## 1. Visão Geral do Projeto

O **Agendador IA** é uma API REST desenvolvida em **FastAPI** para automação de agendamentos de barbearia e salão de beleza. O sistema utiliza um modelo de linguagem local via **Ollama** (`gemma2:2b`) para conduzir a conversa, extrair intenções e entidades estruturadas (nome, telefone, serviço, data e hora) e persistir o fluxo de agendamento em banco **SQLite**.

### Principais Características
- **Execução 100% local**: Modelo LLM via Ollama (`http://localhost:11434`) e banco SQLite local.
- **Extração Tolerante a Falhas**: Parsing de JSON resiliente em Python com suporte a aspas simples e literais não padronizados gerados por SLMs (Small Language Models).
- **Validação Rigorosa de Regras de Negócio**: Validações de data no passado, horário de expediente, duração fixa (60 min) e sobreposição/conflito de horários.
- **Resolução de Datas Relativas**: Interpretação automática de "hoje", "amanhã", "próxima sexta", etc.
- **Suporte a Streaming SSE**: Endpoint `/chat` com suporte a Server-Sent Events e reprocessamento com feedback corretivo quando há rejeição de horário.
- **Gestão de Clientes**: Entidade cliente identificada de forma única pelo número de telefone formatado.

---

## 2. Stack Tecnológica

- **Linguagem**: Python 3.10+ (desenvolvido em Python 3.13)
- **Framework Web**: FastAPI + Uvicorn
- **Cliente HTTP Assíncrono**: HTTPX
- **Validação de Schemas**: Pydantic v2
- **Manipulação de Datas**: `python-dateutil` + `datetime` nativo
- **Banco de Dados**: SQLite3 (`sqlite3` da biblioteca padrão)
- **Frontend de Teste**: HTML5 / Vanilla JavaScript (Fetch API + EventSource/ReadableStream)

---

## 3. Estrutura do Projeto

```
agendador-ia-app/
├── app/
│   ├── __init__.py
│   ├── agenda.py          # Regras de negócio da agenda, expediente, validações e datas relativas
│   ├── db.py              # Camada de banco de dados SQLite, queries SQL e conexões
│   ├── main.py            # Inicialização FastAPI, rotas, CORS, streaming SSE e orquestração
│   ├── ollama_client.py   # Integração assíncrona com Ollama, prompts e parser de JSON
│   └── schema.py          # Schemas Pydantic (Request/Response, Entidades)
├── client/
│   └── index.html         # Interface web estática para teste do chat e SSE
├── scripts/
│   └── reset_db.py        # Script utilitário para resetar o banco de dados
├── spec/                  # Documentações de plano e especificações históricas
├── requirements.txt       # Dependências Python
├── README.md              # Documentação para o usuário final
├── CHANGELOG.md           # Histórico de alterações do projeto
├── AGENTS.md              # Guia para agentes de IA e pair programming
└── GEMINI.md              # Este arquivo (contexto do projeto e diretrizes)
```

---

## 4. Regras de Negócio Críticas

1. **Expediente**:
   - Segunda a Sexta: 09:00 às 18:00
   - Sábado: 09:00 às 13:00
   - Domingo: Fechado
2. **Duração do Atendimento**: Fixa em 60 minutos por agendamento.
3. **Validação de Conflito**: Não é permitido agendar se houver sobreposição com agendamento com `status = 'confirmado'` na mesma data.
4. **Ciclo de Vida do Agendamento**:
   - `rascunho`: Quando faltam informações (ex.: data, hora, telefone ou serviço) ou dados improváveis.
   - `confirmado`: Quando todos os dados estão presentes e válidos dentro do expediente e sem conflitos.
   - `rejeitado`: Quando a data/hora solicitada é inválida, está no passado, fora de expediente ou possui conflito.
5. **Consolidação por Sessão**:
   - Apenas 1 rascunho ativo por sessão (`sessao_id`).
   - Respostas sucessivas atualizam e completam os campos existentes do rascunho.
6. **Clientes**:
   - O telefone é o identificador único.
   - Se o cliente não informar telefone, o sistema não avança para confirmação.

---

## 5. Convenções de Desenvolvimento

- **Código Limpo e Tipado**: Usar type hints em todas as funções (`typing.Optional`, `list`, etc.).
- **Persistência Segura**: Usar parâmetros `?` nas consultas SQL do SQLite para evitar injeção de SQL.
- **Data e Hora**: Normalizar formatos no banco e respeitar `dayfirst=True` para o padrão brasileiro `DD/MM/YYYY`.
- **Tratamento LLM**: Nunca assumir que o modelo retornará um JSON perfeitamente válido. Sempre tratar via `_extrair_json` e prever fallbacks.
