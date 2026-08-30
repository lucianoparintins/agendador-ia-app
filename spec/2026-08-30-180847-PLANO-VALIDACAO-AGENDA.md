# Plano: Validação de data/hora contra a agenda real do negócio

## Objetivo
Adicionar validação de agendamento no backend: respeitar o horário de funcionamento e rejeitar conflito com agendamentos já confirmados. Quando inválido, **reprocessar com o Ollama** para gerar resposta amigável pedindo novo horário.

## Decisões confirmadas
1. Agenda = **horário de funcionamento + conflito** com agendamentos salvos.
2. Conflito/inválido → **rejeitar** (não salvar como confirmado) e pedir novo horário.
3. Validação no **backend** (não injeta disponibilidade no prompt nesta versão).
4. Rejeição → **reprocessar com o Ollama** para resposta amigável.
5. Duração de serviço: **1h fixa**.
6. Parsing de data: **python-dateutil** (nova dependência).

## Arquivo novo: `app/agenda.py`
Toda a lógica isolada do `main.py`. Contém:

**Configurações** (constantes):
- `EXPEDIENTE = {seg: (9,18), ter: (9,18), qua: (9,18), qui: (9,18), sex: (9,18), sáb: (9,13)}` — domingo fechado.
- `DURACAO_MIN = 60` (1h fixa).

**Funções**:
- `parse_data(s)` → `date` usando `dateutil.parser` (aceita AAAA-MM-DD, DD/MM/AAAA, etc.); `None` se inválido.
- `parse_hora(s)` → `time` (HH:MM, HHhMM, HHMM, etc.); `None` se inválido.
- `validar_agendamento(data_raw, hora_raw)` → `ValidacaoResult(valido: bool, motivo: Optional[str], data: Optional[date], hora: Optional[time])`.
  - sem data ou hora → `motivo="insuficiente"` (não é erro, agenda em construção).
  - data/hora não parseável → `motivo` de `data_invalida`/`hora_invalida`.
  - data/hora no passado → `no_passado`.
  - dia/semana fora do expediente → `fora_expediente`.
  - conflito com agendamentos confirmados (sobreposição de 1h) → `conflito`.
  - ok → `valido=True`.
- `verificar_sobreposicao` auxiliar (usa `db.verificar_conflito`).

## Mudanças em `app/db.py`
- Nova função `verificar_conflito(data, hora_inicio_iso, hora_fim_iso)` → retorna `bool` se houver agendamento com `status='confirmado'` na mesma `data` cujo intervalo `[hora, hora+1h)` se sobrepõe.

## Mudanças em `app/schema.py`
- `Agendamento`: add campo `status: Optional[str]` (confirmado/rascunho/rejeitado).
- Novo `Validacao` model: `{valido: bool, motivo: Optional[str]}`.
- `ChatResponse`: add `validacao: Optional[Validacao]`.

## Mudanças em `app/ollama_client.py`
- Adicionar método `reprocessar_rejeicao(historico, rejeicao_texto)` (ou param opcional em `chat`) que insere no histórico uma mensagem de contexto (role `system`) explicando a indisponibilidade e instruindo o modelo a pedir novo horário. Retorna nova `reply` (+ JSON se vier).

## Mudanças em `app/main.py` (rota `/chat`)
Fluxo pós-extração de `dados`:
1. Montar `Agendamento`.
2. `validar = agenda.validar_agendamento(dados.data, dados.hora)`.
3. - **insuficiente** → persiste `rascunho` (se houver algum dado) — comportamento atual.
   - **válido** → persiste `status='confirmado'`.
   - **inválido** (data_invalida/no_passado/fora_expediente/conflito) → **não salva**; chama `ollama.reprocessar_rejeicao(...)` gerando novo `reply`; `status='rejeitado'` e `validacao` preenchido (salva registro com status `rejeitado`).
4. Retorna `ChatResponse` com `reply`, `agendamento` e `validacao`.

## Mudanças em `requirements.txt`
- Adicionar `python-dateutil`.

## Mudanças em `README.md`
- Documentar regras de agenda (expediente, duração 1h, conflito), novo campo `validacao`/`status` e comportamento de rejeição. Atualizar "Estado atual".

## Testes a executar (curl)
1. Bom dia útil em expediente → `status=confirmado`.
2. Domingo ou fora do expediente → `rejeitado` + motivo `fora_expediente`.
3. Horário que conflita com confirmado → `rejeitado` + motivo `conflito`.
4. Sem data/hora → `rascunho`.
5. Data no passado → `rejeitado` + motivo `no_passado`.
6. Confirmar que o rejeitado gera `reply` pedindo novo horário (via reprocessamento).
