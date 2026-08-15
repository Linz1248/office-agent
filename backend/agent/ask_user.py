"""ask_user：agentscope 外部执行工具（human-in-the-loop）。

当智能体需要用户补全信息（如检索前的搜索关键词、期望返回数量）时调用本工具。
调用后框架发出 `RequireExternalExecutionEvent` 并暂停 `reply`/`reply_stream`，
由 /chat 捕获该事件、向前端下发 `clarify` 帧、等待用户作答，再通过
`ExternalExecutionResultEvent` 恢复推理。工具本身不实现执行逻辑（is_external_tool=True）。
"""
from __future__ import annotations

from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import ToolBase


class AskUser(ToolBase):
    """向用户提问以补全检索/任务所需信息，暂停等待用户作答。"""

    name = "ask_user"
    description = (
        "向用户提问以补全完成任务所需的关键信息（例如图像/音频检索前的搜索关键词、"
        "期望返回多少条结果）。调用后流程会暂停，待用户作答后继续。"
        "仅当用户尚未明确这些信息时才调用；用户已提供时不要调用。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "向用户提出的问题，应明确说明需要用户补充什么信息。",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选的快捷答案列表（如 ['3 条','5 条','10 条']），"
                "用户可任选其一或自行输入。无明确选项时留空。",
            },
        },
        "required": ["question"],
    }
    is_external_tool = True  # 执行委派给外部（/chat 收集用户作答），不实现 call
    # 以下两个属性在 ToolBase 中无默认值，子类必须显式设置（否则 _batch_tool_calls
    # 读取时会 AttributeError）。ask_user 仅向用户提问并暂停，无副作用、不修改共享状态。
    is_concurrency_safe = True
    is_read_only = True

    async def check_permissions(self, tool_input: dict, context) -> PermissionDecision:
        # 追问本身无副作用；放行让其进入外部执行暂停。
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="ask_user 仅向用户提问，无副作用。",
        )
