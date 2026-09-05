# Plano: Correção do Fluxo Multi-turno e Extração Inteligente de Dados

## Objetivo
Corrigir bugs críticos e melhorar a robustez do fluxo de conversa multi-turno para que o sistema consiga acumular dados de agendamento de forma incremental ao longo de vários turnos, sem perda de contexto e sem confundir o modelo LLM.

## Decisões confirmadas
1. **Duplicação de mensagem:** Remover a duplicação da mensagem do usuário no payload enviado ao Ollama. O `historico()` já contém a mensagem recém-salva; não passar `nova_mensagem` separadamente.
2. **Rascunho sem telefone:** Permitir criação/atualização de rascunho mesmo quando o telefone não estiver presente no turno atual. Telefone só é obrigatório para transicionar de `rascunho` → `confirmado`.
3. **Prompt acumulativo:** Reescrever o `SYSTEM_PROMPT` para instruir explicitamente o LLM a manter dados de turnos anteriores no JSON e usar aspas duplas (JSON válido).
4. **`dayfirst=True` no conflito:** Corrigir `_data_iso` em `db.py` para usar `dayfirst=True`.
5. **Expediente com duração:** Validar que o fim do atendimento (início + 60min) não ultrapasse o horário de fechamento.
6. **Data no passado:** Distinguir corretamente `no_passado` de `insuficiente` em `validar_agendamento`.
7. **Regex de JSON:** Trocar o regex non-greedy `\{.*?\}` por um parser baseado em contagem de chaves para suportar JSONs com texto ao redor.
8. **Janela de contexto:** Limitar o histórico enviado ao LLM às últimas 14 mensagens para não estourar a janela do `gemma2:2b`.

## Contexto / Stack
- FastAPI + SQLite + Ollama `gemma2:2b`
- Banco: `app/agendamento.db`
- O fluxo atual persiste mensagens por sessão e reenvia o histórico completo ao LLM a cada turno
- O `_processar_dados` bloqueia prematuramente quando `telefone` é `null`, descartando dados já extraídos

## Mudanças por arquivo

### `app/ollama_client.py`

**1. Reescrever `SYSTEM_PROMPT` (L12-28):**
```python
SYSTEM_PROMPT = (
    "Você é um assistente de agendamento de serviços de barbearia/salão de beleza. "
    "Converse de forma amigável e conduza o cliente a informar: nome, telefone, "
    "serviço desejado (ex.: corte de cabelo, barba, manicure), data e horário. "
    "Pergunte um ou dois dados por vez, sem sobrecarregar o cliente. "
    "Quando tiver todos os dados, confirme o agendamento.\n\n"
    "REGRA IMPORTANTE: Ao final de TODA resposta, inclua um bloco JSON com aspas duplas "
    "no formato:\n"
    '{"cliente": ..., "telefone": ..., "servico": ..., "data": ..., "hora": ...}\n\n'
    "- Preencha apenas os campos que já conhece (null para os desconhecidos).\n"
    "- MANTENHA no JSON todos os dados já informados nas mensagens anteriores. "
    "Só altere um campo se o cliente explicitamente corrigir ou complementar.\n"
    "- Para telefone, formate no padrão (NN) NNNNN-NNNN (ex: (92) 99999-8888).\n"
    "- Apresente datas no formato DD/MM/YYYY.\n"
    "- Quando o cliente usar datas relativas (hoje, amanhã, próxima sexta), "
    "calcule a data exata a partir da data atual fornecida. "
    "Se não tiver certeza da data, deixe como null.\n"
    "- Responda em português do Brasil."
)
```

