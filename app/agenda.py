from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re
from typing import Optional

from dateutil import parser as dateutil_parser

from . import db

EXPEDIENTE = {
    0: (9, 18),  # seg
    1: (9, 18),  # ter
    2: (9, 18),  # qua
    3: (9, 18),  # qui
    4: (9, 18),  # sex
    5: (9, 13),  # sab
}
DURACAO_MIN = 60


@dataclass
class ValidacaoResult:
    valido: bool
    motivo: Optional[str]
    data: Optional[date] = None
    hora: Optional[time] = None


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_data(valor: str) -> Optional[date]:
    if not valor:
        return None
    texto = str(valor).strip()
    try:
        if _ISO_DATE_RE.match(texto):
            return dateutil_parser.parse(texto).date()
        return dateutil_parser.parse(texto, dayfirst=True).date()
    except (ValueError, TypeError, OverflowError):
        return None


def formatar_data(valor: str) -> Optional[str]:
    d = parse_data(valor)
    if d is None:
        return valor
    return d.strftime("%d/%m/%Y")


DIAS_SEMANA = {
    "segunda": 0,
    "segunda-feira": 0,
    "terca": 1,
    "terça": 1,
    "terca-feira": 1,
    "terça-feira": 1,
    "quarta": 2,
    "quarta-feira": 2,
    "quinta": 3,
    "quinta-feira": 3,
    "sexta": 4,
    "sexta-feira": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def resolver_data_relativa(valor) -> Optional[str]:
    if not valor:
        return valor
    texto = "_".join(str(valor).strip().lower().split())

    if texto in ("hoje",):
        base = date.today()
    elif texto in ("amanha", "amanhã", "dia_seguinte", "próximo_dia", "proximo_dia"):
        base = date.today() + timedelta(days=1)
    elif texto in (
        "depois_de_amanha",
        "depois_de_amanhã",
        "passado_amanha",
        "passado_amanhã",
    ):
        base = date.today() + timedelta(days=2)
    elif texto in ("ontem",):
        base = date.today() - timedelta(days=1)
    elif texto.startswith("proxima_") or texto.startswith("próxima_") or texto.startswith("proximo_") or texto.startswith("próximo_"):
        palavra = texto.split("_", 1)[1]
        alvo = DIAS_SEMANA.get(palavra)
        if alvo is None:
            return valor
        hoje = date.today().weekday()
        delta = (alvo - hoje) % 7
        if delta == 0:
            delta = 7
        base = date.today() + timedelta(days=delta)
    else:
        return valor

    return base.strftime("%d/%m/%Y")


JANELA_DIAS_FUTURO = 90


def data_plausivel(valor) -> bool:
    if not valor:
        return False
    d = parse_data(valor)
    if d is None:
        return False
    hoje = date.today()
    return hoje <= d <= hoje + timedelta(days=JANELA_DIAS_FUTURO)


def parse_hora(valor: str) -> Optional[time]:
    if not valor:
        return None
    texto = str(valor).strip()
    if "." in texto:
        texto = texto.split(".")[0]
    try:
        return dateutil_parser.parse(texto).time()
    except (ValueError, TypeError, OverflowError):
        return None


def _in_expediente(d: date, h: time) -> bool:
    janela = EXPEDIENTE.get(d.weekday())
    if janela is None:
        return False
    abertura, fechamento = janela
    inicio = time(abertura, 0)
    fim = time(fechamento, 0)
    fim_atendimento = (datetime.combine(date.min, h) + timedelta(minutes=DURACAO_MIN)).time()
    return inicio <= h and fim_atendimento <= fim


def _sobrepoe(h1: time, d1: timedelta, h2: time, d2: timedelta) -> bool:
    t1 = datetime.combine(date.min, h1)
    t2 = datetime.combine(date.min, h2)
    fim1 = t1 + d1
    fim2 = t2 + d2
    return t1 < fim2 and t2 < fim1


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
