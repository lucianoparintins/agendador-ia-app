from contextlib import asynccontextmanager
import json
from typing import AsyncIterator, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import agenda, db
from .ollama_client import _extrair_json, OllamaClient
from .schema import (
    Agendamento,
    ChatRequest,
    ChatResponse,
    Cliente,
    ClienteCreate,
    ClienteUpdate,
    Validacao,
)

ollama = OllamaClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Agendador IA", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    ok = await ollama.check_health()
    return {"status": "ok" if ok else "degraded", "ollama_reachable": ok}


MOTIVO_TEXTO = {
    "no_passado": "a data/hora solicitada já passou",
    "fora_expediente": "o estabelecimento não atende nesse dia/horário",
    "conflito": "o horário já está reservado",
    "data_invalida": "a data informada não é válida",
    "hora_invalida": "o horário informado não é válido",
}


def _obter_ou_criar_cliente(dados: dict) -> Optional[int]:
    telefone = dados.get("telefone")
    if not telefone:
        return None

    cliente = db.obter_cliente_por_telefone(telefone)
    if cliente is not None:
        return cliente["id"]

    nome = dados.get("cliente") or "Cliente"
    return db.criar_cliente(nome, telefone)


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
        cliente_existente = (
            db.obter_cliente(rascunho["cliente_id"])
            if rascunho.get("cliente_id")
            else None
        )
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
    agendamento = _montar_agendamento(finais, telefone, "rejeitado")
    validacao = Validacao(valido=False, motivo=validacao.motivo)
    motivo_texto = MOTIVO_TEXTO.get(
        validacao.motivo, "o horário não está disponível"
    )
    rejeicao_texto = (
        f"O cliente pediu para agendar em {finais.get('data')} às "
        f"{finais.get('hora')}, mas isso não é possível porque "
        f"{motivo_texto}."
    )
    db.salvar_agendamento_rejeitado(
        sessao_id,
        finais.get("cliente_id"),
        finais.get("servico"),
        finais.get("data"),
        finais.get("hora"),
    )
    if rascunho is not None:
        db.atualizar_agendamento(
            rascunho["id"],
            finais.get("cliente_id"),
            finais.get("servico"),
            None,
            None,
            "rascunho",
        )
    else:
        db.salvar_agendamento(
            sessao_id,
            finais.get("cliente_id"),
            finais.get("servico"),
            None,
            None,
            status="rascunho",
        )
    reply, _ = await ollama.reprocessar_rejeicao(historico(), rejeicao_texto)

    return reply, agendamento, validacao


def _sse(data) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _gerar_stream(
    sessao_id: int, historico, nova_mensagem: str
) -> AsyncIterator[str]:
    partes: list[str] = []
    async for chunk in ollama.stream_chat(historico(), nova_mensagem):
        partes.append(chunk)
        yield _sse({"type": "token", "content": chunk})

    texto = "".join(partes)
    dados = _extrair_json(texto)

    if dados:
        reply_final, agendamento, validacao = await _processar_dados(
            sessao_id, dados, historico
        )
        if reply_final is not None and reply_final != texto:
            yield _sse({"type": "correcao", "reply": reply_final})
            reply = reply_final
        else:
            reply = texto
        db.adicionar_mensagem(sessao_id, "assistant", reply)
        yield _sse({
            "type": "done",
            "sessao_id": sessao_id,
            "agendamento": agendamento.model_dump() if agendamento else None,
            "validacao": validacao.model_dump() if validacao else None,
        })
    else:
        db.adicionar_mensagem(sessao_id, "assistant", texto)
        yield _sse({
            "type": "done",
            "sessao_id": sessao_id,
            "agendamento": None,
            "validacao": None,
        })

    yield "data: [DONE]\n\n"


MAX_HISTORICO = 14  # últimas 14 mensagens (~7 turnos)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if req.sessao_id is not None:
        sessao = db.obter_sessao(req.sessao_id)
        if sessao is None:
            raise HTTPException(404, "Sessão não encontrada")
        sessao_id = req.sessao_id
    else:
        sessao_id = db.criar_sessao(titulo=req.mensagem[:60])

    db.adicionar_mensagem(sessao_id, "user", req.mensagem)

    historico = lambda: [
        {"role": m["role"], "content": m["conteudo"]}
        for m in db.listar_mensagens(sessao_id)
        if m["role"] in ("user", "assistant")
    ][-MAX_HISTORICO:]

    if req.stream:
        return StreamingResponse(
            _gerar_stream(sessao_id, historico, ""),
            media_type="text/event-stream",
        )

    reply, dados = await ollama.chat(historico(), "")

    agendamento = None
    validacao: Validacao | None = None

    if dados:
        reply_final, agendamento, validacao = await _processar_dados(
            sessao_id, dados, historico
        )
        if reply_final is not None:
            reply = reply_final

    db.adicionar_mensagem(sessao_id, "assistant", reply)

    return ChatResponse(
        sessao_id=sessao_id,
        reply=reply,
        agendamento=agendamento,
        validacao=validacao,
    )


@app.get("/sessoes")
async def listar_sessoes():
    return db.listar_sessoes()


@app.get("/sessoes/{sessao_id}/mensagens")
async def messagens_da_sessao(sessao_id: int):
    if db.obter_sessao(sessao_id) is None:
        raise HTTPException(404, "Sessão não encontrada")
    return db.listar_mensagens(sessao_id)


@app.get("/agendamentos")
async def listar_agendamentos(limit: int = Query(100, ge=1, le=1000)):
    return db.listar_agendamentos()[-limit:]


@app.get("/clientes", response_model=list[Cliente])
async def listar_clientes():
    return db.listar_clientes()


@app.get("/clientes/{cliente_id}", response_model=Cliente)
async def obter_cliente_endpoint(cliente_id: int):
    cliente = db.obter_cliente(cliente_id)
    if cliente is None:
        raise HTTPException(404, "Cliente não encontrado")
    return cliente


@app.post("/clientes", response_model=Cliente, status_code=201)
async def criar_cliente_endpoint(cliente: ClienteCreate):
    if db.obter_cliente_por_telefone(cliente.telefone) is not None:
        raise HTTPException(409, "Já existe um cliente com esse telefone")
    cliente_id = db.criar_cliente(cliente.nome, cliente.telefone)
    return db.obter_cliente(cliente_id)


@app.put("/clientes/{cliente_id}", response_model=Cliente)
async def atualizar_cliente_endpoint(cliente_id: int, cliente: ClienteUpdate):
    existente = db.obter_cliente(cliente_id)
    if existente is None:
        raise HTTPException(404, "Cliente não encontrado")

    novo_nome = cliente.nome if cliente.nome is not None else existente["nome"]
    novo_telefone = (
        cliente.telefone if cliente.telefone is not None else existente["telefone"]
    )

    if novo_telefone != existente["telefone"]:
        outro = db.obter_cliente_por_telefone(novo_telefone)
        if outro is not None and outro["id"] != cliente_id:
            raise HTTPException(409, "Já existe um cliente com esse telefone")

    db.atualizar_cliente(cliente_id, novo_nome, novo_telefone)
    return db.obter_cliente(cliente_id)


@app.delete("/clientes/{cliente_id}", status_code=204)
async def remover_cliente_endpoint(cliente_id: int):
    if db.obter_cliente(cliente_id) is None:
        raise HTTPException(404, "Cliente não encontrado")
    db.remover_cliente(cliente_id)