**2. Trocar regex de JSON (L30) por parser com contagem de chaves:**
```python
def _extrair_json(texto: str) -> Optional[dict]:
    """Extrai o último bloco JSON {...} do texto usando contagem de chaves."""
    fim = texto.rfind("}")
    if fim == -1:
        return None
    nivel = 0
    inicio = -1
    for i in range(fim, -1, -1):
        if texto[i] == "}":
            nivel += 1
        elif texto[i] == "{":
            nivel -= 1
        if nivel == 0:
            inicio = i
            break
    if inicio == -1:
        return None
    blob = texto[inicio : fim + 1]
    try:
        data = json.loads(blob)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        fix = (
            blob.replace("null", "None")
            .replace("true", "True")
            .replace("false", "False")
        )
        data = ast.literal_eval(fix)
        return data if isinstance(data, dict) else None
    except (ValueError, SyntaxError):
        return None
```

**3. Corrigir `_montar_messages` (L91-95) — não duplicar a mensagem:**
```python
@staticmethod
def _montar_messages(historico: List[dict], nova_mensagem: str = "") -> List[dict]:
    messages = [{"role": "system", "content": _system_prompt()}]
    messages.extend(historico)
    if nova_mensagem:
        messages.append({"role": "user", "content": nova_mensagem})
    return messages
```

### `app/main.py`

**4. Corrigir duplicação de mensagem (L230-244):**
- Salvar a mensagem do usuário no banco **antes** de montar o histórico (como já faz)
- Passar `nova_mensagem=""` para `ollama.chat()` e `ollama.stream_chat()`, já que `historico()` já contém a mensagem recém-salva

```python
# Antes (duplica):
db.adicionar_mensagem(sessao_id, "user", req.mensagem)
historico = lambda: [...]  # já inclui req.mensagem
reply, dados = await ollama.chat(historico(), req.mensagem)  # duplica!

# Depois (correto) — fluxo comum e streaming:
db.adicionar_mensagem(sessao_id, "user", req.mensagem)
historico = lambda: [...]  # já inclui req.mensagem
reply, dados = await ollama.chat(historico(), "")  # não duplica
# stream:
_gerar_stream(sessao_id, historico, "")             # idem
```

**5. Refatorar `_processar_dados` (L68-100) — rascunho antes do telefone:**
```python
async def _processar_dados(
    sessao_id: int, dados: dict, historico
) -> Tuple[str, Optional[Agendamento], Optional[Validacao]]:
    # 1. Resolver datas relativas PRIMEIRO
    dados["data"] = agenda.resolver_data_relativa(dados.get("data"))
    dados["data"] = agenda.formatar_data(dados.get("data"))

    # 2. Buscar rascunho ativo e mesclar ANTES de checar telefone
    rascunho = db.obter_rascunho_ativo(sessao_id)
    if rascunho is not None:
        finais = dict(rascunho)
        for chave in ("servico", "data", "hora"):
            if dados.get(chave):
                finais[chave] = dados[chave]
    else:
        finais = {
            "servico": dados.get("servico"),
            "data": dados.get("data"),
            "hora": dados.get("hora"),
        }

    # 3. Resolver telefone e cliente
    telefone = dados.get("telefone")
    if not telefone and rascunho is not None:
        # Tentar recuperar telefone do cliente já vinculado ao rascunho
        cliente_existente = db.obter_cliente(rascunho["cliente_id"]) if rascunho.get("cliente_id") else None
        if cliente_existente:
            telefone = cliente_existente["telefone"]

    if telefone:
        cliente_id = _obter_ou_criar_cliente({**dados, "telefone": telefone})
        finais["cliente_id"] = cliente_id
    else:
        finais.setdefault("cliente_id", None)

    # 4. Validar agendamento
    validacao = agenda.validar_agendamento(finais.get("data"), finais.get("hora"))

    if validacao.valido:
        # Telefone obrigatório apenas para CONFIRMAR
        if not telefone:
            _salvar_rascunho_parcial(sessao_id, finais)
            return (
                "Quase lá! Preciso do seu telefone para confirmar o agendamento.",
                _montar_agendamento(finais, telefone, "rascunho"),
                Validacao(valido=False, motivo="insuficiente"),
            )
        # Confirmar agendamento
        db.salvar_agendamento(
            sessao_id, finais["cliente_id"],
            finais.get("servico"), finais.get("data"),
            finais.get("hora"), "confirmado",
        )
        return (
            None,  # manter reply original do LLM
            _montar_agendamento(finais, telefone, "confirmado"),
            Validacao(valido=True),
        )

    if validacao.motivo == "insuficiente":
        # Salvar rascunho parcial com o que temos
        if any(finais.get(k) for k in ("servico", "data", "hora")):
            _salvar_rascunho_parcial(sessao_id, finais)
        return (
            None,  # manter reply conversacional do LLM
            _montar_agendamento(finais, telefone, "rascunho"),
            Validacao(valido=False, motivo="insuficiente"),
        )

    # Rejeitado (conflito, fora_expediente, no_passado, etc.)
    # ... lógica de reprocessamento existente (mantida)
```

