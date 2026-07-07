# 总体说明

> Copyright (c) 2026 yangyh03. All rights reserved.
>
> 本项目源码可公开阅读、学习和参考，但禁止移除署名、包装成他人原创项目或未经许可进行商业化/二次发布。详见 `LICENSE`。

## 系统介绍

DocAgent 是一个基于 FastAPI 和 LangGraph 的多模态文档解析与行业知识库构建系统。系统可以把 Word、PDF、HTML、浏览器保存网页包和图片统一解析成结构化结果，再生成面向知识库入库的切片，支持人工校正、构建本地 Chroma 向量索引和任务级问答。

它更准确的定位是：**基于 Agent Workflow 的多模态文档解析、入库前治理与行业知识库构建系统**。

## 阅读建议

- 如果只是使用系统，优先阅读“前端使用流程”和“API 使用流程”。
- 如果想理解实现，阅读“架构说明”和“原理介绍”。
- 如果准备答辩或面试，阅读“面试与设计问答”。

## 当前能力

- **多格式上传解析**：支持 DOCX、PDF、HTML/HTM、浏览器保存网页 ZIP 和常见位图图片。
- **统一结构输出**：输出 `blocks`、`fileContent`、`assets`、`chunks`、`metadata`、`qualityHints`等结构块。
- **工作流编排**：通过 LangGraph 串联路由、解析、元信息抽取、图片理解、结果标准化和 RAG 切片。
- **图片理解**：图片 block 可以交给 VLM 生成描述、提取图片文字和判断图片作用。
- **扫描 PDF 兜底**：无文本层 PDF 页面会渲染为图片，并作为 OCR 候选交给 Vision Agent。
- **人工校正**：前端可编辑结构块和知识库切片，可控制 chunk 是否参与入库。
- **本地知识库**：使用 Chroma 持久化向量库，每个任务一个 collection。
- **知识库问答**：构建索引后可围绕当前任务文档提问；未配置 QA 模型时可返回检索片段。
- **可观测性**：通过质量提示、执行轨迹和运行指标解释解析质量、降级原因和模型调用情况。

## 前端使用流程

1. 打开 `http://127.0.0.1:8001/`。
2. 在左侧选择一个或多个文件。
3. 填写来源系统，默认可保持 `my_source`。
4. 点击“上传并解析”。
5. 等待任务状态从 pending/running 进入完成状态。
6. 在文件列表中切换查看不同文件。
7. 查看概览、正文、结构块、知识库切片、知识库问答、运行指标、执行轨迹和原始 JSON。
8. 如需修正结果，可在结构块或知识库切片中进入编辑模式并保存。
9. 如需问答，先点击“构建/重建索引”，再在知识库问答区域提问。
10. 如需说明文档，可点击右上角“系统说明”进入 Markdown 说明页。

## 适用范围与边界

系统当前版本适合通用办公文档和网页资料的“解析、治理、入库、问答”闭环，也可直接导出为后续工作提供帮助。适用于下列情况：

- 技术文档
- 项目说明书
- 工作报告
- 教程网页
- 普通 PDF、Word 图文混排文档

系统会先把内容解析成 `title / paragraph / table / image` blocks，再生成可人工校正的 chunks，最后可写入任务级 Chroma 向量库做问答。

需要注意的是：法规、合同、招投标文件、学术论文这类强领域结构文档，通常有章节、条款、目录、附件、脚注、复杂表格等领域结构。当前系统可以做基础解析和入库前治理，但如果要获得高质量 chunks，需要增加领域规则或专用 parser，例如法规条文识别、目录过滤、合同条款层级恢复、论文图表/参考文献处理等。

# 架构说明

## 分层结构及重点产物

```text
FastAPI API
  -> Storage Service （保存文件，生成 fileUrl）
  -> Task Service （生成 task_id/status/message）
  -> LangGraph Workflow 
      -> Router Node （file_type）
          -> Parser Tool Node （content/blocks/assets/parser metadata）
          -> Metadata Extraction Agent （author/posted_time/organization/topic/summary）
          -> Vision Understanding Agent （image description/extracted_text/image_role/confidence）
          -> Result Normalizer Agent （final fileContent/normalized blocks）
          -> RAG Chunking Agent （chunks）
  -> Task Result JSON （封装 FileResult）
```

## 各层职责

将系统拆成 API、Service、Workflow、Parser、LLM 和 Knowledge 六层：

- **API 层**：负责接收上传文件、返回 `task_id`、查询任务状态和解析结果，该层并不关心具体实现。
- **Service 层**：负责保存文件、创建任务、运行后台解析、保存最终结果。
- **Workflow 层**：负责把解析流程编排成 LangGraph 的 Agent 工作流节点，并通过 `agentTrace` 记录每个节点的状态、耗时、fallback 和错误信息，最后生成可人工校正的 chunks。
- **Parser 层**：负责确定性解析与流程化处理，稳定、可验证、低成本，例如 Word/HTML/PDF 的结构块分析和 PDF 扫描页候选标记。
- **LLM 层**：负责调用用户配置的模型，用于元信息抽取、图片语义描述和图片文字提取等工作。
- **Knowledge 层**：负责把用户确认启用的 `chunks` 写入任务级 Chroma collection，再通过向量检索和 LLM 生成基于来源的回答，避免未校正内容自动入库。

## Workflow 节点简述

- **Router Node**：根据文件扩展名做确定性路由。（Node）
- **Parser Tool Node**：根据文件类型调用对应 parser。（Node）
- **Metadata Extraction Agent**：从压缩后的文档上下文中抽取：作者、发布时间、机构、主题、摘要。（Agent）
- **Vision Understanding Agent**：逐张处理 image block，读取图片并结合图片前后文本调用VLM。最终返回图片语义描述 `description` 和图片中可见文字 `extracted_text`。（Agent）输出规则：

```text
Word/HTML 图片：description 进入 fileContent，extracted_text 只放 metadata
PDF 普通插图：description 进入 fileContent，extracted_text 只放 metadata
PDF 扫描页：extracted_text 额外插入 paragraph，description 仍进入 image block
```

- **Result Normalizer Agent**：统一最终输出字段，确保 API 结果稳定。
- **RAG Chunking Agent**：把最终 `blocks` 转成面向知识库/RAG 入库的 `chunks`。
- **agentTrace**：脱离黑盒函数调用，让系统成为明确节点边界、耗时记录、fallback 记录和错误追踪的 Agent Workflow。

# 接口说明

## 主要 API 接口

