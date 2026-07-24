import asyncio
import sys
import time
import types
from unittest.mock import MagicMock, patch

import pytest

from src.providers import SYSTEM_PROMPT, ProviderError, ask_cerebras

pytestmark = pytest.mark.asyncio

# providers.py делает `from cerebras.cloud.sdk import Cerebras` ВНУТРИ функции
# _ask_cerebras_sync, а не на уровне модуля. Поэтому patch("src.providers.Cerebras")
# не сработает — такого атрибута в модуле нет. Патчим по месту реального импорта.
CEREBRAS_PATH = "cerebras.cloud.sdk.Cerebras"


def _real_sdk_installed() -> bool:
    try:
        import importlib
        importlib.import_module("cerebras.cloud.sdk")
        return True
    except ImportError:
        return False


@pytest.fixture(autouse=True)
def ensure_cerebras_sdk_importable():
    """
    Если пакет cerebras-cloud-sdk не установлен в тестовом окружении,
    patch("cerebras.cloud.sdk.Cerebras") упадёт с ModuleNotFoundError
    ещё до подмены. Подставляем фейковые модули в sys.modules, чтобы
    `from cerebras.cloud.sdk import Cerebras` внутри providers.py
    отрабатывал независимо от того, установлен ли настоящий SDK.
    """
    if _real_sdk_installed():
        yield
        return

    cerebras_pkg = types.ModuleType("cerebras")
    cloud_pkg = types.ModuleType("cerebras.cloud")
    sdk_mod = types.ModuleType("cerebras.cloud.sdk")
    sdk_mod.Cerebras = MagicMock(name="Cerebras")
    cloud_pkg.sdk = sdk_mod
    cerebras_pkg.cloud = cloud_pkg

    sys.modules["cerebras"] = cerebras_pkg
    sys.modules["cerebras.cloud"] = cloud_pkg
    sys.modules["cerebras.cloud.sdk"] = sdk_mod
    try:
        yield
    finally:
        for mod in ("cerebras", "cerebras.cloud", "cerebras.cloud.sdk"):
            sys.modules.pop(mod, None)


def _fake_response(content):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


# ------------------------------------------------------------------ #
# PRV-01: системный промпт + порядок сообщений
# ------------------------------------------------------------------ #

async def test_prv01_calls_sdk_with_system_prompt_and_history():
    history = [{"role": "user", "content": "Привет"}]

    with patch(CEREBRAS_PATH) as mock_cerebras_cls:
        mock_client = mock_cerebras_cls.return_value
        mock_client.chat.completions.create.return_value = _fake_response("Привет!")

        result = await ask_cerebras(history, "valid_key_123")

    assert result == "Привет!"
    mock_cerebras_cls.assert_called_once_with(api_key="valid_key_123")
    _, kwargs = mock_client.chat.completions.create.call_args
    assert kwargs["model"] == "gpt-oss-120b"
    assert kwargs["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert kwargs["messages"][1:] == history


# ------------------------------------------------------------------ #
# PRV-02 / PRV-03: _require_key до похода в SDK
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("bad_key", [None, ""])
async def test_prv02_03_missing_key_raises_before_sdk_call(bad_key):
    # match намеренно без кириллицы (ASCII-часть сообщения) — сообщение
    # об ошибке на русском, а "cerebras" — literal-имя провайдера в тексте.
    with patch(CEREBRAS_PATH) as mock_cerebras_cls:
        with pytest.raises(ProviderError, match="cerebras"):
            await ask_cerebras([], bad_key)
        mock_cerebras_cls.assert_not_called()


# ------------------------------------------------------------------ #
# PRV-04..07: обёртка ошибок SDK в ProviderError
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "exc,expected_msg",
    [
        (TimeoutError("connection timed out"), "connection timed out"),
        (Exception("401 Unauthorized"), "401 Unauthorized"),
        (Exception("429 Too Many Requests"), "429 Too Many Requests"),
        (Exception("500 Internal Server Error"), "500 Internal Server Error"),
    ],
)
async def test_prv04_07_sdk_errors_wrapped(exc, expected_msg):
    with patch(CEREBRAS_PATH) as mock_cerebras_cls:
        mock_cerebras_cls.return_value.chat.completions.create.side_effect = exc
        with pytest.raises(ProviderError, match=expected_msg):
            await ask_cerebras([{"role": "user", "content": "?"}], "valid_key")


# ------------------------------------------------------------------ #
# PRV-08 / PRV-09: неожиданная структура ответа SDK
# ------------------------------------------------------------------ #

async def test_prv08_empty_choices_raises_provider_error():
    resp = MagicMock()
    resp.choices = []
    with patch(CEREBRAS_PATH) as mock_cerebras_cls:
        mock_cerebras_cls.return_value.chat.completions.create.return_value = resp
        with pytest.raises(ProviderError, match="Cerebras:"):
            await ask_cerebras([{"role": "user", "content": "?"}], "valid_key")


async def test_prv09_content_none_returns_none_not_raises():
    resp = _fake_response(None)
    with patch(CEREBRAS_PATH) as mock_cerebras_cls:
        mock_cerebras_cls.return_value.chat.completions.create.return_value = resp
        result = await ask_cerebras([{"role": "user", "content": "?"}], "valid_key")
    # фиксируем текущее поведение как риск: функция не падает, просто отдаёт None дальше
    assert result is None


# ------------------------------------------------------------------ #
# PRV-10: history передаётся как есть, без обрезки на стороне providers.py
# ------------------------------------------------------------------ #

async def test_prv10_full_history_passed_through_unchanged():
    history = [{"role": "user", "content": f"msg-{i}"} for i in range(25)]
    with patch(CEREBRAS_PATH) as mock_cerebras_cls:
        mock_cerebras_cls.return_value.chat.completions.create.return_value = _fake_response("ok")
        await ask_cerebras(history, "valid_key")

    _, kwargs = mock_cerebras_cls.return_value.chat.completions.create.call_args
    assert kwargs["messages"][1:] == history
    assert len(kwargs["messages"]) == 26  # system + все 25


# ------------------------------------------------------------------ #
# PRV-11: asyncio.to_thread не блокирует event loop
# ------------------------------------------------------------------ #

async def test_prv11_to_thread_runs_calls_concurrently():
    def slow_create(*args, **kwargs):
        time.sleep(2)
        return _fake_response("ok")

    with patch(CEREBRAS_PATH) as mock_cerebras_cls:
        mock_cerebras_cls.return_value.chat.completions.create.side_effect = slow_create

        start = time.monotonic()
        await asyncio.gather(
            ask_cerebras([{"role": "user", "content": "1"}], "key1"),
            ask_cerebras([{"role": "user", "content": "2"}], "key2"),
        )
        elapsed = time.monotonic() - start

    assert elapsed < 3.5, "вызовы выполнились последовательно, to_thread не спасает от блокировки"