**6. Extrair helpers auxiliares:**
```python
def _salvar_rascunho_parcial(sessao_id: int, finais: dict) -> None:
    db.salvar_agendamento(
        sessao_id, finais.get("cliente_id"),
        finais.get("servico"), finais.get("data"),
        finais.get("hora"), "rascunho",
    )

def _montar_agendamento(finais: dict, telefone: Optional[str], status: str) -> Agendamento:
    cliente_id = finais.get("cliente_id")
    cliente = finais.get("cliente")
    if not cliente and cliente_id:
        cliente = (db.obter_cliente(cliente_id) or {}).get("nome")
    return Agendamento(
        cliente_id=cliente_id,
        cliente=cliente,
        telefone=telefone,
        servico=finais.get("servico"),
        data=finais.get("data"),
        hora=finais.get("hora"),
        status=status,
    )
```

**7. Limitar janela de contexto (L232-236):**
```python
MAX_HISTORICO = 14  # últimas 14 mensagens (~7 turnos)

historico = lambda: [
    {"role": m["role"], "content": m["conteudo"]}
    for m in db.listar_mensagens(sessao_id)
    if m["role"] in ("user", "assistant")
][-MAX_HISTORICO:]
```

### `app/db.py`

**8. Corrigir `_data_iso` (L238-242) — adicionar `dayfirst=True`:**
```python
def _data_iso(texto) -> Optional[str]:
    try:
        return dateutil_parser.parse(str(texto), dayfirst=True).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None
```

**9. Ativar Foreign Keys (em `_connect`, L58-62):**
```python
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

### `app/agenda.py`

**10. Validar fim do atendimento dentro do expediente (L129-136):**
```python
def _in_expediente(d: date, h: time) -> bool:
    janela = EXPEDIENTE.get(d.weekday())
    if janela is None:
        return False
    abertura, fechamento = janela
    inicio = time(abertura, 0)
    fim = time(fechamento, 0)
    fim_atendimento = (datetime.combine(date.min, h) + timedelta(minutes=DURACAO_MIN)).time()
    return inicio <= h and fim_atendimento <= fim
```

**11. Distinguir `no_passado` de `insuficiente` (L147-159):**
```python
def validar_agendamento(data_raw, hora_raw) -> ValidacaoResult:
    d = parse_data(data_raw)
    h = parse_hora(hora_raw)

    if d is None and h is None:
        return ValidacaoResult(valido=False, motivo="insuficiente")
    if d is None:
        return ValidacaoResult(valido=False, motivo="data_invalida")
    if h is None:
        return ValidacaoResult(valido=False, motivo="hora_invalida")

    # Checar passado ANTES de plausibilidade
    agora = datetime.now()
    horario = datetime.combine(d, h)
    if horario <= agora:
        return ValidacaoResult(valido=False, motivo="no_passado", data=d, hora=h)

    if not data_plausivel(data_raw):
        return ValidacaoResult(valido=False, motivo="data_invalida")

    if not _in_expediente(d, h):
        return ValidacaoResult(valido=False, motivo="fora_expediente", data=d, hora=h)

    inicio = h
    fim = (datetime.combine(date.min, h) + timedelta(minutes=DURACAO_MIN)).time()
    if db.verificar_conflito(d.isoformat(), inicio.isoformat(), fim.isoformat()):
        return ValidacaoResult(valido=False, motivo="conflito", data=d, hora=h)

    return ValidacaoResult(valido=True, motivo=None, data=d, hora=h)
