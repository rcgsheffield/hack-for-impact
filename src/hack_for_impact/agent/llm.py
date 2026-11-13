#%%
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

OLLAMA_URL = "http://spark12.local:11434"

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

def build_agent(model_name: str = "gemma4:e2b", model_provider: str = "ollama", base_url: str = OLLAMA_URL, api_key: str = "not-needed"):
    """
    Build a LangChain agent
    """
    model = init_chat_model(
        model_name,
        model_provider=model_provider,
        base_url=base_url,
        api_key=api_key,
    )

    agent = create_agent(
        model=model,
        tools=[],
    )
    return agent
# %%
