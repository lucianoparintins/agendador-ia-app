import ast
import json
from datetime import datetime
from typing import AsyncIterator, List, Optional

import httpx

OLLAMA_URL = "http://localhost:11434"
MODEL = "gemma2:2b"

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


def _system_prompt() -> str:
    agora = datetime.now()
    return (
        f"Data e hora atuais: {agora.strftime('%d/%m/%Y %H:%M')}.\n"
        + SYSTEM_PROMPT
    )


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
    def _montar_messages(historico: List[dict], nova_mensagem: str = "") -> List[dict]:
        messages = [{"role": "system", "content": _system_prompt()}]
        messages.extend(historico)
        if nova_mensagem:
            messages.append({"role": "user", "content": nova_mensagem})
        return messages

    async def chat(
        self, historico: List[dict], nova_mensagem: str = ""
    ) -> tuple[str, Optional[dict]]:
        return await self._call(self._montar_messages(historico, nova_mensagem))

    async def stream_chat(
        self, historico: List[dict], nova_mensagem: str = ""
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