```

### `client/index.html`

**12. Persistir sessão no `sessionStorage` (L30):**
```javascript
// Recuperar sessão ao carregar a página
let sessaoId = sessionStorage.getItem("sessaoId")
    ? parseInt(sessionStorage.getItem("sessaoId"))
    : null;

// Ao receber sessao_id do backend (no evento "done"):
sessaoId = evt.sessao_id;
sessionStorage.setItem("sessaoId", sessaoId);
```

## Testes a validar

### Cenário 1: Fluxo multi-turno incremental
1. Turno 1: *"Quero cortar o cabelo amanhã às 10h"* → deve criar rascunho com serviço + data + hora (sem telefone)
2. Turno 2: *"Meu telefone é (92) 99999-8888"* → deve mesclar telefone no rascunho e confirmar
3. Verificar: agendamento com `status='confirmado'` no banco

### Cenário 2: Dados espalhados em 3+ turnos
1. Turno 1: *"Oi, quero agendar"* → rascunho vazio (ou nenhum), bot pergunta dados
2. Turno 2: *"Quero cortar o cabelo"* → rascunho com servico
3. Turno 3: *"Amanhã às 14h"* → rascunho com servico + data + hora
4. Turno 4: *"(92) 99999-8888, me chamo João"* → confirma agendamento

### Cenário 3: Telefone já fornecido, LLM omite no turno seguinte
1. Turno 1: *"Sou o João, telefone (92) 99999-8888"* → rascunho com cliente + telefone
2. Turno 2: *"Corte de cabelo sexta às 15h"* → LLM retorna `telefone: null` no JSON
3. Verificar: sistema deve recuperar telefone do rascunho/cliente existente e confirmar — agendamento com `status='confirmado'` e `agendamento.cliente == "João"` no banco

### Cenário 4: Rejeição e re-tentativa
1. Agendar para domingo → rejeitado (`fora_expediente`), bot pede outra data
2. Agendar para segunda 10h → confirmado
3. Verificar: rascunho manteve serviço e cliente entre os turnos

### Cenário 5: Conflito de horário
1. Confirmar agendamento para 15/09/2026 às 10h
2. Tentar agendar outro para 15/09/2026 às 10h → rejeitado (`conflito`)
3. Verificar: detecção de conflito funciona com data no formato DD/MM/YYYY

### Cenário 6: Expediente (borda)
1. Agendar para segunda às 17:30 → rejeitado (atendimento terminaria às 18:30)
2. Agendar para segunda às 17:00 → confirmado (termina às 18:00)

### Cenário 7: Data passada
1. Agendar para 01/01/2020 → rejeitado com `motivo="no_passado"` (não `insuficiente`)

### Cenário 8: Janela de contexto
1. Simular conversa longa (15+ turnos) → verificar que apenas as últimas 14 mensagens são enviadas ao LLM

## Ordem de execução
1. Corrigir `app/ollama_client.py` — reescrever prompt, corrigir regex, ajustar `_montar_messages`
2. Corrigir `app/db.py` — `_data_iso` com `dayfirst=True`, ativar foreign keys
3. Corrigir `app/agenda.py` — expediente com duração, distinguir `no_passado`
4. Refatorar `app/main.py` — corrigir duplicação, refatorar `_processar_dados`, limitar histórico
5. Corrigir `client/index.html` — persistir sessão no `sessionStorage`
6. Rodar `python3 -m py_compile app/*.py` para checar sintaxe
7. Resetar banco: `python3 scripts/reset_db.py`
8. Testes ponta a ponta com os 8 cenários descritos
