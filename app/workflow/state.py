from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    # 文件与任务上下文
    task_id: str
    file_path: str
    file_type: str
    server_source: str

    # Parser Tool Node 产物
    content: str
    blocks: list[dict[str, Any]]
    assets: list[dict[str, str]]

    # Agent Node 产物
    metadata: dict[str, Any]
    chunks: list[dict[str, Any]]
    errors: list[str]
    status: str
    agent_trace: list[dict[str, Any]]
    runtime_metrics: dict[str, Any]
