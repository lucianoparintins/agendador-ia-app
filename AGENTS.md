# AGENTS.md

Guia de operação e diretrizes para agentes autônomos, assistentes de IA e pair programmers que interagem com o repositório **Agendador IA**.

---

## 1. Comandos Essenciais

### Ambiente Virtual e Dependências
```bash
# Ativar o ambiente virtual
source .venv/bin/activate

# Instalar ou atualizar dependências
pip install -r requirements.txt
```

### Execução da Aplicação
```bash
# Executar a API FastAPI com reload automático
uvicorn app.main:app --reload --port 8000

# Executar o frontend estático para testes
python3 -m http.server 8080 -d client
```

### Validações de Sintaxe e Banco
```bash
# Checagem de sintaxe dos arquivos Python
python3 -m py_compile app/*.py scripts/*.py

# Resetar o banco de dados (CUIDADO: apaga todos os registros)
python3 scripts/reset_db.py
```

---

## 2. Padrões de Código e Arquitetura

1. **Separação de Responsabilidades**:
   - `app/main.py`: Camada de roteamento HTTP, CORS, orquestração de dependências e streaming. Não coloque queries SQL ou regras de expediente diretamente aqui.
   - `app/db.py`: Camada de acesso a dados SQLite. Todas as transações com banco devem passar por esta camada usando context manager `_tx()` ou conexões com parâmetros parametrizados (`?`).
   - `app/agenda.py`: Núcleo de regras de negócio de agendamento (horários, expediente, dias da semana, sobreposição e parsing de datas). Não deve depender do LLM.
   - `app/ollama_client.py`: Comunicação com o servidor Ollama via HTTP assíncrono. Contém o prompt de sistema e parser de respostas JSON.
   - `app/schema.py`: Modelos Pydantic v2 para validação de entrada, saída e tipagem estrita.

2. **Manipulação de LLM com Modelos Leves (`gemma2:2b`)**:
   - Modelos locais de 2B a 3B parâmetros tendem a produzir JSONs com pequenas falhas sintáticas (ex.: aspas simples, `None` em vez de `null`, chaves soltas).
   - Mantenha sempre a resiliência no método `_extrair_json` em `ollama_client.py`.
   - Se alterar o `SYSTEM_PROMPT`, certifique-se de que a instrução de retornar o bloco JSON ao final continue explícita e clara.

3. **Datas e Horários**:
   - O padrão principal do sistema no chat e persistência atual é dia/mês/ano (`DD/MM/YYYY`).
   - Sempre utilize `dayfirst=True` ao fazer parsing com `dateutil_parser` em datas não-ISO para não inverter dia e mês.

---

## 3. Diretrizes para Modificações

- **Não altere o schema do banco sem migração/ajuste em `SCHEMA`**: O banco é criado sob demanda via `db.init_db()` usando `CREATE TABLE IF NOT EXISTS`. Caso adicione colunas, garanta compatibilidade ou documente a necessidade de recriação do banco.
- **Preservação de Documentação**: Se alterar comportamentos de endpoints ou regras de validação, atualize o `README.md`, `CHANGELOG.md` e os arquivos de especificação correspondentes em `spec/`.
- **Prevenção de Regressões de Streaming**: Ao alterar rotas do `/chat`, lembre-se de que o endpoint suporta tanto requisições comuns (JSON direto) quanto streaming SSE (`stream: true`). Teste ambos os fluxos.
- **Padrão de Commits Locais (Conventional Commits)**:
  - Realizar commits seguindo a especificação do **Conventional Commits** com descrições em **Português do Brasil (pt-BR)**.
  - Formato: `<tipo>[escopo opcional]: <descrição concisa em minúsculas>` (máximo 72 caracteres, sem ponto final).
  - Tipos comuns:
    - `feat`: Novo recurso ou funcionalidade (ex.: `feat(chat): adiciona suporte a cancelamento de agendamento`).
    - `fix`: Correção de bug (ex.: `fix(agenda): corrige calculo de sobreposicao de horarios`).
    - `docs`: Documentação (ex.: `docs: atualiza especificacao no AGENTS.md`).
    - `refactor`: Refatoração interna sem alterar comportamento externo.
    - `test`: Testes unitários ou de integração.
    - `chore`: Atualização de configurações, scripts auxiliares ou dependências.
    - `style`: Ajustes estéticos/formatação sem alteração de lógica.


