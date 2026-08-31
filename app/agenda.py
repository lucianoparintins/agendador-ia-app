from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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


def parse_data(valor: str) -> Optional[date]:
    if not valor:
        return None
    try:
        return dateutil_parser.parse(str(valor)).date()
    except (ValueError, TypeError, OverflowError):
        return None


def formatar_data(valor: str) -> Optional[str]:
    d = parse_data(valor)
    if d is None:
        return valor
    return d.strftime("%d/%m/%Y")


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
    return inicio <= h < fim


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

    agora = datetime.now()
    horario = datetime.combine(d, h)
    if horario <= agora:
        return ValidacaoResult(valido=False, motivo="no_passado", data=d, hora=h)

    if not _in_expediente(d, h):
        return ValidacaoResult(valido=False, motivo="fora_expediente", data=d, hora=h)

    inicio = h
    fim = (datetime.combine(date.min, h) + timedelta(minutes=DURACAO_MIN)).time()
    if db.verificar_conflito(d.isoformat(), inicio.isoformat(), fim.isoformat()):
        return ValidacaoResult(valido=False, motivo="conflito", data=d, hora=h)

    return ValidacaoResult(valido=True, motivo=None, data=d, hora=h)
