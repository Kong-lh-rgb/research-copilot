import logging
from app.llm.wrapper import call_llm
from app.graph.state import AgentState
from app.llm.prompts import CONTROLLER_PROMPTS

logger = logging.getLogger(__name__)

async def simple_chat_node(state: AgentState) -> dict:
    user_input = state.get("user_input", "")
    res = await call_llm(messages=[{"role": "user", "content": user_input}])
    content = res.get("content", "")
    logger.info(f"[SimpleChat] 回复: {content}")
    return {"final_report": content}