| 方法      | 路径                                                                | 说明                   |
| --------- | ------------------------------------------------------------------- | ---------------------- |
| `POST`  | `/api/documents/analyze`                                          | 上传文件并创建解析任务 |
| `GET`   | `/api/documents/tasks`                                            | 查询最近任务列表       |
| `GET`   | [`/api/documents/tasks/{task_id}](#任务状态字段)`                                  | 查询任务状态           |
| `DELETE` | `/api/documents/tasks/{task_id}`                                | 删除历史任务和索引     |
| `GET`   | [`/api/documents/tasks/{task_id}/result`](#任务结果字段)           | 获取任务结果           |
| `PATCH` | `/api/documents/tasks/{task_id}/result/files/{file_index}/blocks` | 保存结构块校正         |
| `PATCH` | `/api/documents/tasks/{task_id}/result/files/{file_index}/chunks` | 保存知识库切片校正     |
| `GET`   | [`/api/documents/tasks/{task_id}/result/files/{file_index}/export`](#导出接口字段) | 导出 blocks/chunks     |
| `POST`  | [`/api/documents/tasks/{task_id}/knowledge/index`](#知识库索引字段)                  | 构建或重建知识库索引   |
| `GET`   | [`/api/documents/tasks/{task_id}/knowledge/index`](#知识库索引字段)                  | 查询索引状态           |
| `POST`  | [`/api/documents/tasks/{task_id}/knowledge/ask`](#知识库问答字段)                    | 知识库问答             |
| `GET`   | [`/api/documents/tasks/{task_id}/assets/{file_name}`](#任务资源字段)               | 访问任务图片资源       |

## 接口字段说明

### 任务状态字段

```text
GET /api/documents/tasks/{task_id}
```

返回结构：

```json
{
  "progress": {
    "total_files": 1,
    "processed_files": 1,
    "current_file": "",
    "current_step": "准备解析",
    "percent": 100
  }
}
```

字段描述：

| 字段 | 类型 | 含义 | 常见取值 | 来源 |
| ---- | ---- | ---- | -------- | ---- |
| `total_files` | number | 本任务总文件数 | 正整数 | 上传时的文件数量 |
| `processed_files` | number | 已处理的文件数 | `0` 到 `total_files` | `document_service` 每处理完一个文件后更新 |
| `current_file` | string | 当前正在处理或刚处理完的文件名 | `demo.pdf` | `document_service` |
| `current_step` | string | 当前阶段文案 | `准备解析`, `正在解析第 1/2 个文件`, `解析完成` | `document_service` |
| `percent` | number | 任务进度百分比 | `0` 到 `100` | 按已处理文件数估算 |


### 任务结果字段

```text
GET /api/documents/tasks/{task_id}/result
```

返回结构：

```json
{
  "code": 200,
  "message": "解析完成",
  "task_id": "...",
  "status": "success",
  "progress": {
    "total_files": 1,
    "processed_files": 1,
    "current_file": "",
    "current_step": "解析完成",
    "percent": 100
  },
  "runtimeMetrics": {},
  "data": [
    {
      "fileName": "...",
      "fileType": "DOCX",
      "fileUrl": "data/tasks/{task_id}/xxx.docx",
      "fileContent": "...",
      "fileSource": "my_source",
      "createDate":"2026-07-01 12:00:00",
      "status": "success",
      "errorMessage": "",
      "blocks": [],
      "assets": [],
      "chunks": [],
      "qualityHints": [],
      "metadata": {},
      "agentTrace": [],
      "runtimeMetrics": {}
    }
  ]
}
```

#### A.顶层任务字段描述

| 字段               | 类型   | 含义                           | 常见取值                                                               | 来源                                          |
| ------------------ | ------ | ------------------------------ | ---------------------------------------------------------------------- | --------------------------------------------- |
| `code`           | number | 接口业务状态码                 | `200`, `202`                                                       | 响应模型的默认值                              |
| `message`        | string | 当前任务或接口提示             | `任务已提交`, `解析完成`, `正在解析`                             | `TaskService` 维护任务状态时写入            |
| `task_id`        | string | 本次上传任务 ID                | UUID hex 字符串                                                        | `TaskService.create_task()` 生成            |
| `status`         | string | 任务状态                       | `pending`, `running`, `success`, `failed`, `partial_success` | `TaskStatus` 枚举                           |
| `progress`       | object | 任务级解析进度                 | 见 [任务状态字段描述](#任务状态字段)                                                     | `TaskService.update_progress()`             |
| `runtimeMetrics` | object | 任务级模型运行指标             | 见 `RuntimeMetrics`                                                  | workflow 与 Knowledge Service                 |
| `data`           | list   | 各文件对应各自 `FileResult` | 多文件上传时有多个元素                                                 | `document_service.run_analysis_task()` 汇总 |

补充说明：

- 当前支持多文件一次上传，但任务内文件解析是顺序处理，不是并行处理。
  
- `POST /api/documents/analyze` 返回的是提交结果，`GET /result` 返回最终解析结果。

####  B. FileResult 文件级字段描述

`data` 数组中的每个对象表示一个文件的解析结果。

| 字段            | 类型   | 含义                           | 常见取值                                      | 来源                                            |
| --------------- | ------ | ------------------------------ | --------------------------------------------- | ----------------------------------------------- |
| `fileName`    | string | 原始上传文件名                 | `demo.docx`, `page_files.zip`             | 上传保存后的文件名                              |
| `fileType`    | string | 文件扩展名大写                 | `DOCX`, `PDF`, `HTML`, `ZIP`, `PNG` | `file_path.suffix.upper()`                    |
| `fileUrl`     | string | 后端保存的文件路径 | `data/tasks/{task_id}/xxx.docx` | `document_service` |
| `fileContent` | string | 最终正文文本               | 普通文本、表格、图片信息           |  blocks 重新渲染  |
| `fileSource`  | string | 来源系统                       | 前端输入值，默认类似`my_source`             | 上传表单 `serverSource`                        |
| `createDate`  | string | 结果生成时间                   | `2026-07-01 12:00:00`                       | `document_service` 创建 `FileResult` 时写入 |
| `status`      | string | 当前文件解析状态               | `success`, `partial_success`, `failed`      | workflow `status` 或单文件异常处理           |
| `errorMessage` | string | 当前文件失败原因               | 签名校验失败、parser 异常等                  | `document_service` 从 workflow 错误中提取    |
| `blocks`      | list   | 文档结构块     | `paragraph/title/table/image`               | Normalizer后结果              |
| `assets`      | list   | 抽取出资源             | 目前主要是图片                                | Parser 保存到任务`assets/`                    |
| `chunks`      | list   | 面向 RAG/知识库入库的切片      | `chunk_1`, `chunk_2`                      | `rag_chunking_agent`                          |
| `qualityHints` | list | 后端生成的质量提示             | 见下方 qualityHints 字段描述                         | `document_service`                            |
| `metadata`    | object | 文件级元信息和 parser 附加信息 | 作者、主题、HTML ZIP 信息等                   | Parser 与 Metadata Agent                         |
| `agentTrace`  | list   | 工作流节点执行轨迹             | router/parser/metadata/vision/...             | LangGraph 各节点`_trace()`                    |
| `runtimeMetrics` | object | 当前文件的模型运行指标         | metadata/vision 等事件                         | workflow 模型节点                              |

*`partial_success` 表示基础解析完成，但 metadata 或图片理解等智能增强发生降级、pending 或失败。*

多文件上传中，如果某个文件失败或部分成功，任务整体会聚合为 `partial_success`；只有全部文件失败时，任务整体才是 `failed`。

#### C. runtimeMetrics 字段描述

`runtimeMetrics` 可以理解成：系统给自己记的一本“模型调用账本”。它不影响正文、blocks、chunks，只用来解释“模型有没有调用、调用了几次、失败几次、耗时多少、有没有降级”。

大致结构：

```json
{
  "model_call_count": 2,
  "success_count": 1,
  "failed_count": 1,
  "fallback_count": 1,
  "total_duration_ms": 3820,
  "by_stage": {
    "metadata": {
      "event_count": 1,
      "model_call_count": 1,
      "success_count": 1,
      "failed_count": 0,
      "fallback_count": 0,
      "total_duration_ms": 1200,
      "input_items": 1,
      "output_items": 1
    },
    "vision": {
      "event_count": 1,
      "model_call_count": 1,
      "success_count": 0,
      "failed_count": 1,
      "fallback_count": 1,
      "total_duration_ms": 2620,
      "input_items": 3,
      "output_items": 0
    }
  },
  "events": [
    {
      "stage": "metadata",
      "model_type": "llm",
      "model": "qwen-plus",
      "status": "success",
      "duration_ms": 1200,
      "fallback_used": false,
      "input_items": 1,
      "output_items": 1,
      "error": "",
      "details": {}
    }
  ]
}
```

总汇总字段描述：

| 字段 | 类型 | 含义 | 来源 |
| ---- | ---- | ---- | ---- |
| `model_call_count` | number | 实际进入模型调用链路的次数 | 由 events 汇总 |
| `success_count` | number | 成功模型事件数 | 由 events 汇总 |
| `failed_count` | number | 失败模型事件数 | 由 events 汇总 |
| `fallback_count` | number | 使用降级逻辑的事件数 | 由 events 汇总 |
| `total_duration_ms` | number | 模型相关动作总耗时 | 由 events 汇总 |
| `by_stage` | object | 按 `metadata/vision/embedding/qa` 聚合的指标 | `runtime_metrics.py` |
| `events` | list | 模型事件明细，一条 event 表示一次模型相关动作 | workflow / Knowledge Service |

动作解释：

- metadata：抽作者、发布时间、主题、摘要

- vision：理解图片、扫描 PDF 页面 OCR 候选

- embedding：构建知识库索引时生成向量

- qa：知识库问答时调用 QA 模型

`events` 中每条记录字段描述：

| 字段 | 含义 | 常见取值 |
| ---- | ---- | -------- |
| `stage` | 阶段 | `metadata`, `vision`, `embedding`, `qa` |
| `model_type` | 模型类型 | `llm`, `vlm`, `embedding` |
| `model` | 模型名 | `qwen3-vl-flash`, `text-embedding-v4` |
| `status` | 事件状态 | `success`, `partial_success`, `failed`, `skipped` |
| `duration_ms` | 耗时 | 毫秒 |
| `fallback_used` | 是否走降级 | `true/false` |
| `input_items/output_items` | 输入输出规模 | 图片数、chunk 数、检索来源数等 |
| `error` | 失败或跳过原因 | 未配置 API key、模型异常、开关关闭 |

**区分[任务结果字段](#任务结果字段)中的两种级别`runtimeMetrics`：**

- 任务级 `runtimeMetrics` :最外层的。 会聚合文件解析事件，以及后续“构建索引”和“知识库问答”产生的 embedding/QA 事件。
  
- 文件级 `runtimeMetrics` ：`data`下内层的，可能有多个。只包含当前文件解析阶段的 metadata/vision 事件。

>文件级 runtimeMetrics 是每个文件自己的模型调用账本；任务级 runtimeMetrics 是整个上传任务的总账本，并且还会包含后续知识库索引和问答产生的 embedding/QA 事件。

#### D. qualityHints 字段描述

```json
{
  "level": "warning",
  "code": "pending_images",
  "message": "1 张图片未完成视觉理解，图片描述可能仍是占位文本。"
}
```

| 字段 | 类型 | 含义 | 常见取值 |
| ---- | ---- | ---- | -------- |
| `level` | string | 提示级别 | `info`, `warning`, `error` |
| `code` | string | 稳定机器码 | `quality_ok`, `parse_failed`, `no_blocks`, `no_chunks`, `pending_images`, `metadata_unknown`, `fallback_used`, `model_disabled`, `model_call_failed`, `vision_limit_reached` |
| `message` | string | 面向用户的中文提示 | 可直接展示 |

这些提示不是模型打分，也不是百分制质量分，而是根据最终**后端根据结构化结果确定性生成的工作流信号**。

#### E. blocks 字段描述

每个 block 都有统一结构：

```json
{
  "type": "paragraph",
  "content": "正文内容",
  "metadata": {}
}
```
通用字段:

| 字段         | 类型   | 含义             | 取值                                           | 来源                   |
| ------------ | ------ | ---------------- | ---------------------------------------------- | ---------------------- |
| `type`     | string | 结构块类型       | `paragraph`, `title`, `table`, `image` | 各 parser 判断         |
| `content`  | string | 当前块的主要文本 | 正文、标题、表格文本、图片描述                 | Parser 或 Vision Agent |
| `metadata` | object | 类型相关扩展信息 | 不同 type 不同                                 | Parser/Agent 写入      |

##### E.1 按 type 类型分类 metadata

(1) `paragraph` 常见 metadata：

普通正文段落，**Word/HTML/PDF 文本层、PDF 扫描页 OCR 文本、单图片 OCR 文本**都可能成为 paragraph。

| 字段               | 含义                     | 常见取值                                    | 来源                            |
| ------------------ | ------------------------ | ------------------------------------------- | ------------------------------- |
| `style`          | Word 段落样式            | `Normal`, `正文`                        | Word Parser                     |
| `alignment`      | Word 对齐方式            | `center`                                  | Word Parser                     |
| `tag`            | HTML 原始标签            | `p`, `li`, `blockquote`, `div`      | HTML Parser                     |
| `source`         | 段落来源                 | `pdf`, `pdf_image_text`, `image_text` | PDF Parser 或 Vision Agent 插入 |
| `page_number`    | PDF 页码，从 1 开始      | `1`, `2`                                | PDF Parser                      |
| `formulas`       | Word 段落中的公式列表    | list                                        | Word Parser                     |
| `linked_image`   | OCR 段落对应的图片名 | `page_1.png`                              | Vision Agent 插入               |
| `vision_mode`    | 图片文字来源模式         | `ocr_and_description`                     | Vision Agent                    |
| `debug_metadata` | 底层调试信息             | 包含`bbox/font_size` 等                   | Normalizer 从主 metadata 移入   |

- `source=pdf_image_text` 表示这是 PDF 扫描页或大面积图片中提取出来的正文。

- `source=image_text` 表示这是单独上传图片中提取出来的正文。

(2) `title` 常见 metadata：

标题块，展示标题级别和判断依据等信息。系统采用**保守启发式**：宁可少识别，也尽量避免把正文误判成标题。

| 字段               | 含义          | 常见取值                                                                     | 来源                          |
| ------------------ | ------------- | ---------------------------------------------------------------------------- | ----------------------------- |
| `level`          | 标题级别      | `1` 到 `6`                                                               | Word/HTML/PDF Parser          |
| `title_source`   | 标题识别来源  | `style`, `numbered_heading`, `first_paragraph`, `pdf_font_heuristic` | Word/PDF Parser               |
| `style`          | Word 样式名   | `Heading 1`, `标题 1`                                                    | Word Parser                   |
| `tag`            | HTML 标题标签 | `h1` 到 `h6`                                                             | HTML Parser                   |
| `source`         | PDF 文本来源  | `pdf`                                                                      | PDF Parser                    |
| `page_number`    | PDF 页码      | `1`                                                                        | PDF Parser                    |
| `debug_metadata` | 底层调试信息  | 包含`font_size/bold/bbox`                                                  | Normalizer 从主 metadata 移入 |

(3) `table` 常见 metadata：

| 字段             | 含义                            | 常见取值            | 来源             |
| ---------------- | ------------------------------- | ------------------- | ---------------- |
| `table_index`  | 当前文件中的表格序号，从 1 开始 | `1`, `2`        | Word/HTML Parser |
| `rows`         | 表格原始行列文本                | `list[list[str]]` | Word/HTML Parser |
| `row_count`    | 行数                            | `2`               | Word/HTML Parser |
| `column_count` | 最大列数                        | `3`               | Word/HTML Parser |

(4) `image` 常见 metadata：

| 字段                   | 含义                              | 常见取值                                                         | 来源                   |
| ---------------------- | --------------------------------- | ---------------------------------------------------------------- | ---------------------- |
| `source`             | 图片来源                          | `html`, `pdf`, `pdf_page_render`, `image`                | Parser                 |
| `file_name`          | 保存到 assets 下的文件名          | `image_1.png`, `page_1.png`                                  | Parser                 |
| `path`               | 内部处理路径           | 原始 parser 内部可能是本地路径                                   | Parser / API 输出清洗  |
| `mime_type`          | MIME 类型                         | `image/png`, `image/jpeg`                                    | Parser                 |
| `width` / `height` | 图片像素尺寸                      | `640`, `480`                                                 | Parser 或 Vision Agent |
| `image_status`       | 图片提取状态                      | `extracted`, `rendered_page`                                 | PDF/Image Parser       |
| `description`        | 图片语义描述                      | 中文描述或 pending 文案                                          | Vision Agent           |
| `extracted_text`     | 图片中可见文字                    | 文本或空字符串                                                   | Vision Agent           |
| `image_role`         | 模型判断的图片角色                | `scan_page`, `screenshot`, `chart`, `photo`, `unknown` | Vision Agent           |
| `confidence`         | 模型自评置信度                    | `high`, `medium`, `low`, `unknown`                       | Vision Agent           |
| `vision_status`      | 视觉理解状态                      | `success`, `pending`, `failed`, `skipped`                | Vision Agent           |
| `vision_mode`        | 视觉处理模式                      | `ocr_and_description`                                          | Vision Agent           |
| `vision_model`       | 使用的模型名                      | `qwen3-vl-flash`                                               | Vision Agent           |

##### E.2 按文件格式分类 metadata

(1) Word 特有 metadata :

| 字段              | 含义             | 常见取值                                             | 来源        |
| ----------------- | ---------------- | ---------------------------------------------------- | ----------- |
| `style`         | Word 段落样式    | `Normal`, `Heading 1`, `标题 1`                | python-docx |
| `alignment`     | 对齐方式         | `center`                                           | python-docx |
| `title_source`  | 标题判断依据     | `style`, `numbered_heading`, `first_paragraph` | Word Parser |
| `formulas`      | 当前段落公式列表 | list                                                 | Word Parser |
| `formula_index` | 公式序号         | `1`                                                | Word Parser |
| `position_hint` | 公式占位符       | `[公式1]`                                          | Word Parser |
| `readable_text` | 公式可读文本     | `(a)/(b)`                                          | Word Parser |
| `latex_text`    | 简化 LaTeX       | `\\frac{a}{b}`                                     | Word Parser |

(2) HTML / HTML ZIP 特有 metadata :

| 字段                     | 含义                                      | 常见取值                              | 来源                           |
| ------------------------ | ----------------------------------------- | ------------------------------------- | ------------------------------ |
| `tag`                  | HTML 标签名                               | `h1`, `p`, `div`, `li`        | HTML Parser                    |
| `alt`                  | 图片 alt 文本                             | 字符串或空                            | HTML Parser                    |
| `original_src`         | 图片原始 src                              | 相对路径、URL、data URI               | HTML Parser                    |
| `source_url`           | 网络图片原始 URL                          | `https://...`                       | HTML Parser                    |
| `download_status`      | 网络图片下载状态                          | `success`, `failed`, `skipped`  | HTML Parser                    |
| `download_error`       | 下载失败原因                              | `response is not an image` 等       | HTML Parser                    |
| `local_status`         | 本地图片解析状态                          | `success`, `missing`, `blocked` | HTML Parser                    |
| `local_error`          | 本地图片失败原因                          | 路径越界、空 src 等                   | HTML Parser                    |
| `archive_path`         | ZIP 包路径           | 原始 parser 内部本地路径              | HTML ZIP Parser / API 输出清洗 |
| `selected_html_member` | ZIP 中选中的主 HTML                       | `index.html`                        | HTML ZIP Parser                |
| `selected_html_path`   | 解压后的主 HTML 路径 | 原始 parser 内部本地路径              | HTML ZIP Parser / API 输出清洗 |

(3) PDF 特有 metadata :

| 字段                | 含义                       | 常见取值                                           | 来源                          |
| ------------------- | -------------------------- | -------------------------------------------------- | ----------------------------- |
| `source`          | PDF 内容来源               | `pdf`, `pdf_page_render`, `pdf_image_text`   | PDF Parser / Vision Agent     |
| `page_number`     | 页码，从 1 开始            | `1`, `2`                                       | PDF Parser                    |
| `page_area_ratio` | 图片占页面面积比例         | `0.55`, `1.0`                                  | PDF Parser                    |
| `render_dpi`      | 整页渲染 DPI               | `144`                                            | PDF Parser                    |
| `ocr_candidate`   | 是否是扫描页/大图 OCR 候选 | `true/false`                                     | PDF Parser                    |
| `ocr_source`      | OCR 候选来源               | `pdf_large_image`, `pdf_page_render`, 空 | PDF Parser                    |
| `debug_metadata`  | PDF 底层调试字段           | `bbox/font_size/bold/page_width/page_height`     | Normalizer  |

PDF 中如果有文本层，优先抽取文本层。如果某页没有文本层，但有大面积图片或整页可渲染内容，会生成 `ocr_candidate=true` 的 image block。Vision Agent 提取出 `extracted_text` 后，会在该 image block 前插入 `source=pdf_image_text` 的 paragraph。

> `debug_metadata` 不是业务主字段，主要用于调试 PDF 抽取位置、标题判断和后续页面高亮定位。

(4) 单图片特有 metadata :

| 字段                   | 含义           | 常见取值      | 来源         |
| ---------------------- | -------------- | ------------- | ------------ |
| `source`             | 来源类型       | `image`     | Image Parser |
| `original_file_name` | 原始上传图片名 | `photo.png` | Image Parser |
| `image_status`       | 图片标准化状态 | `extracted` | Image Parser |

单图片上传时，图片本身被视为文档主体。如果 Vision Agent 提取出 `extracted_text`，会额外插入 `source=image_text` 的 paragraph，便于检索和问答。

#### F. chunks 字段描述

```json
{
  "chunk_id": "chunk_1",
  "content": "切片文本",
  "metadata": {
    "block_types": ["title", "paragraph"],
    "source_file": "demo.docx",
    "page_number": 1,
    "asset_refs": [],
    "heading_path": ["第一章 系统设计"],
    "ingest_enabled": true,
    "chunk_index": 1,
    "char_count": 120
  }
}
```
| 字段                                   | 含义                         | 来源                                             |
| -------------------------------------- | ---------------------------- | ------------------------------------------------ |
| `chunk_id`                           | 切片 ID                      | `rag_chunking_agent`                           |
| `content`                            | 用于入库/检索的文本          | blocks 聚合                                      |
| `metadata.block_types`               | 该 chunk 来自哪些 block 类型 | `title/paragraph/table/image`                  |
| `metadata.source_file`               | 原文件名                     | workflow state 的`file_path`                   |
| `metadata.page_number`               | 页码，主要用于 PDF           | block metadata                                   |
| `metadata.asset_refs`                | 关联图片文件名               | image block 或缓冲区                             |
| `metadata.heading_path`              | 当前 chunk 所在标题路径      | `rag_chunking_agent` 根据前置 title 维护       |
| `metadata.ingest_enabled`            | 是否参与后续知识库入库       | 默认`true`，低质量图片或人工关闭时为 `false` |
| `metadata.chunk_index`               | chunk 序号，从 1 开始        | `rag_chunking_agent`                           |
| `metadata.char_count`                | chunk 内容字符数             | `rag_chunking_agent`                           |
| `metadata.row_count` / `col_count` | 表格行列数                   | table block                                      |
| `metadata.extracted_text`            | 图片中可见文字               | image block                                      |
| `metadata.image_role`                | 图片角色                     | Vision Agent                                     |
| `metadata.ocr_review_required`       | OCR 文本是否建议人工复核     | PDF 扫描页或单图片 OCR 文本 chunk                |

#### G. metadata 文件级字段描述

| 字段                     | 含义                                    | 常见取值                                       | 来源                           |
| ------------------------ | --------------------------------------- | ---------------------------------------------- | ------------------------------ |
| `author`               | 作者                                    | 姓名或`未知`                                 | Metadata Agent / fallback      |
| `posted_time`          | 发布时间                                | 日期或`未知`                                 | Metadata Agent / fallback      |
| `organization`         | 机构、单位、学院                        | 字符串或`未知`                               | Metadata Agent / fallback      |
| `topic`                | 主题/标题                               | 字符串或`未知`                               | Metadata Agent / fallback      |
| `summary`              | 摘要                                    | 字符串或`未知`                               | Metadata Agent / fallback      |
| `extraction_mode`      | 元信息抽取模式                          | `llm:qwen3-vl-flash`, `heuristic_fallback` | Metadata Agent                 |
| `validation_error`     | 文件签名校验错误                        | 错误消息                                       | Parser Tool                    |
| `declared_file_type`   | 按扩展名判断出的文件类型                | `pdf`, `word`, `image`                   | Router/Parser Tool             |
| `archive_path`         | HTML ZIP 原始路径  | 原始 parser 内部本地路径                       | HTML ZIP Parser / API 输出清洗 |
| `selected_html_member` | ZIP 选中的主 HTML                       | `index.html`                                 | HTML ZIP Parser                |
| `selected_html_path`   | 解压后的 HTML 路径 | 原始 parser 内部本地路径                       | HTML ZIP Parser / API 输出清洗 |

`metadata` 里字段可能随文件类型扩展。固定元信息字段由 Metadata Agent 保底，格式相关字段由对应 Parser 附加。

#### H. agentTrace 执行轨迹

`agentTrace` 用于把工作流从黑盒变成可观测链路。

| 字段              | 含义             | 常见取值                                                                                                                                        | 来源                   |
| ----------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| `node`          | 节点名           | `router`, `parser_tool`, `metadata_extraction_agent`, `vision_understanding_agent`, `result_normalizer_agent`, `rag_chunking_agent` | LangGraph 节点         |
| `message`       | 节点说明         | 中文描述                                                                                                                                        | 各节点`_trace()`     |
| `status`        | 节点状态         | `success`, `partial_success`, `failed`, `skipped`                                                                                       | `_trace()`           |
| `duration_ms`   | 节点耗时毫秒     | 整数                                                                                                                                            | `_duration_ms()`     |
| `fallback_used` | 是否用了降级逻辑 | `true/false`                                                                                                                                  | Metadata/Vision 等节点 |
| `error`         | 错误信息         | 空字符串或异常信息                                                                                                                              | 各节点                 |

不同节点还会附加不同字段：

| 节点                           | 附加字段                                                                  | 含义                            |
| ------------------------------ | ------------------------------------------------------------------------- | ------------------------------- |
| `router`                     | `file_type`                                                             | 按扩展名路由出的类型            |
| `parser_tool`                | `file_type`, `block_count`, `asset_count`, `validation_status`    | parser 输出规模和签名校验结果   |
| `metadata_extraction_agent`  | `mode`, `model`, `input_chars`, `block_count`, `extracted_keys` | 元信息抽取方式和输入规模        |
| `vision_understanding_agent` | `mode`, `model`, `image_count`, `inserted_text_count`             | 图片理解方式和插入 OCR 正文数量 |
| `result_normalizer_agent`    | `error_count`, `content_chars`, `block_count`, `asset_count`      | 最终正文和结构规模              |
| `rag_chunking_agent`         | `chunk_count`, `content_chars`                                        | RAG 切片数量和文本规模          |

### 任务资源字段

`assets` 是从文档中抽取出的资源列表，目前主要是图片。

```text
GET /api/documents/tasks/{task_id}/assets/{file_name}
```

返回结构：

```json
{
  "file_name": "image_1.png",
  "path": "",
  "mime_type": "image/png"
}
```
字段描述：

| 字段          | 含义                                        | 来源                     |
| ------------- | ------------------------------------------- | ------------------------ |
| `file_name` | assets 目录下的资源文件名                   | Parser 生成              |
| `path`      | 兼容字段 | API 输出清洗             |
| `mime_type` | 文件 MIME 类型                              | Parser 或 mimetypes 推断 |

### 知识库索引字段

```text
POST/GET /api/documents/tasks/{task_id}/knowledge/index
```

| 字段                | 含义                   | 来源                                 |
| ------------------- | ---------------------- | ------------------------------------ |
| `task_id`         | 当前任务 ID            | 路由参数                             |
| `collection_name` | Chroma collection 名称 | Knowledge Service                    |
| `indexed`         | 是否已有可用索引       | Chroma 状态                          |
| `indexed_count`   | 已入库 chunk 数        | Chroma / 构建结果                    |
| `skipped_count`   | 跳过 chunk 数          | 空内容或`ingest_enabled=false`     |
| `status`          | 索引状态               | `not_built`, `built`, `failed` |
| `message`         | 可展示的中文说明   | Knowledge Service                    |
| `last_built_at`   | 最近构建时间           | 构建索引时生成                       |

### 知识库问答字段

```text
POST /api/documents/tasks/{task_id}/knowledge/ask
```

| 字段                   | 含义                               | 来源                            |
| ---------------------- | ---------------------------------- | ------------------------------- |
| `answer`             | 最终回答                           | LLM，或 retrieval-only fallback |
| `sources`            | 检索命中的来源 chunks              | Chroma 查询结果                 |
| `sources[].content`  | 来源片段正文                       | 入库 chunk                      |
| `sources[].score`    | 相似度分数，越高越相关             | 由向量距离换算                  |
| `sources[].metadata` | 文件名、chunk_id、页码、标题路径等 | 入库 metadata                   |
| `retrievalTrace`     | 检索过程摘要                       | Knowledge Service               |

### 导出接口字段

导出接口用于把人工校正后的 blocks/chunks 交给外部系统，有 json 、jsonl 两种可选格式。

```text
GET /api/documents/tasks/{task_id}/result/files/{file_index}/export?target=chunks&format=jsonl
```
#### JSON 格式

| 字段               | 含义                      | 来源                             |
| ------------------ | ------------------------- | -------------------------------- |
| `schema_version` | 导出 schema 版本          | 固定为`docagent.export.v1`     |
| `export_type`    | 导出内容类型              | `blocks`, `chunks`, `both` |
| `task_id`        | 当前任务 ID               | 路由参数                         |
| `file_index`     | 文件在任务结果中的下标    | 路由参数                         |
| `file_name`      | 原文件名                  | `FileResult.fileName`          |
| `file_type`      | 文件类型                  | `FileResult.fileType`          |
| `exported_at`    | 导出时间                  | Export Service                   |
| `metadata`       | 文件级元信息              | `FileResult.metadata`          |
| `items`          | 导出的 blocks/chunks 记录 | 当前任务结果                     |

#### JSONL 格式

JSONL 一行一条记录，适合外部向量库和批处理系统。每行包含：

| 字段                           | 含义                                                |
| ------------------------------ | --------------------------------------------------- |
| `schema_version`             | 导出 schema 版本                                    |
| `record_type`                | `block` 或 `chunk`                              |
| `id`                         | 稳定记录 ID，包含 task、file、block/chunk 信息      |
| `content`                    | 可直接消费的文本内容                                |
| `metadata`                   | block/chunk 原 metadata                             |
| `source`                     | `task_id/file_index/file_name/file_type` 来源信息 |
| `block_type`                 | 仅 block 记录存在                                   |
| `chunk_id` / `chunk_index` | 仅 chunk 记录存在                                   |

>导出不会触发向量入库，也不会修改当前任务结果。

## API 使用流程

### 启动服务

进入项目目录：

```powershell
cd "DocAgent"
```

启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Swagger 页面：

```text
http://127.0.0.1:8001/docs
```

前端工作台：

```text
http://127.0.0.1:8001/
```

健康检查：

```text
GET http://127.0.0.1:8001/health
```

### 上传文档

如果只是本地查看解析结果，优先使用前端工作台上传；如果要调试接口细节，可用 Postman。

请求：

```text
POST http://127.0.0.1:8001/api/documents/analyze
```

Body 选择 `form-data`：

| Key              | Type | Value                |
| ---------------- | ---- | -------------------- |
| `multiFiles`   | File | 选择`.docx` 文件   |
| `serverSource` | Text | 例如`postman-test` |

如果要上传多个文件，就添加多个同名 `multiFiles` 字段。

返回示例：

```json
{
  "code": 202,
  "message": "任务已提交",
  "task_id": "xxx",
  "status": "pending"
}
```

### 查询任务状态

```text
GET http://127.0.0.1:8001/api/documents/tasks/{task_id}
```

任务状态会包含 `progress`，前端进度条就是每秒轮询这个字段：

```json
{
  "status": "running",
  "message": "正在解析",
  "progress": {
    "total_files": 2,
    "processed_files": 1,
    "current_file": "demo.pdf",
    "current_step": "正在解析第 2/2 个文件",
    "percent": 50
  }
}
```

### 查询解析结果

```text
GET http://127.0.0.1:8001/api/documents/tasks/{task_id}/result
```

重点看这些字段：

- `fileContent`：文本拼接总结果。
  
- `blocks`：结构化块，包含标题、段落、表格、图片。
  
- `assets`：提取出来的图片等资源。
  
- `chunks`：面向知识库/RAG 入库的切分结果。
  
- `status/errorMessage`：单文件解析状态和失败原因，多文件上传时用于定位哪个文件失败。
  
- `qualityHints`：后端生成的质量提示，例如图片未理解、切片为空、元信息未知。
  
- `metadata`：模型或 fallback 抽取出的作者、发布时间、主题、摘要。
  
- `agentTrace`：LangGraph 节点执行过程，方便调试和展示。

多文件上传是同一任务内顺序处理。某个文件失败时，不会阻断其它文件；失败会体现在该文件的 `status=failed` 和 `errorMessage` 中。若基础解析成功但模型增强未完成，状态会是 `partial_success`，表示“结果可用但不完整”。

默认 JSON 不暴露后端本地绝对路径。图片预览不要读取 `assets[].path`，而是使用受控接口：

```text
GET /api/documents/tasks/{task_id}/assets/{file_name}
```

### 导出结构块和知识库切片

人工校正 blocks 或 chunks 后，可以导出当前文件的结构化结果给外部系统使用：

```text
GET http://127.0.0.1:8001/api/documents/tasks/{task_id}/result/files/{file_index}/export?target=chunks&format=jsonl
```

参数：

| 参数 | 取值 | 说明 |
| ---- | ---- | ---- |
| `target` | `blocks`, `chunks`, `both` | 导出结构块、知识库切片或二者 |
| `format` | `json`, `jsonl` | JSON 保留整体结构，JSONL 一行一条记录 |

JSON 导出适合归档和系统对接；JSONL 适合向量库、批处理和数据管道。导出的内容来自当前任务结果，因此会包含人工校正后的 blocks/chunks。

### 构建任务级知识库索引

解析完成并确认 `chunks` 后，点击前端“构建/重建索引”，或调用：

```text
POST http://127.0.0.1:8001/api/documents/tasks/{task_id}/knowledge/index
```

请求体：

```json
{
  "file_indices": [0],
  "rebuild": true
}
```

`file_indices` 可省略，省略时入库当前任务下所有文件的可入库切片。后端只会处理 `content` 非空且 `metadata.ingest_enabled != false` 的 chunks。

索引状态查询：

```text
GET http://127.0.0.1:8001/api/documents/tasks/{task_id}/knowledge/index
```

### 任务级知识库问答

构建索引后调用：

```text
POST http://127.0.0.1:8001/api/documents/tasks/{task_id}/knowledge/ask
```

请求体：

```json
{
  "question": "这份文档主要讲了什么？",
  "top_k": 5
}
```

返回包含：

- `answer`：基于检索片段生成的回答。
- `sources`：命中的 chunks，包含文件名、chunk_id、页码、相似度等来源信息。
- `retrievalTrace`：检索模式、top_k、模型信息。

如果没有配置问答 LLM，接口会返回检索来源，并提示“未配置问答模型，已返回相关来源片段”。

## 字段查询建议

- 只想看最终正文：看 `fileContent`。
  
- 想看文档结构是否解析对：看 `blocks`。
  
- 想看图片是否保存和能否预览：看 `assets[].file_name` 和 image block 的 `metadata.file_name`，预览走 `/api/documents/tasks/{task_id}/assets/{file_name}`。
  
- 想接知识库/RAG：优先看 `chunks`。
  
- 想排查哪里失败：看 `agentTrace` 和 `metadata.validation_error`。
  
- 想看模型是否生效：看 `metadata.extraction_mode`、image block 的 `vision_status`、`vision_model`。

# 原理介绍

## Word 模块

### 前置知识

#### 1. DOCX 本质

`.docx` 不是一个普通二进制文件，它本质上是一个压缩包。

你可以把一个 `.docx` 文件改名成 `.zip`，解压后会看到类似：

```
word/document.xml
word/media/image1.png
word/media/image2.jpg
word/_rels/document.xml.rels
[Content_Types].xml
```

大概含义是：

```
word/document.xml
文档正文结构，段落、表格、图片引用都在这里。

word/media/
真正的图片二进制文件在这里。

word/_rels/document.xml.rels
关系表，记录 document.xml 里引用的图片、链接、样式等资源到底对应哪个文件。

[Content_Types].xml
记录各种文件的 MIME 类型。
```

所以 Word 文档不是“一个页面一个页面存”的，而是“正文 XML + 资源文件 + 关系表”，底层主要存的是“流式内容”，不是固定页面。

#### 2. XML 含义

XML 可以理解成一种带标签的结构化文本，和 HTML 有点像。

比如一个简化版 Word 段落可能长这样：

```
<w:p>
  <w:r>
    <w:t>这是一段文字</w:t>
  </w:r>
</w:p>
```

含义是：

```
w:p = paragraph，段落
w:r = run，段落里的一个文本片段或对象片段
w:t = text，真正的文字
```

表格可能像这样：

```
<w:tbl>
  <w:tr>
    <w:tc>
      <w:p>
        <w:r>
          <w:t>A1</w:t>
        </w:r>
      </w:p>
    </w:tc>
  </w:tr>
</w:tbl>
```

含义是：

```
w:tbl = table，表格
w:tr = table row，表格行
w:tc = table cell，单元格
```

所以我们说“按 XML body 顺序解析”，意思就是按 `document.xml` 里真实出现的结构顺序处理。

#### 3. OOXML 规范

OOXML 全称是 Office Open XML。

它是 Microsoft Office 现代格式的标准，比如：

```
.docx = Word 的 OOXML
.xlsx = Excel 的 OOXML
.pptx = PowerPoint 的 OOXML
```

可以这样理解：

```
XML 是一种通用结构化文本格式
OOXML 是 Office 文件使用的一套 XML 规范
DOCX 是 OOXML 在 Word 文档里的具体落地形式
```

也就是说，`.docx` 里面的 `word/document.xml` 不是随便写的 XML，而是按照 OOXML 规范组织的。

#### 4. Relationship ID

DOCX 里图片不是直接写在 `document.xml` 里的。正文 XML 只保存一个引用，比如：

```
<a:blip r:embed="rId5"/>
```

然后在：

```
word/_rels/document.xml.rels
```

里会有类似：

```
<Relationship Id="rId5"
              Type=".../image"
              Target="media/image1.png"/>
```

这表示：

```
document.xml 里的 rId5
实际对应 word/media/image1.png
```

所以实际流程是：

```
找到 blip 节点
拿到 r:embed = rId5
用 rId5 去 related_parts 里找图片对象
把 image_part.blob 写成图片文件
生成 image block
```

#### 5. 按段落内部顺序处理

一个 Word 段落里不一定只有文字。它可能同时包含：

```text
普通文字
内嵌图片
Office Math 公式
换行或其他 run
```

如果只用 `paragraph.text`，通常只能拿到纯文字，图片和公式的位置会丢失。

比如一个段落实际可能是：

```text
模型结构如下：[图片]，其中损失函数为：[公式]
```

如果不扫描段落内部 XML，就容易变成：

```text
模型结构如下：，其中损失函数为：
[图片被统一放到后面]
[公式无法定位]
```

所以 Word Parser 会按段落 XML 子节点顺序扫描，遇到图片前先把已有文字落成 block，再插入 image block；遇到公式时插入 `[公式x]` 占位符，并把公式文本放到 metadata 里。

#### 6. Office Math 公式

Word 里的公式通常使用 OMML，也就是 Office Math Markup Language。它也是一种 XML 结构。

简单公式可能有普通文本节点，复杂公式可能有分数、上下标、求和等结构，例如：

```text
分数 f
  -> 分子 num
  -> 分母 den

上标 sSup
  -> 主体 e
  -> 上标 sup

下标 sSub
  -> 主体 e
  -> 下标 sub
```

当前系统对公式做轻量解析，不追求完整覆盖全部数学排版语法。目标是：


- 正文里保留公式出现位置

- metadata 里保留可读文本和简化 LaTeX

- 不把原始 XML 暴露给前端用户

### 代码设计

#### 核心实现思路

1. 用 `doc.element.body.iterchildren()` 保留段落和表格的原始顺序。
2. 用段落 OOXML 子节点扫描保留段落内部文字、图片和公式的相对顺序。
3. 用 OOXML Relationship ID 从 Word 关系表里取出图片二进制。
4. 表格只解析一级表格，保留行列文本和 Markdown 形式内容。
5. 输出 `blocks` 做结构化结果，同时拼接 `fileContent` 文本内容。

整体流程可以理解为：

```text
DOCX 文件
  -> python-docx 打开
  -> doc.element.body.iterchildren()
      -> w:p 段落
          -> 扫描段落内部 XML
          -> paragraph/title/image/formula
      -> w:tbl 表格
          -> table block
  -> render_blocks_to_text()
  -> fileContent
```

> `.docx` 本质是一个 OOXML 压缩包，正文内容在 `word/document.xml`，图片资源在 `word/media`，正文和图片之间通过 Relationship ID 关联。按 `document.xml` 的 body 顺序解析，并在段落内部按 OOXML 子节点扫描。遇到图片的 `r:embed` 引用时，通过 Relationship ID 找到对应图片二进制并生成 `image` block；遇到 Office Math 公式时，插入 `[公式x]` 占位符，并把常见公式结构转换成可读文本和简化 LaTeX。这样输出的 `paragraph/title/table/image` blocks 能尽量保持 Word 原始文档流顺序。

#### 段落处理

段落处理不是简单读取 `paragraph.text`，而是：

1. 先判断这个段落应该是 `title` 还是 `paragraph`。
2. 初始化一个文本缓冲区 `text_parts`。
3. 按段落 XML 子节点顺序遍历。
4. 遇到普通文本就追加到 `text_parts`。
5. 遇到公式就插入 `[公式x]`，同时记录公式 metadata。
6. 遇到图片就先把已有文本 flush 成 block，再保存图片并插入 image block。
7. 段落结束时再 flush 剩余文本。

这样可以处理下面这种混合段落：

```text
文字A [图片1] 文字B [公式1] 文字C [图片2]
```

输出顺序会尽量变成：

```text
paragraph: 文字A
image: 图片1
paragraph: 文字B [公式1] 文字C
image: 图片2
```

#### 标题兜底识别

标题识别分三层：

1. 样式标题：`Heading 1`、`标题 1` 等，`metadata.title_source = "style"`。
2. 编号标题：`1. 引言`、`1.1 模型结构`、`第1章 绪论`、`一、研究背景`，`metadata.title_source = "numbered_heading"`。
3. 首段兜底：第一个非空、长度适中、不像完整正文句子的段落，`metadata.title_source = "first_paragraph"`。

这样做是为了兼容真实 Word 文档：很多人只是把标题字号调大，并没有应用 Word 的标题样式。

#### 图片处理

Word 图片处理的关键是 Relationship ID。

解析流程：

```text
段落 XML 中找到 a:blip
  -> 读取 r:embed 或 r:link
  -> 用 rId 到 paragraph.part.related_parts 查找图片对象
  -> 读取 image_part.blob
  -> 根据 MIME 类型确定扩展名
  -> 保存到任务 assets/
  -> 生成 image block
```

image block 初始内容为空，图片语义描述不是 Word Parser 生成的，而是后续 Vision Understanding Agent 生成的。

如果没有配置视觉模型，image block 会被标记为 pending，`fileContent` 里会显示类似：

```text
[图片: image_1.png 图片内容: 待生成图片描述]
```

#### 公式处理

公式处理的目标不是做完整数学排版渲染，而是让公式在文档中“有位置、有可读说明、可被导出”。

公式在正文中会表现为占位符：

```text
损失函数为 [公式1]
```

对应 metadata 中会保存：

```json
{
  "formulas": [
    {
      "formula_index": 1,
      "position_hint": "[公式1]",
      "readable_text": "L = x + y",
      "latex_text": "L = x + y"
    }
  ]
}
```

对分数、上下标、求和等常见结构，系统会尝试生成简化 LaTeX。例如分数可能变成：

```text
\frac{z_{c}}{n}
```

如果遇到未知公式结构，就退回到拼接公式中的文本，保证至少不丢失主要字符。

#### 表格处理

Word 表格会生成独立的 `table` block。

当前只做一级表格，不递归解析单元格里的嵌套表格。这样做是为了保持实现稳定，也避免复杂 Word 表格把输出结构搞得过深。

表格输出两份信息：

```text
content
用于 fileContent 展示的 Markdown 表格文本。

metadata.rows
保留原始行列结构，方便前端、导出和后续处理。
```

### 输出结果

Word Parser 最终输出统一结构：

| block 类型 | 来源 | 说明 |
| ---------- | ---- | ---- |
| `title` | Word 标题样式、编号标题或首段兜底 | 保存 `level` 和 `title_source` |
| `paragraph` | 普通段落 | 保留正文文本，可能包含 `[公式x]` |
| `table` | Word 一级表格 | `content` 是 Markdown 表格，`metadata.rows` 是行列结构 |
| `image` | Word 内嵌图片 | 图片保存到 `assets/`，后续交给 Vision Agent |

常见 metadata：

| 字段 | 出现场景 | 含义 |
| ---- | -------- | ---- |
| `style` | 段落/标题 | Word 段落样式名 |
| `alignment` | 居中段落 | 例如 `center` |
| `level` | 标题 | 标题层级 |
| `title_source` | 标题 | `style`, `numbered_heading`, `first_paragraph` |
| `formulas` | 含公式段落 | 公式索引、占位符、可读文本、LaTeX |
| `table_index` | 表格 | 表格序号 |
| `rows` | 表格 | 表格行列数据 |
| `row_count` | 表格 | 行数 |
| `column_count` | 表格 | 最大列数 |
| `file_name` | 图片 | assets 中的图片文件名 |
| `path` | 图片 | 后端保存路径，API 输出时会做本地路径清洗 |
| `mime_type` | 图片 | 图片 MIME 类型 |

输出示例：

```json
{
  "type": "title",
  "content": "1.1 Word 解析",
  "metadata": {
    "style": "Normal",
    "level": 2,
    "title_source": "numbered_heading"
  }
}
```

```json
{
  "type": "image",
  "content": "",
  "metadata": {
    "file_name": "image_1.png",
    "path": "data/tasks/{task_id}/assets/image_1.png",
    "mime_type": "image/png"
  }
}
```

最终 `fileContent` 不是原始 Word 文本，而是由 blocks 重新渲染出来的结果。这样人工校正 blocks 后，后端可以重新生成稳定的 `fileContent` 和 chunks。

## PDF 模块

### 前置知识

#### 1. PDF 文本层和扫描页

PDF 和 Word 不一样。Word 更像“文档流”，而 PDF 更像“页面版式结果”。

一个 PDF 页面里可能有两类内容：

```text
文本层
  -> 可以直接提取文字、字体大小、粗细、坐标等信息。

图片层
 -> 可能是文档里的插图，也可能是整页扫描图。
```

如果 PDF 有文本层，系统会优先读取文本层，因为这种方式稳定、成本低，也不会依赖 OCR。

如果某一页没有文本层，但页面仍然有可渲染内容，就很可能是扫描版 PDF。系统会把这一整页渲染成图片，并标记为 OCR 候选，后续交给 Vision Understanding Agent 处理。

#### 2. PyMuPDF 和页面坐标

PDF Parser 使用 PyMuPDF 读取页面内容。

PyMuPDF 可以把页面内容拆成 blocks，每个 block 可能是：

```text
type = 0
 -> 文本块，里面有 lines、spans、font size、font flags、bbox。

type = 1
 -> 图片块，里面有图片二进制、宽高、扩展名、bbox。
```

其中 `bbox` 是页面上的矩形坐标，大致表示该文本块或图片块在页面中的位置。系统会用 bbox 做页内排序，也会把它保存到 block metadata 里，方便后续调试。

#### 3. PDF 标题识别保守估计

PDF 里通常没有 Word 那种明确的标题样式结构。一个看起来像标题的文本，底层可能只是字号更大、字体更粗、位置更靠上。

因此 PDF 标题识别只能用启发式规则：

- 字号明显大于正文

- 字体加粗且长度适中

- 字号达到较高阈值

这类规则不能保证所有 PDF 都准确，但可以避免把大段正文误判成标题。

### 代码设计

#### 核心实现思路

1. 用 PyMuPDF 打开 PDF，按页遍历。
2. 对每页调用 `page.get_text("dict")`，拿到文本块和图片块。
3. 文本块按 bbox 排序，拼接 span 文本。
4. 根据字体大小、bold、正文中位数字号等信息，保守判断 `title` 或 `paragraph`。
5. 图片块保存到任务 `assets/`，生成 image block。
6. 过滤过小图片，避免把图标、装饰点、统计像素当成有效图片。
7. 如果页面没有文本、没有可用图片但有可渲染内容，把整页渲染为 PNG。
8. 扫描页或大面积图片标记 `ocr_candidate=true`，交给 Vision Agent 进一步理解。

可以把 PDF 解析流程理解成：

```text
PDF 页面
  -> 提取文本块
      -> paragraph/title block
  -> 提取图片块
      -> image block + assets
  -> 无文本扫描页兜底
      -> 整页渲染为图片
      -> ocr_candidate=true
```

#### OCR 候选页处理

PDF Parser 本身不直接做 OCR。它只负责判断“哪些图片或页面适合做 OCR”。

规则主要有两类：

```text
大面积图片
 -> 页面没有文本层，并且图片 bbox 占页面面积较大。
 -> 某张图片覆盖页面面积 >= 0.55

整页渲染图
 -> 页面没有文本，也没有可直接抽取的可用图片，但页面本身可渲染。
```

这些 image block 会带上：

```json
{
  "ocr_candidate": true,
  "ocr_source": "pdf_large_image 或 pdf_page_render"
}
```

后续 Vision Agent 如果提取到 `extracted_text`，系统会额外插入一个 paragraph block：

```json
{
  "type": "paragraph",
  "content": "OCR 提取出的文字",
  "metadata": {
    "source": "pdf_image_text",
    "linked_image": "page_1.png"
  }
}
```

这样做的原因是：扫描 PDF 的文字本身就是正文，应该进入 `fileContent` 和后续 chunks。

### 输出结果

PDF 最终仍然输出统一 blocks：

| block 类型 | 来源 | 说明 |
| ---------- | ---- | ---- |
| `title` | PDF 文本层 | 字号/加粗启发式判断出的标题 |
| `paragraph` | PDF 文本层或 OCR 候选文本 | 普通正文，或扫描页 OCR 插入文本 |
| `image` | PDF 内嵌图片或整页渲染图 | 插图、扫描页、大面积图片 |

常见 metadata：

| 字段 | 含义 |
| ---- | ---- |
| `source` | `pdf`, `pdf_page_render`, `pdf_image_text` |
| `page_number` | 页码，从 1 开始 |
| `bbox` | 页面内坐标 |
| `font_size` | 文本块字号 |
| `title_source` | PDF 标题启发式来源 |
| `file_name` | 图片资源文件名 |
| `page_area_ratio` | 图片占页面面积比例 |
| `ocr_candidate` | 是否建议交给 Vision 做 OCR |
| `ocr_source` | OCR 候选来源 |

## HTML 模块

### 前置知识

#### 1. HTML 是 DOM 树

HTML 文档不是按页存储，而是由标签组成的 DOM 树。

常见结构类似：

```html
<article>
  <h1>标题</h1>
  <p>正文段落</p>
  <img src="./demo_files/image.png" />
  <table>...</table>
</article>
```

系统要做的事情不是保留网页样式，而是把网页正文内容抽取成统一的 blocks：

```text
h1-h6      -> title block
p/li/quote -> paragraph block
table      -> table block
img        -> image block
```

#### 2. 浏览器保存网页 ZIP

浏览器保存网页时，通常会得到：

```text
page.html
page_files/
  image1.png
  style.css
  script.js
```

如果用户把这些内容压成 ZIP 上传，系统会把它当作“网页包”，而不是通用压缩包。

ZIP 解析时最重要的是两件事：

```text
安全解压
 -> 防止 Zip Slip，避免 ZIP 中的路径逃出任务目录。

选择主 HTML
 -> 从多个 HTML 文件里挑出真正要解析的入口页面。
```

#### 3. HTML 图片来源比较复杂

网页图片不一定只在 `src` 里。常见情况包括：

```text
src
data-src
data-original
data-lazy-src
srcset
base64 data:image
远程 http/https 图片
本地相对路径图片
```

所以 HTML Parser 会同时兼容普通图片、懒加载图片、base64 图片、本地附件图片和远程图片。

### 代码设计

#### 核心实现思路

1. 用 BeautifulSoup 读取 HTML。
2. 根据页面声明 charset、UTF-8、GB18030、GBK 等候选编码读取文本。
3. 删除 `script/style/iframe/form/button` 等噪声节点。
4. 删除导航、页脚、侧边栏、评论、广告等常见噪声容器。
5. 从 `body` 开始按 DOM 顺序递归遍历。
6. 遇到标题、段落、表格、图片就生成对应 block。
7. 段落和标题内部如果夹杂图片，会先 flush 文本，再生成 image block，尽量保留顺序。
8. 最后用统一的 `render_blocks_to_text()` 生成 `fileContent`。

#### ZIP 网页包处理

ZIP 只作为“浏览器保存网页包”处理。系统不会把它当成任意压缩文件批量解析。

主 HTML 选择规则：

```text
1. 优先 index.html / index.htm
2. 其次选择根目录下最大的 HTML
3. 最后选择整个 ZIP 中最大的 HTML
```

安全处理包括：

```text
禁止绝对路径
禁止 ..
过滤 __MACOSX、.DS_Store 等系统文件
限制文件数量
限制单文件大小
限制解压后总大小
只解压主 HTML 和图片资源
```

#### 图片处理

HTML 图片会生成 image block，并把图片尽量保存到任务 `assets/`。

不同来源处理方式：

| 图片来源 | 处理方式 |
| -------- | -------- |
| base64 `data:image/...` | 解码保存为本地图片 |
| 本地相对路径 | 在 HTML 所在目录下查找并复制 |
| 远程 URL | 根据配置尝试下载，失败则保留状态 |
| 懒加载属性 | 从 `data-src` 等属性中提取真实地址 |

图片 metadata 中会保留 `original_src`、`alt`、`source_url`、`download_status`、`local_status`、`local_error`等字段。

### 输出结果

HTML 最终输出：

| block 类型 | 来源 | 说明 |
| ---------- | ---- | ---- |
| `title` | `h1-h6` | metadata 保存 `tag` 和 `level` |
| `paragraph` | `p/li/blockquote/div` | 清洗后的正文文本 |
| `table` | `table` | 转成 Markdown 表格文本，同时保存 rows |
| `image` | `img` | 保存图片资源，后续交给 Vision Agent |

HTML ZIP 额外 metadata：

| 字段 | 含义 |
| ---- | ---- |
| `archive_path` | 原始 ZIP 路径 |
| `selected_html_member` | ZIP 中选中的主 HTML |
| `selected_html_path` | 解压后的主 HTML 路径 |

## 图片模块

### 前置知识

#### 1. 单图片上传也被当成文档

如果用户上传的是一张图片，系统不会把它当作普通附件，而是把它视为“图片型文档”。

也就是说，图片入口会生成一个 image block，然后交给统一的 Vision Understanding Agent。

```text
图片文件
  -> image_parser
  -> image block
  -> Vision Agent
  -> description / extracted_text / image_role
  -> fileContent / chunks
```

#### 2. 为什么要先用 Pillow 校验

只看扩展名不可靠。一个文件可能叫 `.png`，但内容不是有效图片。

所以 Image Parser 会用 Pillow 打开并校验图片内容，确认能读取宽高、格式和 MIME 类型。

支持的位图格式：

```text
.jpg / .jpeg / .png / .webp / .bmp / .gif / .tif / .tiff
```

不支持的格式会直接失败，例如：

```text
.svg / .ico / .heic / .raw / .psd / .txt
```

### 代码设计

#### 核心实现思路

1. 检查文件是否存在。
2. 检查扩展名是否属于支持的图片格式。
3. 用 Pillow 打开图片，读取宽高、真实格式和 MIME 类型。
4. 调用 `image.verify()` 确认图片内容可读。
5. 复制图片到任务 `assets/` 目录。
6. 生成一个 image block。
7. 由后续 Vision Agent 生成图片描述和图片文字。

Image Parser 自身不调用模型，它只负责把图片标准化成统一结构。

#### 单图片 OCR 文本插入规则

普通 Word/HTML/PDF 插图中的 `extracted_text` 通常只放在 image metadata 中，不直接插入正文。

但单图片上传不同：用户上传的整张图片就是文档主体。如果 Vision Agent 提取到 `extracted_text`，系统会插入 paragraph block：

```json
{
  "type": "paragraph",
  "content": "图片中提取出的文字",
  "metadata": {
    "source": "image_text",
    "linked_image": "image_1.png"
  }
}
```

这样图片型文档的文字可以进入 `fileContent`，也能进入 RAG chunks。

### 输出结果

单图片解析成功后，基础输出类似：

```json
{
  "type": "image",
  "content": "",
  "metadata": {
    "source": "image",
    "file_name": "image_1.png",
    "mime_type": "image/png",
    "original_file_name": "demo.png",
    "original_extension": ".png",
    "detected_format": "PNG",
    "extension_mismatch": false,
    "width": 1200,
    "height": 800,
    "image_status": "extracted"
  }
}
```

Vision Agent 增强后，image metadata 可能继续包含：

| 字段 | 含义 |
| ---- | ---- |
| `vision_status` | 图片理解状态 |
| `description` | 图片语义描述 |
| `extracted_text` | 图片中可见文字 |
| `image_role` | 图片作用，例如截图、图表、扫描页 |
| `confidence` | 模型置信度 |
| `vision_model` | 使用的视觉模型 |

## LLM 模块

### 前置知识

DocAgent 里大模型不是用来替代 Word/PDF/HTML/Image Parser 的。

Parser 做的是稳定、确定性的结构解析：

- DOCX 段落、表格、图片抽取

- PDF 文本层、图片和扫描页候选识别

- HTML DOM 清洗和网页包解析

- 单图片文件校验和标准化


大模型做的是语义增强和 RAG 能力：

```text
Metadata Agent
 -> 抽取作者、发布时间、机构、主题、摘要。

Vision Agent
 -> 生成图片语义描述、提取图片可见文字、判断图片作用。

Embedding
 -> 把 chunks 和用户问题转成向量。

QA LLM
 -> 基于检索来源生成回答。
```

这样设计的原因是：基础解析必须稳定可验证，不能因为模型没配置、模型超时或模型输出格式异常就整体失败。


### 代码设计

#### Metadata Agent

Metadata Agent 不会把完整文档直接传给模型，而是构造裁剪后的 `metadata_context`。

裁剪内容包括：

```text
前 5 个 title block
fileContent 前 6000 字
fileContent 后 2000 字
前 20 个 paragraph block，每个最多 300 字
```

模型被要求只返回 JSON：

```json
{
  "author": "作者",
  "posted_time": "发布时间",
  "organization": "机构",
  "topic": "主题",
  "summary": "摘要"
}
```

如果模型没配置、开关关闭或调用失败，系统会走启发式 fallback，并保证这些字段仍然存在，找不到的信息填 `未知`。

#### Vision Agent

Vision Agent 按 image block 粒度逐张处理图片。

每张图片输入：

```text
图片 base64 data URL
图片前后各 1-2 个文本 block
提示词要求返回 description / extracted_text / image_role / confidence
```

模型返回后会写回 image metadata：

```json
{
  "vision_status": "success",
  "description": "图片语义描述",
  "extracted_text": "图片中可见文字",
  "image_role": "chart",
  "confidence": "high",
  "vision_mode": "ocr_and_description",
  "vision_model": "qwen3-vl-flash"
}
```

如果模型返回的不是 JSON，系统会尽量把返回文本当成 `description`，不让格式异常中断主流程。

#### 图片文字进入正文规则

`extracted_text` 默认只保存在 image metadata 中。

只有两类图片文字会额外插入 paragraph，进入 `fileContent` 和后续 chunks：

```text
PDF 扫描页 / 大面积 OCR 候选图片
  -> source=pdf_image_text

单图片上传
  -> source=image_text
```

普通 Word/HTML/PDF 插图中的 `extracted_text` 不直接插入正文，避免把图例、坐标轴、截图局部文字误当成正文。

#### Embedding 与 QA

Embedding 用于两个地方：

1. 构建知识库索引时，把可入库 chunks 转成向量。
2. 用户提问时，把 question 转成查询向量。

当前 embedding 批大小受配置限制，最大不超过 10，避免超过 DashScope batch 上限。

QA LLM 只接收 Chroma 检索到的 sources，不接收完整文档。这样可以控制上下文长度，也能减少回答编造。

如果没有配置 QA LLM，系统会进入 retrieval-only 模式，只返回检索来源片段，不生成总结回答。

#### 模型配置

常用环境变量：

```powershell
$env:DASHSCOPE_API_KEY="你的 API Key"
$env:DASHSCOPE_BASE_URL="你的 OpenAI-compatible Base URL"
$env:LLM_MODEL="qwen3-vl-flash"
$env:EMBEDDING_MODEL="text-embedding-v4"
```

功能开关和限流：

```powershell
$env:METADATA_ENABLED="true"
$env:VISION_ENABLED="true"
$env:EMBEDDING_ENABLED="true"
$env:QA_ENABLED="true"
$env:MODEL_TIMEOUT_SECONDS="60"
$env:MODEL_RETRY_TIMES="1"
$env:VISION_MAX_IMAGES_PER_FILE="20"
$env:EMBEDDING_BATCH_SIZE="10"
```

说明：

| 配置 | 含义 |
| ---- | ---- |
| `METADATA_ENABLED=false` | 元信息抽取不调用 LLM，走 fallback |
| `VISION_ENABLED=false` | 图片保留为 image block，但标记 pending |
| `EMBEDDING_ENABLED=false` | 构建索引返回明确错误，不影响解析 |
| `QA_ENABLED=false` | 问答只返回检索来源 |
| `VISION_MAX_IMAGES_PER_FILE` | 限制单文件最多理解多少张图片 |
| `EMBEDDING_BATCH_SIZE` | embedding 批大小，代码限制在 1 到 10 |

API key 和功能开关同时生效。即使配置了 API key，只要对应开关关闭，也不会调用该能力。

#### fallback 与可观测性

模型失败不会直接等于任务失败。

常见降级：

| 场景 | 降级方式 |
| ---- | -------- |
| Metadata 模型不可用 | 使用启发式 metadata，未知字段填 `未知` |
| Vision 模型不可用 | image block 标记为 `pending` 或 `failed` |
| Embedding 未配置 | 构建索引返回明确错误 |
| QA LLM 未配置 | 返回 retrieval-only 来源片段 |

降级信息会进入：

```text
agentTrace
qualityHints
runtimeMetrics
```

其中 `agentTrace` 关注 workflow 节点是否执行，`runtimeMetrics` 更关注模型层是否真正调用、耗时多少、输入输出数量和是否 fallback。

### 输出结果

大模型不会产生新的顶层文件类型，而是增强已有结构：

| 输出位置 | 典型字段 |
| -------- | -------- |
| `metadata` | `author`, `posted_time`, `organization`, `topic`, `summary`, `extraction_mode` |
| image block `metadata` | `vision_status`, `description`, `extracted_text`, `image_role`, `confidence`, `vision_model` |
| OCR paragraph | `source=pdf_image_text` 或 `source=image_text` |
| `runtimeMetrics.events` | `stage`, `model_type`, `model`, `status`, `duration_ms`, `fallback_used` |
| `retrievalTrace` | `mode`, `top_k`, `embedding_model`, `llm_model` |

## RAG 模块

### 前置知识

#### 1. blocks 和 chunks 的关系

`blocks` 是文档解析结构，尽量还原文档原始内容顺序。

`chunks` 是面向知识库/RAG 入库的切片，重点是方便检索和问答。

两者关系可以理解为：

```text
blocks
  -> 人工校正
  -> rag_chunking_agent
  -> chunks
  -> 人工校正 chunks / 控制 ingest_enabled
  -> Chroma 向量索引
  -> 检索问答
```

#### 2. 为什么不直接把全文丢进向量库

全文太长会导致：

- 检索命中不精确

- 上下文过长

- 模型回答容易混入无关信息

- 表格和图片描述边界不清楚

- 用户无法控制哪些内容入库

因此系统先把文档变成结构化 blocks，再按结构生成 chunks。

#### 3. 为什么当前不做 overlap

当前系统有人工 chunk 检查和 `ingest_enabled` 开关。为了减少重复片段和检索噪声，当前默认不做 overlap。

如果后续面向长篇论文、法规、合同等强结构文档，可以再做领域专用切片策略。

### 代码设计

#### Chunking 核心思路

RAG Chunking Agent 的目标长度约为 1000 字符，优先按 block 边界切分。

切片规则：

- 标题会和后续正文尽量合并，并在 metadata 中形成 `heading_path`。
- 普通段落会按 block 顺序累积，目标长度约 1000 字。
- 单个 paragraph 超长时，优先按中文/英文句末标点、换行等自然边界拆分；只有找不到合适边界时才按字符数硬切。
- 表格单独成 chunk；如果前面存在标题路径，`content` 会注入 `标题1 > 标题2` 后再拼接表格内容，提升向量检索时的上下文完整度。
- 图片单独成 chunk，内容使用图片描述。
- PDF 扫描页 OCR 生成的 paragraph 会正常进入文本 chunk。

切片时会维护：`block_types`、`source_file`、`page_number`、`asset_refs`、`heading_path`、`block_sources`、`ocr_review_required` 等字段。

如果 chunk 来源包含 `pdf_image_text` 或 `image_text`，会标记：

```json
{
  "ocr_review_required": true
}
```

表示这段文字来自 OCR 或图片识别，建议人工复核。

#### 图片 chunk 入库控制

图片 block 会单独生成 chunk，但如果图片描述还是 pending、failed 或明显是占位文本，会自动设置：

```json
{
  "ingest_enabled": false
}
```

这样可以避免“待生成图片描述”这类低质量文本进入向量库。

#### Chroma 入库流程

知识库索引是任务级的，每个任务一个 collection：

```text
docagent_task_{task_id}
```

构建索引时：

1. 读取任务结果中的 chunks。
2. 根据 `file_indices` 选择全部文件或部分文件。
3. 跳过空 content。
4. 跳过 `metadata.ingest_enabled=false` 的 chunk。
5. 调用 embedding 模型生成向量。
6. 写入本地 Chroma 持久化目录。
7. 记录 embedding 阶段的 runtimeMetrics。

如果没有配置 embedding key，系统不会偷偷失败，而是返回明确错误，并记录 skipped/fallback 类型的运行指标。

#### 问答流程

问答时流程是：

```text
用户问题
  -> embedding 成查询向量
  -> Chroma top_k 检索
  -> sources 来源片段
  -> QA LLM 生成回答
```

如果未配置 QA LLM，系统会进入 retrieval-only 模式：

```text
不生成最终总结回答
只返回检索命中的来源片段
```

这保证了即使没有问答模型，用户仍然能看到“系统认为相关的 chunks”。

### 输出结果

RAG Chunking Agent 输出的 chunk 结构：

```json
{
  "chunk_id": "chunk_1",
  "content": "切片正文",
  "metadata": {
    "block_types": ["title", "paragraph"],
    "source_file": "demo.pdf",
    "page_number": 1,
    "asset_refs": [],
    "heading_path": ["第一章 总则"],
    "chunk_index": 1,
    "char_count": 356,
    "ingest_enabled": true
  }
}
```

Chroma 入库 metadata 会补充任务和文件来源：

| 字段 | 含义 |
| ---- | ---- |
| `task_id` | 当前任务 ID |
| `file_index` | 文件在任务结果中的下标 |
| `file_name` | 原文件名 |
| `chunk_id` | chunk ID |
| `chunk_index` | chunk 序号 |
| `block_types` | 来源 block 类型 |
| `page_number` | 页码 |
| `asset_refs` | 关联图片资源 |
| `heading_path` | 标题路径 |

知识库问答返回：

| 字段 | 含义 |
| ---- | ---- |
| `answer` | LLM 回答或 retrieval-only 提示 |
| `sources` | 检索命中的来源 chunks |
| `sources[].score` | 相似度分数 |
| `sources[].metadata` | 来源文件、chunk、页码、标题路径等 |
| `retrievalTrace` | 检索模式、top_k、模型信息 |

## 部署模块

### 前置知识

#### 1. 为什么需要部署模块

本地开发时，通常按下面流程启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

这种方式依赖当前电脑上的 Python、`.venv`、依赖版本、环境变量和本地目录。换一台电脑后，需要重新创建虚拟环境、安装依赖、配置模型 API key，再手动启动服务。

Docker 部署的目标是把这些运行条件固定下来，让项目可以通过统一方式启动。对 DocAgent 来说，部署模块主要解决四件事：

1. 固定 Python 运行环境和依赖版本。
2. 固定 FastAPI 服务启动命令。
3. 固定上传文件、图片资源和 Chroma 向量库的数据目录。
4. 通过环境变量注入模型 API key、模型名和功能开关。

#### 2. Docker 的核心概念

Docker 可以理解成把“项目代码 + 运行环境 + 启动命令”封装成可复制的运行单元。

| 概念 | 含义 | 在本项目中的对应 |
| ---- | ---- | ---------------- |
| `Dockerfile` | 镜像构建说明书 | 说明如何安装 Python 依赖、复制 `app/`、启动 uvicorn |
| image | 根据 `Dockerfile` 构建出来的镜像 | `docagent:latest` |
| container | 镜像真正运行起来后的容器实例 | 正在运行的 DocAgent 服务 |
| port mapping | 端口映射 | 本机 `8001` 映射到容器 `8001` |
| volume | 数据挂载 | 本机 `./data` 挂载到容器 `/app/data` |
| env | 环境变量 | `DASHSCOPE_API_KEY`、`LLM_MODEL`、`VECTOR_STORE_DIR` 等 |

可以这样理解三者关系：

```text
Dockerfile          负责怎么构建镜像
docker build        负责生成镜像
docker run/compose  负责把镜像启动成容器
```

#### 3. 为什么要挂载 data 目录

容器默认是可删除、可重建的运行环境。如果上传文件、图片资源和向量库只保存在容器内部，容器删除后这些数据也可能丢失。

DocAgent 的运行数据主要包括：

```text
data/tasks/{task_id}/
data/tasks/{task_id}/task.json
data/tasks/{task_id}/assets/
data/vector_store/chroma/
```

因此部署时需要把本机目录挂载到容器目录：

```text
本机 ./data  <->  容器 /app/data
```

其中 `task.json` 保存任务状态、解析结果、人工校正后的 blocks/chunks、qualityHints、agentTrace 和 runtimeMetrics；`assets/` 保存图片资源；`vector_store/chroma/` 保存 Chroma 向量库。

这样即使容器重建，已完成任务、上传文件、assets、解析结果和 Chroma 持久化向量库仍然保留在宿主机。需要注意的是：如果服务重启时任务仍处于 `pending` 或 `running`，系统不会自动续跑该任务，而是会在恢复时标记为 `failed`，提示用户重新上传解析。

#### 4. `.env.example` 和 `.env`

`.env.example` 是环境变量模板，适合提交到项目中，告诉使用者需要配置哪些变量。

`.env` 是真实运行配置，通常包含真实 API key，不应该提交到代码仓库。

推荐做法：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写真实配置：

```env
DASHSCOPE_API_KEY=你的真实 API Key
DASHSCOPE_BASE_URL=你的 OpenAI-compatible Base URL
LLM_MODEL=qwen3-vl-flash
EMBEDDING_MODEL=text-embedding-v4
DOCAGENT_HOST_PORT=8001
```

当前后端代码通过 `os.getenv()` 读取环境变量。本地直接用 Python 启动时，系统读取的是当前 PowerShell 进程里的环境变量；Docker Compose 启动时，`env_file: .env` 会把 `.env` 内容注入容器环境变量，后端同样能读取到。

### 代码设计

#### Dockerfile

`Dockerfile` 用来描述镜像怎么构建。本项目的 Dockerfile 做了这些事：

1. 使用 `python:3.13-slim` 作为基础环境。
2. 设置 `/app` 为工作目录。
3. 复制 `requirements.txt` 并安装运行依赖。
4. 复制 `app/`、`README.md`、`LICENSE`。
5. 创建 `/app/data` 数据目录。
6. 容器启动时运行：

```text
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

这里使用 `0.0.0.0` 是因为服务要在容器内部对外监听。如果写成 `127.0.0.1`，只会监听容器内部本地地址，宿主机可能访问不到。

#### docker-compose.yml

`docker-compose.yml` 是对 `docker run` 长命令的配置化封装。

当前配置核心内容：

```yaml
services:
  docagent:
    build:
      context: .
      dockerfile: Dockerfile
    image: docagent:latest
    container_name: docagent
    ports:
      - "${DOCAGENT_HOST_PORT:-8001}:8001"
    env_file:
      - .env
    environment:
      DOCAGENT_DATA_DIR: /app/data
      VECTOR_STORE_DIR: /app/data/vector_store/chroma
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

关键字段含义：

| 字段 | 含义 |
| ---- | ---- |
| `build.context` | 使用当前项目目录构建镜像 |
| `dockerfile` | 使用当前目录下的 `Dockerfile` |
| `image` | 构建后的镜像名 |
| `container_name` | 容器名 |
| `ports` | 本机端口映射到容器端口 |
| `env_file` | 从 `.env` 注入环境变量 |
| `environment` | 覆盖容器内数据目录配置 |
| `volumes` | 把本机 `./data` 挂载到容器 `/app/data` |
| `restart` | 服务异常停止后自动重启策略 |

端口配置：

```yaml
ports:
  - "${DOCAGENT_HOST_PORT:-8001}:8001"
```

含义是：如果 `.env` 里设置了 `DOCAGENT_HOST_PORT`，就使用该端口；否则默认使用本机 `8001`。

例如 `.env` 中写：

```env
DOCAGENT_HOST_PORT=8010
```

则访问地址变为：

```text
http://127.0.0.1:8010/
```

### 使用流程

#### 1. 本地普通启动

适合开发调试：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

这种方式读取的是当前 PowerShell 进程的环境变量，例如：

```powershell
$env:DASHSCOPE_API_KEY="你的 API Key"
$env:METADATA_ENABLED="true"
```

#### 2. Docker Compose 启动

适合交付部署：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

后台启动：

```powershell
docker compose up -d --build
```

停止服务：

```powershell
docker compose down
```

访问地址：

```text
http://127.0.0.1:8001/
```

如果端口被占用，修改 `.env`：

```env
DOCAGENT_HOST_PORT=8010
```

然后重新启动：

```powershell
docker compose up -d --build
```

访问地址改为：

```text
http://127.0.0.1:8010/
```

#### 3. 直接 Docker 启动

如果不使用 Compose，也可以手动构建和运行：

```powershell
docker build -t docagent:latest .
```

```powershell
docker run --rm -p 8001:8001 `
  -v ${PWD}\data:/app/data `
  --env-file .env `
  docagent:latest
```

这条命令中：

| 参数 | 含义 |
| ---- | ---- |
| `--rm` | 容器停止后自动删除容器记录 |
| `-p 8001:8001` | 本机 8001 映射到容器 8001 |
| `-v ${PWD}\data:/app/data` | 挂载数据目录 |
| `--env-file .env` | 注入环境变量 |
| `docagent:latest` | 使用该镜像启动 |

### 常见问题

#### 1. Docker 部署会不会使用本机 `.venv`

不会。Docker 镜像内部会根据 `requirements.txt` 重新安装依赖。`.venv` 会被 `.dockerignore` 排除，不会进入镜像。

#### 2. Docker 启动后数据保存在哪里

由于 `docker-compose.yml` 配置了：

```yaml
volumes:
  - ./data:/app/data
```

所以容器内 `/app/data` 的数据会落到本机项目目录的 `data/` 下。

#### 3. 为什么 `.env.example` 不直接改成 `.env`

`.env.example` 是模板，可以提交给别人看；`.env` 是真实配置，可能包含 API key，应该留在本机并被 `.gitignore` 忽略。

#### 4. 当前 Docker 部署是否包含前端

包含。DocAgent 的前端是 FastAPI 挂载的静态页面，代码在 `app/static/`，随 `app/` 一起复制进镜像。容器启动 FastAPI 后，访问 `/` 就是前端工作台，访问 `/system` 就是系统说明页。

#### 5. 当前 Docker 部署是否包含 Chroma 持久化

包含本地目录级持久化。`VECTOR_STORE_DIR` 被设置为：

```text
/app/data/vector_store/chroma
```

该目录又通过 volume 映射到本机 `./data/vector_store/chroma`，因此向量库数据不会随着容器重建而丢失。

# 面试与设计问答

## 系统整体

### 一句话介绍项目

DocAgent 是一个基于 FastAPI、LangGraph 的多模态文档解析与行业知识库构建系统。Parser 负责稳定抽取文档结构，LLM/VLM Agent 负责元信息抽取、图片描述和图片文字提取，最终输出统一 JSON，并生成面向知识库入库的 chunks。

### 当前适用于哪些场景

当前版本适合多格式文档的结构化解析、入库前治理和任务级行业知识库问答，尤其适合常规办公文档和网页资料，例如 Word 图文混排文档、普通 PDF、HTML/HTML ZIP 网页包、技术文档、项目说明书、工作报告、教程资料和单图片文档。系统可以把这些材料解析成 `title / paragraph / table / image` blocks，经过图片理解、metadata 抽取、人工校正和 chunk 编辑后，再写入 Chroma 做任务级问答。

### 当前不适合直接承诺哪些能力

法规、合同、招投标文件、学术论文这类强领域结构文档虽然也能做基础解析，但高质量切片还需要专门规则。例如法规需要识别“章、节、条、款、目录、发文信息”；合同需要识别甲乙方、定义条款、权利义务和附件；论文需要处理摘要、图表编号、公式、参考文献和多栏版面。当前系统更准确的定位是通用多模态文档解析与行业知识库构建工作台，领域文档需要在这个框架上继续扩展专用 parser。

### 是否为多智能体架构

准确说是基于 LangGraph 的 Agent 工作流。不是所有模块都是 Agent。Router 和 Parser 是确定性工具节点，Metadata/Vision 是 Agent 风格节点，Normalizer 和 RAG Chunking 是后处理节点。

### 为什么进度先用轮询而不是 SSE

当前任务接口已经是异步任务模型：上传返回 `task_id`，前端每秒查询任务状态。第一版进度只需要展示文件级处理进度和当前阶段，用 `progress.total_files / processed_files / current_file / current_step / percent` 就能满足本地演示和常规使用。SSE 或 WebSocket 更适合节点级、页级、图片级实时事件，但会增加连接管理和实现复杂度，所以先采用轮询增强版，后续再升级流式进度。

### 多文件里一个文件失败会怎样

单文件失败不会让整个任务直接崩掉。每个 `FileResult` 都有自己的 `status` 和 `errorMessage`，例如伪装 PDF 会在该文件中返回 `status=failed` 和签名校验错误；其它文件仍继续解析。只要任务中存在 `failed` 或 `partial_success` 文件，任务整体会聚合为 `partial_success`；只有所有文件都 `success` 时，任务整体才是 `success`。

### 当前不足

PDF 表格、页眉页脚过滤、多栏阅读顺序还没有深入处理；公式目前是轻量可读化，不承诺覆盖全部 OMML 语法；模型调用已有基础超时、重试、图片数量限制和 embedding 批大小限制，但还缺少更完整的并发限流、成本估算和调用预算控制。

## 模块细节

### runtimeMetrics 和 agentTrace 区别

`agentTrace` 看的是工作流节点，比如 router、parser、metadata、vision、chunking 是否执行。`runtimeMetrics` 看的是模型层，比如是否真的调用了 LLM/VLM/Embedding、输入了多少图片或切片、耗时多少、是否 fallback、失败原因是什么。两者配合起来可以解释“Parser 成功但图片理解没做”的情况：工作流没有崩，但模型增强层降级，所以文件状态是 `partial_success`。

### Chunking 有无 overlap

当前版本没有默认 overlap，主要是工程取舍。这个系统已经提供 blocks 人工校正、chunks 入库前编辑和 `ingest_enabled` 开关，用户可以逐个检查切片是否适合入库。默认 overlap 会让同一段内容重复进入向量库，增加存储、召回噪声和后续答案重复风险。所以第一版先采用可解释的结构化切分：优先按 `title/paragraph/table/image` block 边界切，超长段落先按句号、问号、分号、换行等自然边界拆，实在找不到边界才按字符数硬切。后续如果实际召回不足，再把 overlap 做成可配置参数。

### 为什么要支持导出 blocks/chunks

导出能力让 DocAgent 不只是一个本地查看工具，而是可以作为其它系统的数据预处理模块。用户人工校正后的 blocks 可以交给标注平台、审查系统或其它结构化处理流程；编辑后的 chunks 可以导出为 JSONL，交给外部向量库或批处理任务。JSON 保留完整结构，适合归档和接口对接；JSONL 一行一条记录，更适合数据管道和 RAG 入库。

### 为什么选 Chroma 本地向量库

Chroma 不需要额外数据库服务，适合本地演示和轻量部署，可以把向量持久化到 `data/vector_store/chroma/`。它比纯内存检索更接近真实入库流程，又比 pgvector、Milvus 这类服务型方案部署成本低。后续如果要生产化，可以把 Knowledge Service 的向量库实现替换成 pgvector 或 Milvus，上层 API 不需要大改。

### 为什么不用模型直接解析整个 Word

因为 Word 的结构解析是确定性任务，用 parser 更稳定、可控、便宜。模型更适合语义理解，例如作者时间抽取、图片描述和摘要生成。

### 把 Word 后缀改成 PDF 会怎样

系统不会只相信后缀名。Router 仍按扩展名做第一层分流，但 Parser Tool 在调用具体 parser 前会做轻量文件头校验。例如 `.pdf` 必须以 `%PDF-` 开头，`.docx` 必须是包含 `word/document.xml` 的 OOXML 压缩包。如果 Word 被改成 `.pdf`，会返回“扩展名为 .pdf，但文件内容不是有效 PDF”的明确失败信息，而不是把底层 PyMuPDF 异常直接暴露出来。

# 相关文档

- FastAPI：[https://fastapi.tiangolo.com/zh/](https://fastapi.tiangolo.com/zh/)

- LangGraph：[https://docs.langchain.com/oss/python/langgraph/overview](https://docs.langchain.com/oss/python/langgraph/overview) 
