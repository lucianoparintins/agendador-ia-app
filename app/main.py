from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from . import agenda, db
from .ollama_client import OllamaClient
from .schema import Agendamento, ChatRequest, ChatResponse, Validacao

ollama = OllamaClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Agendador IA", lifespan=lifespan)


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
    ]

    reply, dados = await ollama.chat(historico(), req.mensagem)

    agendamento = None
    validacao: Validacao | None = None

    if dados:
        agendamento = Agendamento(**{
            "cliente": dados.get("cliente"),
            "servico": dados.get("servico"),
            "data": dados.get("data"),
            "hora": dados.get("hora"),
        })

        resultado = agenda.validar_agendamento(dados.get("data"), dados.get("hora"))

        if resultado.valido:
            agendamento.status = "confirmado"
            validacao = Validacao(valido=True, motivo=None)
            db.salvar_agendamento(
                sessao_id,
                dados.get("cliente"),
                dados.get("servico"),
                dados.get("data"),
                dados.get("hora"),
                status="confirmado",
            )
        elif resultado.motivo == "insuficiente":
            agendamento.status = "rascunho"
            validacao = Validacao(valido=False, motivo=resultado.motivo)
            if any(dados.get(k) for k in ("cliente", "servico", "data", "hora")):
                db.salvar_agendamento(
                    sessao_id,
                    dados.get("cliente"),
                    dados.get("servico"),
                    dados.get("data"),
                    dados.get("hora"),
                    status="rascunho",
                )
        else:
            agendamento.status = "rejeitado"
            validacao = Validacao(valido=False, motivo=resultado.motivo)
            motivo_texto = MOTIVO_TEXTO.get(
                resultado.motivo, "o horário não está disponível"
            )
            rejeicao_texto = (
                f"O cliente pediu para agendar em {dados.get('data')} às "
                f"{dados.get('hora')}, mas isso não é possível porque "
                f"{motivo_texto}."
            )
            db.salvar_agendamento(
                sessao_id,
                dados.get("cliente"),
                dados.get("servico"),
                dados.get("data"),
                dados.get("hora"),
                status="rejeitado",
            )
            reply, _ = await ollama.reprocessar_rejeicao(historico(), rejeicao_texto)
            db.adicionar_mensagem(sessao_id, "assistant", reply)

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
