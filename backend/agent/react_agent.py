# react_agent.py
# One search is often not enough to answer "how does login work?". A ReAct
# agent THINKS, calls a tool, LOOKS at the result, and repeats, like a
# developer investigating. LangGraph's prebuilt agent runs that loop; we add
# the step cap and the citation check.
#
# NOTE: LangChain's newer docs describe `langchain.agents.create_agent` as the
# successor of `create_react_agent`. We use the prebuilt LangGraph agent as
# planned; check the LangGraph docs if a future version removes it.

from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from backend import config
from backend.agent.tools import build_tools
from backend.explain_mode import NOT_FOUND, check_citations
from backend.llm import groq_client, prompts
from backend.llm.retry import with_retry


def _text_of(message) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def ask(repo, question: str, history: list, level: str) -> dict:
    system = prompts.agent_system_prompt(level, repo.url, config.AGENT_MAX_STEPS)
    messages = [(m["role"], m["content"]) for m in history[-config.CHAT_HISTORY_MESSAGES:]]
    messages.append(("user", question))

    def run():
        agent = create_react_agent(groq_client.get_chat_model(), build_tools(repo, level), prompt=system)
        try:
            # One "step" = one model call + one tool call = 2 graph steps,
            # so 8 steps means a recursion limit of 17 (the +1 is the final answer).
            return agent.invoke({"messages": messages},
                                {"recursion_limit": 2 * config.AGENT_MAX_STEPS + 1})
        except GraphRecursionError:
            return None  # the agent used all its steps without reaching an answer

    result = with_retry(run, "Groq")  # waits and retries on rate limits
    if result is None:
        return {"answer": (f"I used all {config.AGENT_MAX_STEPS} search steps without a confident answer. "
                           "Try a more specific question (for example, name a file or function)."),
                "steps": []}

    # A readable trace of what the agent did, shown to the user.
    steps = []
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            args = ", ".join(f"{key}={value!r}" for key, value in call["args"].items())
            steps.append(f"{call['name']}({args})")

    answer = _text_of(result["messages"][-1]).strip() or NOT_FOUND
    return {"answer": check_citations(answer, repo), "steps": steps}