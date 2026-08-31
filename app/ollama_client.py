import ast
import json
import re
from datetime import datetime
from typing import AsyncIterator, List, Optional

import httpx

OLLAMA_URL = "http://localhost:11434"
MODEL = "gemma2:2b"

SYSTEM_PROMPT = (
    "Você é um assistente de agendamento de serviços de barbearia/salão de beleza. "
    "Converse de forma amigável e conduza o cliente a informar: nome do cliente, "
    "telefone do cliente, serviço desejado (ex.: corte de cabelo, barba, manicure), "
    "data e horário. "
    "Quando tiver esses dados, confirme o agendamento. "
    "Ao final da sua resposta, sempre inclua um bloco JSON no formato "
    "{'cliente': ..., 'telefone': ..., 'servico': ..., 'data': ..., 'hora': ...} "
    "preenchendo apenas os campos que já conhece (null para os desconhecidos). "
    "Para telefone, extraia e formate no padrão (NN) NNNN-NNNN (ex: (11) 9999-8888). "
    "Sempre apresente datas no formato DD/MM/YYYY. "
    "Quando o cliente usar datas relativas (hoje, amanhã, depois de amanhã, "
    "próxima semana, próxima <dia da semana>), calcule a data exata a partir da "
    "data atual fornecida. Nunca use anos passados nem datas inventadas; se não "
    "tiver certeza da data, deixe o campo data como null para o backend calcular. "
    "Responda em português do Brasil."
)

_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _system_prompt() -> str:
    agora = datetime.now()
    return (
        f"Data e hora atuais: {agora.strftime('%d/%m/%Y %H:%M')}.\n"
        + SYSTEM_PROMPT
    )


def _extrair_json(texto: str) -> Optional[dict]:
    match = _JSON_RE.search(texto)
    if not match:
        return None
    blob = match.group(0)
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


class OllamaClient:
    def __init__(self, model: str = MODEL, base_url: str = OLLAMA_URL):
        self.model = model
        self.base_url = base_url

    async def check_health(self) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            return resp.status_code == 200

    async def _call(self, messages: List[dict]) -> tuple[str, Optional[dict]]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        reply = data.get("message", {}).get("content", "")
        dados = _extrair_json(reply)
        return reply, dados

    @staticmethod
    def _montar_messages(historico: List[dict], nova_mensagem: str) -> List[dict]:
        messages = [{"role": "system", "content": _system_prompt()}]
        messages.extend(historico)
        messages.append({"role": "user", "content": nova_mensagem})
        return messages

    async def chat(
        self, historico: List[dict], nova_mensagem: str
    ) -> tuple[str, Optional[dict]]:
        return await self._call(self._montar_messages(historico, nova_mensagem))

    async def stream_chat(
        self, historico: List[dict], nova_mensagem: str
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": self._montar_messages(historico, nova_mensagem),
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break

    async def reprocessar_rejeicao(
        self, historico: List[dict], rejeicao_texto: str
    ) -> tuple[str, Optional[dict]]:
        messages = [
            {
                "role": "system",
                "content": (
                    _system_prompt()
                    + "\n\nATENÇÃO: "
                    + rejeicao_texto
                    + " Informe o cliente educadamente sobre a indisponibilidade "
                    "e peça para ele escolher outro dia e/ou horário."
                ),
            }
        ]
        messages.extend(historico)
        return await self._call(messages)
