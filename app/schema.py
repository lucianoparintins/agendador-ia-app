from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    sessao_id: Optional[int] = None
    mensagem: str


class Agendamento(BaseModel):
    cliente: Optional[str] = None
    servico: Optional[str] = None
    data: Optional[str] = None
    hora: Optional[str] = None
    status: Optional[str] = None


class Validacao(BaseModel):
    valido: bool
    motivo: Optional[str] = None


class ChatResponse(BaseModel):
    sessao_id: int
    reply: str
    agendamento: Optional[Agendamento] = None
    validacao: Optional[Validacao] = None


class Sessao(BaseModel):
    id: int
    titulo: Optional[str] = None
    criado_em: str


class Mensagem(BaseModel):
    id: int
    sessao_id: int
    role: str
    conteudo: str
    criado_em: str


class AgendamentoRecord(BaseModel):
    id: int
    sessao_id: int
    cliente: Optional[str] = None
    servico: Optional[str] = None
    data: Optional[str] = None
    hora: Optional[str] = None
    status: str
    criado_em: str
