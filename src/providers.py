# src/providers.py
"""
Диспетчер нейросетей.

Три async-функции с ОДИНАКОВОЙ сигнатурой:

    async def ask_xxx(history: list[dict], api_key: str) -> str

где history — это user.history, список вида:
    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]

и словарь-диспетчер PROVIDERS в конце файла.

Использование (в handlers/chat.py):

    from src.providers import PROVIDERS

    key = user.get_key(user.current_provider)
    answer = await PROVIDERS[user.current_provider](user.history, key)

Новая нейронка = новая функция ask_xxx() + новая строка в PROVIDERS. Больше никуда лезть не нужно.

Все три SDK (google-generativeai, groq, cerebras_cloud_sdk) — синхронные,
поэтому вызовы обёрнуты в asyncio.to_thread, чтобы не блокировать event loop aiogram.
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
# Gemini
# ---------------------------------------------------------------------- #

def _ask_gemini_sync(history: list[dict], api_key: str) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    # google-generativeai использует роли "user" / "model", а не "assistant"
    contents = [
        {
            "role": "model" if msg["role"] == "assistant" else "user",
            "parts": [msg["content"]],
        }
        for msg in history
    ]

    response = model.generate_content(contents)
    return response.text


async def ask_gemini(history: list[dict], api_key: str) -> str:
    _require_key("gemini", api_key)
    try:
        return await asyncio.to_thread(_ask_gemini_sync, history, api_key)
    except Exception as e:
        raise ProviderError(f"Gemini: {e}") from e


# ---------------------------------------------------------------------- #
# Groq
# ---------------------------------------------------------------------- #

def _ask_groq_sync(history: list[dict], api_key: str) -> str:
    from groq import Groq

    client = Groq(api_key=api_key)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": msg["role"], "content": msg["content"]} for msg in history
    ]

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
    )
    return response.choices[0].message.content


async def ask_groq(history: list[dict], api_key: str) -> str:
    _require_key("groq", api_key)
    try:
        return await asyncio.to_thread(_ask_groq_sync, history, api_key)
    except Exception as e:
        raise ProviderError(f"Groq: {e}") from e


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
        model="llama-3.3-70b",
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
    "gemini": ask_gemini,
    "groq": ask_groq,
    "cerebras": ask_cerebras,
}