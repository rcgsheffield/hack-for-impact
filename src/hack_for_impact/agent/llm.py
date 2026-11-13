#%%
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from app.config import OLLAMA_URL



model = init_chat_model(
    "gemma4:e2b",
    model_provider="ollama",            # use the OpenAI-compatible client
    base_url="http://spark12.local:11434",                 # or os.environ["OLLAMA_URL"],
    api_key="not-needed",               # or os.environ["..."]
)

agent = create_agent(
    model=model,
    tools=[],
)
# %%
