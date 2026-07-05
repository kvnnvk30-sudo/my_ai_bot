# src/providers.py
"""
Диспетчер нейросетей.

Async-функция с сигнатурой:

    async def ask_xxx(history: list[dict], api_key: str) -> str

где history — это user.history, список вида:
    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]

и словарь-диспетчер PROVIDERS в конце файла.

Использование (в handlers/chat.py):

    from src.providers import PROVIDERS

    key = user.get_key(user.current_provider)
    answer = await PROVIDERS[user.current_provider](user.history, key)

Новая нейронка = новая функция ask_xxx() + новая строка в PROVIDERS. Больше никуда лезть не нужно.

Сейчас в диспетчере остался только Cerebras (Gemini и Groq убраны:
Gemini режет по региону, Groq требует платёжку/недоступную регистрацию).
SDK cerebras_cloud_sdk — синхронный, поэтому вызов обёрнут в asyncio.to_thread,
чтобы не блокировать event loop aiogram.
"""

import asyncio

# ---------------------------------------------------------------------- #
# Системный промпт — общий для всех провайдеров, чтобы поведение бота
# не "плыло" при переключении нейронки
# ---------------------------------------------------------------------- #
SYSTEM_PROMPT = "Ты — полезный ассистент в Telegram-боте. Отвечай кратко и по делу."


class ProviderError(Exception):
    """
    Единая ошибка для всех провайдеров.

    Хэндлер chat.py ловит только этот один класс и не обязан знать
    про исключения конкретных SDK (google.api_core, groq.APIError, ...).
    """
    pass


def _require_key(provider: str, api_key: str | None) -> str:
    if not api_key:
        raise ProviderError(
            f"Ключ для «{provider}» не задан. Добавьте его в настройках (/settings)."
        )
    return api_key


# ---------------------------------------------------------------------- #
# Cerebras
# ---------------------------------------------------------------------- #

def _ask_cerebras_sync(history: list[dict], api_key: str) -> str:
    from cerebras.cloud.sdk import Cerebras

    client = Cerebras(api_key=api_key)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": msg["role"], "content": msg["content"]} for msg in history
    ]

    response = client.chat.completions.create(
        model="gpt-oss-120b",
        messages=messages,
    )
    return response.choices[0].message.content


async def ask_cerebras(history: list[dict], api_key: str) -> str:
    _require_key("cerebras", api_key)
    try:
        return await asyncio.to_thread(_ask_cerebras_sync, history, api_key)
    except Exception as e:
        raise ProviderError(f"Cerebras: {e}") from e


# ---------------------------------------------------------------------- #
# Диспетчер — единственное место, которое нужно трогать, добавляя провайдера.
# Ключи словаря ДОЛЖНЫ совпадать с models.SUPPORTED_PROVIDERS.
# ---------------------------------------------------------------------- #
PROVIDERS = {
    "cerebras": ask_cerebras,
}