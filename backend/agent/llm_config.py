"""统一 LLM 接入模块。

通过 LLM_PROVIDER 环境变量切换模型提供商，所有提供商返回统一的
(model, formatter) 元组，Agent 主逻辑无需关心具体实现。

支持的提供商:
  - deepseek  : DeepSeek API（默认，原生支持思维链）
  - openai    : OpenAI API
  - dashscope : 阿里云 DashScope（通义千问）
  - ollama    : 本地 Ollama

get_model_and_formatter() 返回流式 + 思维链主模型，供 Agent 推理使用；
get_memory_model() 返回非流式、非思维链模型，供长期记忆中间件做异步
检索（结构化输出在关闭思维链后更稳定，且不抢占主推理的流式连接）。
"""
import logging

from agentscope.credential import (
    DeepSeekCredential,
    DashScopeCredential,
    OpenAICredential,
    OllamaCredential,
)
from agentscope.formatter import (
    DeepSeekChatFormatter,
    DashScopeChatFormatter,
    OpenAIChatFormatter,
    OllamaChatFormatter,
)
from agentscope.model import (
    DeepSeekChatModel,
    DashScopeChatModel,
    OpenAIChatModel,
    OllamaChatModel,
)

from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_MAX_TOKENS,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    LLM_THINKING_ENABLE,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(_h)


def _build_model_and_formatter(
    *,
    stream: bool,
    thinking_enable: bool | None = None,
    temperature: float | None = None,
):
    """根据 LLM_PROVIDER 构造 (model, formatter) 元组。

    所有提供商共享同一份构造逻辑，仅 stream / thinking_enable / temperature 由调用方
    指定，避免主模型与记忆检索/萃取模型的代码重复。

    Args:
        stream (`bool`):
            是否启用流式输出。主推理用 True，记忆侧用 False。
        thinking_enable (`bool | None`):
            DeepSeek 思维链开关。None 表示沿用 LLM_THINKING_ENABLE；
            仅对 deepseek 提供商生效，其余提供商忽略此参数。
        temperature (`float | None`):
            采样温度覆盖。None 表示沿用 LLM_TEMPERATURE；记忆图谱萃取/检索
            需低温度（0.2）以保证结构化 JSON 输出稳定。

    Returns:
        tuple: (model_instance, formatter_instance)
    """
    if LLM_PROVIDER == "deepseek":
        credential = DeepSeekCredential(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        parameters = DeepSeekChatModel.Parameters(
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            thinking_enable=(
                LLM_THINKING_ENABLE if thinking_enable is None else thinking_enable
            ),
        )
        formatter = DeepSeekChatFormatter()
        model = DeepSeekChatModel(
            credential=credential,
            model=DEEPSEEK_MODEL,
            parameters=parameters,
            stream=stream,
            formatter=formatter,
        )

    elif LLM_PROVIDER == "openai":
        credential = OpenAICredential(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
        )
        parameters = OpenAIChatModel.Parameters(
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        formatter = OpenAIChatFormatter()
        model = OpenAIChatModel(
            credential=credential,
            model=OPENAI_MODEL,
            parameters=parameters,
            stream=stream,
            formatter=formatter,
        )

    elif LLM_PROVIDER == "dashscope":
        credential = DashScopeCredential(
            api_key=DASHSCOPE_API_KEY,
        )
        parameters = DashScopeChatModel.Parameters(
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        formatter = DashScopeChatFormatter()
        model = DashScopeChatModel(
            credential=credential,
            model=DASHSCOPE_MODEL,
            parameters=parameters,
            stream=stream,
            formatter=formatter,
        )

    elif LLM_PROVIDER == "ollama":
        credential = OllamaCredential(
            host=OLLAMA_BASE_URL,
        )
        parameters = OllamaChatModel.Parameters(
            temperature=temperature if temperature is not None else LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        formatter = OllamaChatFormatter()
        model = OllamaChatModel(
            credential=credential,
            model=OLLAMA_MODEL,
            parameters=parameters,
            stream=stream,
            formatter=formatter,
        )

    else:
        raise ValueError(
            f"不支持的 LLM_PROVIDER: {LLM_PROVIDER}。"
            f"支持: deepseek / openai / dashscope / ollama"
        )

    return model, formatter


def get_model_and_formatter():
    """主模型：流式 + 思维链，供 Agent 推理使用。

    在 AgentScope 2.0 中，formatter 会在模型构造函数中自动设置，
    此处返回 formatter 仅供日志记录参考。

    Returns:
        tuple: (model_instance, formatter_instance)
    """
    return _build_model_and_formatter(stream=True)


def get_memory_model():
    """长期记忆检索模型：非流式、非思维链。

    供 AgenticMemoryMiddleware 在每次 reply 前异步选择相关记忆文件。
    关闭流式以避免与主推理的流式连接相互阻塞；关闭思维链以保证
    generate_structured_output 的强制工具调用稳定生效。
    """
    model, _ = _build_model_and_formatter(stream=False, thinking_enable=False)
    return model


def get_memory_graph_chat_model():
    """记忆图谱萃取/检索 chat 模型：非流式、非思维链、低温度（0.2）。

    供 ``memory_graph`` 模块（图式长期记忆）做陈述/三元组萃取、去重判定、巩固与
    反思等结构化输出。低温度保证 JSON 输出稳定；非流式避免与主推理流式连接冲突。
    """
    model, _ = _build_model_and_formatter(
        stream=False, thinking_enable=False, temperature=0.2
    )
    return model
