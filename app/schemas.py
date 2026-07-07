from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    partial_success = "partial_success"
    success = "success"
    failed = "failed"

class HealthResponse(BaseModel):
    status: str = "ok"
    message: str = "Service is running"
    task_count: int = 0
    data_dir: str = ""
    vector_store_dir: str = ""


class DocumentBlock(BaseModel):
    # 文档结构块分类
    type: Literal["paragraph", "title", "table", "image"]
    content: str = ""
    # 文档结构块扩展信息：标题级别、表格 rows、图片路径、图片理解结果等
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetInfo(BaseModel):
    # 从文档中抽取出的外部资源：目前主要是 Word 内嵌图片
    file_name: str
    path: str
    mime_type: str


class DocumentChunk(BaseModel):
    # 面向知识库/RAG 入库的文本片段，由最终 blocks 稳定切分生成
    chunk_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityHint(BaseModel):
    # 后端生成的质量提示
    level: Literal["info", "warning", "error"] = "info"
    code: str
    message: str


class RuntimeMetricEvent(BaseModel):
    # 一次模型相关动作的轻量记录
    stage: str
    model_type: str
    model: str = ""
    status: Literal["success", "partial_success", "failed", "skipped"] = "success"
    duration_ms: int = 0
    fallback_used: bool = False
    input_items: int = 0
    output_items: int = 0
    error: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeMetrics(BaseModel):
    # 当前任务/文件的模型运行指标汇总（方便前端接收显示）
    model_call_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    fallback_count: int = 0
    total_duration_ms: int = 0
    by_stage: dict[str, dict[str, Any]] = Field(default_factory=dict)
    events: list[RuntimeMetricEvent] = Field(default_factory=list)


class TaskProgress(BaseModel):
    # 任务级解析进度；按文件和阶段估算
    total_files: int = 0
    processed_files: int = 0
    current_file: str = ""
    current_step: str = "等待解析"
    percent: int = 0


class FileResult(BaseModel):
    fileName: str
    fileType: str
    fileUrl: str = ""
    fileContent: str
    fileSource: str
    createDate: str
    status: Literal["success", "partial_success", "failed"] = "success"
    errorMessage: str = ""
    # 结构化文档块
    blocks: list[DocumentBlock] = Field(default_factory=list)
    # 结构化资源块(当前主要为图片)
    assets: list[AssetInfo] = Field(default_factory=list)
    # 面向 RAG/知识库入库的切分结果
    chunks: list[DocumentChunk] = Field(default_factory=list) 
    # 可解释质量提示
    qualityHints: list[QualityHint] = Field(default_factory=list)
    # 智能体增强结果：作者、发布时间、机构、主题等元数据
    metadata: dict[str, Any] = Field(default_factory=dict)
    # LangGraph 工作流节点级处理摘要
    agentTrace: list[dict[str, Any]] = Field(default_factory=list)
    # 模型调用、降级、失败和耗时的结构化指标
    runtimeMetrics: RuntimeMetrics = Field(default_factory=RuntimeMetrics)


class AnalyzeAccepted(BaseModel):
    code: int = 202
    message: str
    task_id: str
    status: TaskStatus


class TaskInfo(BaseModel):
    task_id: str
    status: TaskStatus
    message: str = ""
    created_at: datetime
    updated_at: datetime
    file_count: int = 0
    progress: TaskProgress = Field(default_factory=TaskProgress)
    runtimeMetrics: RuntimeMetrics = Field(default_factory=RuntimeMetrics)


class TaskListItem(BaseModel):
    task_id: str
    status: TaskStatus
    message: str = ""
    created_at: datetime
    updated_at: datetime
    file_count: int = 0
    progress: TaskProgress = Field(default_factory=TaskProgress)
    file_names: list[str] = Field(default_factory=list)


class TaskListResponse(BaseModel):
    total: int = 0
    items: list[TaskListItem] = Field(default_factory=list)


class TaskDeleteResponse(BaseModel):
    task_id: str
    deleted: bool = True
    index_deleted: bool = False
    message: str = ""


class TaskResult(BaseModel):
    code: int = 200
    message: str
    task_id: str
    status: TaskStatus
    progress: TaskProgress = Field(default_factory=TaskProgress)
    data: list[FileResult] = Field(default_factory=list)
    runtimeMetrics: RuntimeMetrics = Field(default_factory=RuntimeMetrics)


class BlockCorrectionRequest(BaseModel):
    # 前端提交人工修正后的结构块；后端据此重新生成正文和知识库切片。
    blocks: list[DocumentBlock]


class ChunkCorrectionRequest(BaseModel):
    # 前端提交入库前修正后的知识库切片；不反向修改 blocks/fileContent。
    chunks: list[DocumentChunk]


class KnowledgeIndexRequest(BaseModel):
    file_indices: list[int] | None = None
    rebuild: bool = True


class KnowledgeIndexStatus(BaseModel):
    task_id: str
    collection_name: str
    indexed: bool = False
    indexed_count: int = 0
    skipped_count: int = 0
    status: Literal["not_built", "built", "failed"] = "not_built"
    message: str = ""
    last_built_at: str = ""


class KnowledgeAskRequest(BaseModel):
    question: str
    top_k: int = 5


class KnowledgeSource(BaseModel):
    content: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeAskResponse(BaseModel):
    answer: str
    sources: list[KnowledgeSource] = Field(default_factory=list)
    retrievalTrace: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    code: int
    message: str
    detail: Any | None = None
