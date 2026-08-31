# Plano: Entidade Cliente com Telefone Único

## Objetivo
Refatorar o sistema para que cada cliente seja uma entidade única com um telefone por cliente. O LLM extrai nome e telefone da conversa. Se não houver telefone, o bot solicita ao usuário. A busca por cliente existente é feita pelo telefone.

## Decisões confirmadas
1. **Migração:** Não migrar dados existentes — banco será resetado via `scripts/reset_db.py`.
2. **Telefone ausente:** Solicitar ao usuário (bot responde "Por favor, informe seu telefone").
3. **Nome do cliente:** LLM continua extraindo o nome da conversa.
4. **Telefone:** Extraído pelo LLM e formatado com máscara `(NN) NNNN-NNNN` (ex: `(11) 9999-8888`).
5. **Endpoints REST:** Criar CRUD completo para clientes (`GET/POST/PUT/DELETE /clientes`).

## Contexto / Stack
- FastAPI + SQLite + Ollama `gemma2:2b`
- Banco: `app/agendamento.db` (será resetado)
- Schema atual: 3 tabelas (`sessoes`, `mensagens`, `agendamentos`) — sem entidade `clientes`

## Mudanças por arquivo

### `app/db.py`
**Adicionar tabela `clientes`:**
```sql
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    telefone TEXT UNIQUE NOT NULL,  -- formato: "(11) 9999-8888"
    criado_em TEXT NOT NULL
);
```

**Modificar tabela `agendamentos`:**
- Substituir coluna `cliente TEXT` por `cliente_id INTEGER` (FK → `clientes.id`)
- Manter `FOREIGN KEY (cliente_id) REFERENCES clientes(id)`

**Novas funções CRUD:**
- `criar_cliente(nome, telefone) -> int`
- `obter_cliente_por_telefone(telefone) -> Optional[dict]`
- `obter_cliente(cliente_id) -> Optional[dict]`
- `listar_clientes() -> list`
- `atualizar_cliente(cliente_id, nome, telefone) -> None`
- `remover_cliente(cliente_id) -> None`

**Modificar funções existentes:**
- `salvar_agendamento(sessao_id, cliente_id, servico, data, hora, status)` — usar `cliente_id`
- `salvar_agendamento_rejeitado(sessao_id, cliente_id, servico, data, hora)` — idem
- `atualizar_agendamento(id, cliente_id, servico, data, hora, status)` — idem
- `listar_agendamentos()` — JOIN com `clientes` para retornar `nome` e `telefone`

### `app/schema.py`
**Novos modelos:**
```python
class Cliente(BaseModel):
    id: int
    nome: str
    telefone: str  # formato: "(11) 9999-8888"
    criado_em: str

class ClienteCreate(BaseModel):
    nome: str
    telefone: str  # formato: "(11) 9999-8888"

class ClienteUpdate(BaseModel):
    nome: Optional[str] = None
    telefone: Optional[str] = None  # formato: "(11) 9999-8888"
```

**Modificar `Agendamento`:**
- Substituir `cliente: Optional[str]` por `cliente_id: Optional[int]`
- Adicionar `telefone: Optional[str] = None`

**Modificar `AgendamentoRecord`:**
- Substituir `cliente: Optional[str]` por `cliente_id: Optional[int]`
- Adicionar `telefone: Optional[str] = None`

### `app/ollama_client.py`
**Atualizar `SYSTEM_PROMPT`:**
- Adicionar instrução para extrair `telefone` e formatar com máscara `(NN) NNNN-NNNN`
- Formato JSON: `{cliente, telefone, servico, data, hora}`
- Instruir: "Para telefone, extraia e formate no padrão (NN) NNNN-NNNN (ex: (11) 9999-8888)"

### `app/main.py`
**Novos endpoints:**
```
GET    /clientes              - listar todos
GET    /clientes/{id}         - obter por ID
POST   /clientes              - criar novo
PUT    /clientes/{id}         - atualizar
DELETE /clientes/{id}         - remover
```

**Modificar `_processar_dados()`:**
```python
# 1. Extrair telefone
telefone = dados.get("telefone")

# 2. Se não tiver telefone → solicitar ao usuário
if not telefone:
    return "Por favor, informe seu telefone para continuar.", None, None

# 3. Buscar cliente pelo telefone
cliente_existente = db.obter_cliente_por_telefone(telefone)

# 4. Se não existir → criar novo cliente
if cliente_existente:
    cliente_id = cliente_existente["id"]
else:
    nome = dados.get("cliente") or "Cliente"
    cliente_id = db.criar_cliente(nome, telefone)

# 5. Usar cliente_id ao salvar agendamento
db.salvar_agendamento(sessao_id, cliente_id, ...)
```

**Modificar `_gerar_stream()`:**
- Adicionar lógica similar para verificar telefone antes de processar agendamento

**Modificar endpoints de agendamento:**
- `listar_agendamentos()` — retornar dados do cliente via JOIN

### `scripts/reset_db.py`
- Já existe — será usado para limpar o banco antes de testar

## Testes a validar
1. Resetar banco: `python scripts/reset_db.py`
2. Subir API: `uvicorn app.main:app --reload`
3. Testar CRUD de clientes via Swagger (`/docs`):
   - `POST /clientes` com `{nome: "João", telefone: "(11) 9999-8888"}`
   - `GET /clientes`
   - `GET /clientes/{id}`
   - `PUT /clientes/{id}`
   - `DELETE /clientes/{id}`
4. Testar fluxo de chat:
   - Enviar mensagem sem telefone → bot deve solicitar telefone
   - Enviar com telefone → sistema deve criar cliente automaticamente
   - Enviar com mesmo telefone → sistema deve reutilizar cliente existente
5. Verificar agendamentos vinculados a `cliente_id` correto

## Ordem de execução
1. Resetar banco existente (rodar `scripts/reset_db.py`)
2. Modificar `app/db.py` — adicionar tabela, CRUD, modificar funções
3. Modificar `app/schema.py` — adicionar modelos, modificar existentes
4. Modificar `app/ollama_client.py` — atualizar prompt
5. Modificar `app/main.py` — adicionar endpoints, modificar processamento
6. Testes ponta a ponta
