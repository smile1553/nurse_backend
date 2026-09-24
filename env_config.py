import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
ENV_EXAMPLE_PATH = BASE_DIR / ".env.example"

DEEPGRAM_API_KEY_TEMPLATE_VALUE = "PASTE_YOUR_DEEPGRAM_API_KEY_HERE"
OPENAI_API_KEY_TEMPLATE_VALUE = "PASTE_YOUR_OPENAI_API_KEY_HERE"

ENV_EXAMPLE_TEMPLATE = f"""DEEPGRAM_API_KEY={DEEPGRAM_API_KEY_TEMPLATE_VALUE}
OPENAI_API_KEY={OPENAI_API_KEY_TEMPLATE_VALUE}
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SEC=3.0
ASR_WARMUP_ON_START=0
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=zh
DEEPGRAM_SAMPLE_RATE=16000
DEEPGRAM_ENDPOINTING_MS=200
"""

_initialized = False


def ensure_env_example(path: Optional[Path] = None) -> bool:
    """Create the local environment template once without overwriting it."""
    target = path or ENV_EXAMPLE_PATH
    try:
        with target.open("x", encoding="utf-8") as file:
            file.write(ENV_EXAMPLE_TEMPLATE)
        print(f"[config] created environment template: {target}")
        return True
    except FileExistsError:
        return False
    except OSError as error:
        print(f"[config] failed to create environment template: {error}")
        return False


def initialize_environment() -> None:
    """Load deployment settings, with the ignored local template as fallback."""
    global _initialized
    if _initialized:
        return

    ensure_env_example()
    load_dotenv(dotenv_path=ENV_PATH, override=False)
    load_dotenv(dotenv_path=ENV_EXAMPLE_PATH, override=False)
    _initialized = True


def read_api_key(name: str, template_value: str) -> Optional[str]:
    value = (os.getenv(name) or "").strip()
    if not value or value == template_value:
        return None
    return value
