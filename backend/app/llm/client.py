from app.llm.gateway import get_llm_gateway
from app.llm.providers.deepseek import DeepSeekProvider

DeepSeekClient = DeepSeekProvider  # compatibility alias
get_llm_client = get_llm_gateway  # backward-compatible DI name
