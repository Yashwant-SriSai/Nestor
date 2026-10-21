# groq_client.py
# Groq answers very fast, which matters for chat (and later for the agent, which
# may call the model several times per question). get_chat_model() returns a
# LangChain model object, because the Phase 3 agent needs exactly that.

from langchain_groq import ChatGroq

from backend import config
from backend.errors import LLMError
from backend.llm.retry import with_retry


def get_chat_model() -> ChatGroq:
    if not config.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is missing. Add it to your .env file and restart the backend.", 500)
    # max_retries=0 because OUR with_retry handles waiting and retrying;
    # two retry layers would stack into very long waits.
    return ChatGroq(model=config.GROQ_MODEL, api_key=config.GROQ_API_KEY,
                    temperature=0.1, max_retries=0, timeout=60)


def chat(messages: list) -> str:
    """messages = [("system", "..."), ("user", "..."), ("assistant", "..."), ...]"""
    model = get_chat_model()
    result = with_retry(lambda: model.invoke(messages), "Groq")
    content = result.content
    return content if isinstance(content, str) else str(content)