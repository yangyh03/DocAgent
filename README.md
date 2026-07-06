# DocAgent

> Copyright (c) 2026 yangyh03. All rights reserved.
>
> 本项目源码可公开阅读、学习和参考，但禁止移除署名、包装成他人原创项目或未经许可进行商业化/二次发布。详见 `LICENSE`。

DocAgent 是一个基于 FastAPI 和 LangGraph 的**多模态文档解析与行业知识库构建系统**。系统可以把 Word、PDF、HTML、浏览器保存网页包和图片统一解析成结构化结果，再生成面向知识库入库的切片，支持人工校正、构建本地 Chroma 向量索引和任务级问答。

它更准确的定位是：**基于 Agent Workflow 的多模态文档解析、入库前治理与行业知识库构建系统**。

## 主要能力

- **多格式上传解析**：支持 DOCX、PDF、HTML/HTM、浏览器保存网页 ZIP 和常见位图图片。
- **统一结构输出**：输出 `blocks`、`fileContent`、`assets`、`chunks`、`metadata`、`qualityHints`、`agentTrace`、`runtimeMetrics`。
- **工作流编排**：通过 LangGraph 串联路由、解析、元信息抽取、图片理解、结果标准化和 RAG 切片。
- **图片理解**：图片 block 可以交给 VLM 生成描述、提取图片文字和判断图片作用。
- **扫描 PDF 兜底**：无文本层 PDF 页面会渲染为图片，并作为 OCR 候选交给 Vision Agent。
- **人工校正**：前端可编辑结构块和知识库切片，可控制 chunk 是否参与入库。
- **本地知识库**：使用 Chroma 持久化向量库，每个任务一个 collection。
- **知识库问答**：构建索引后可围绕当前任务文档提问；未配置 QA 模型时可返回检索片段。
- **可观测性**：通过质量提示、执行轨迹和运行指标解释解析质量、降级原因和模型调用情况。
- **系统说明页**：`/system` 页面会读取 `app/static/system.md`，用于展示更完整的使用说明和字段解释。

## 支持格式

| 类型             | 后缀                                                                              |
| ---------------- | --------------------------------------------------------------------------------- |
| Word             | `.docx`                                                                         |
| PDF              | `.pdf`                                                                          |
| HTML             | `.html`, `.htm`                                                               |
| 浏览器保存网页包 | `.zip`                                                                          |
| 图片             | `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`, `.tif`, `.tiff` |

ZIP 只按浏览器保存网页包处理，不作为通用压缩包处理。

暂不支持 `.svg`、`.ico`、`.heic`、`.raw`、`.psd`、`.txt` 等格式。

## 快速启动

建议使用 Python 3.13 版本。

```powershell
cd "DocAgent"

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

启动后访问：

```text
前端工作台：http://127.0.0.1:8001/
系统说明页：http://127.0.0.1:8001/system
API Docs：http://127.0.0.1:8001/docs
健康检查：http://127.0.0.1:8001/health
```

## Docker 部署

项目提供 `Dockerfile`，会封装后端服务、静态前端、运行依赖和默认数据目录。构建镜像：

```powershell
docker build -t docagent:latest .
```

也可以直接用 Docker Compose 启动。先复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

然后按需修改 `.env` 中的模型 API key、模型名和端口配置，启动服务：

```powershell
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

如果不使用 Docker Compose，也可以直接启动容器：

```powershell
docker run --rm -p 8001:8001 `
  -v ${PWD}\data:/app/data `
  --env-file .env `
  docagent:latest
```

实际部署时，请复制 `.env.example` 并填入真实模型 API key。`/app/data` 用于保存上传文件、图片资源和 Chroma 向量库数据，建议通过 volume 挂载到宿主机。

## 模型配置

系统支持 OpenAI-compatible 的模型服务，当前建议配置 [www.aliyun.com/product/tongyi](https://www.aliyun.com/product/tongyi) 平台下**多模态大模型和向量模型**。可在 app\config.py 中进行配置，也可修改系统环境变量：

```powershell
$env:DASHSCOPE_API_KEY="你的 API Key"
$env:DASHSCOPE_BASE_URL="你的 LLM Base URL"
$env:LLM_MODEL="qwen3-vl-flash"
```

Embedding 和 QA 默认也复用 `DASHSCOPE_API_KEY` 与 `DASHSCOPE_BASE_URL`。

> 如果没有配置真实 API key，系统仍可完成基础解析，但 metadata、vision、embedding 或 QA 可能降级、跳过或返回明确错误。

## 环境变量

| 变量                              | 默认值                                         | 作用                                   |
| --------------------------------- | ---------------------------------------------- | -------------------------------------- |
| `DOCAGENT_DATA_DIR`             | `data`                                       | 上传文件、任务资源和默认向量库数据目录 |
| `DOCAGENT_MAX_UPLOAD_MB`        | `100`                                        | 单次上传大小限制                       |
| `DASHSCOPE_API_KEY`             | `EMPTY`                                      | LLM/VLM/Embedding API key              |
| `DASHSCOPE_BASE_URL`            | `https://api.openai.com/v1/chat/completions` | OpenAI-compatible 服务地址             |
| `LLM_MODEL`                     | `qwen3-vl-flash`                             | 元信息抽取、图片理解和问答模型         |
| `METADATA_ENABLED`              | `true`                                       | 是否启用元信息抽取                     |
| `VISION_ENABLED`                | `true`                                       | 是否启用图片理解                       |
| `EMBEDDING_ENABLED`             | `true`                                       | 是否启用向量化和索引构建               |
| `QA_ENABLED`                    | `true`                                       | 是否启用 LLM 生成回答                  |
| `EMBEDDING_MODEL`               | `text-embedding-v4`                          | Embedding 模型                         |
| `EMBEDDING_BATCH_SIZE`          | `10`                                         | Embedding 批大小，系统会限制最大为 10  |
| `VECTOR_STORE_DIR`              | `data/vector_store/chroma`                   | Chroma 持久化目录                      |
| `MODEL_TIMEOUT_SECONDS`         | `60`                                         | 模型调用超时时间                       |
| `MODEL_RETRY_TIMES`             | `1`                                          | 模型调用重试次数                       |
| `VISION_MAX_IMAGES_PER_FILE`    | `20`                                         | 单文件最多理解图片数                   |
| `REMOTE_IMAGE_DOWNLOAD_ENABLED` | `true`                                       | HTML 网络图片是否下载到本地 assets     |
| `REMOTE_IMAGE_TIMEOUT_SECONDS`  | `10`                                         | 网络图片下载超时                       |
| `REMOTE_IMAGE_MAX_MB`           | `10`                                         | 单张网络图片最大下载大小               |
| `HTML_ARCHIVE_MAX_FILES`        | `1000`                                       | HTML ZIP 最大文件数                    |
| `HTML_ARCHIVE_MAX_FILE_MB`      | `50`                                         | HTML ZIP 单文件最大大小                |
| `HTML_ARCHIVE_MAX_TOTAL_MB`     | `200`                                        | HTML ZIP 解压总大小限制                |

布尔型环境变量中，`false`、`0`、`no`、`off` 会被识别为关闭，其余通常视为开启。

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

## 结果字段说明

每个文件结果通常包含：

| 字段               | 含义                                     |
| ------------------ | ---------------------------------------- |
| `fileName`       | 文件名                                   |
| `fileType`       | 文件类型                                 |
| `fileContent`    | 由 blocks 渲染出的正文                   |
| `fileSource`     | 上传时填写的来源系统                     |
| `status`         | 当前文件处理状态                         |
| `errorMessage`   | 失败原因                                 |
| `metadata`       | 作者、发布时间、机构、主题、摘要等元信息 |
| `blocks`         | 结构化文档块                             |
| `assets`         | 图片等资源                               |
| `chunks`         | 面向知识库入库的切片                     |
| `qualityHints`   | 质量提示和降级说明                       |
| `agentTrace`     | 工作流节点执行轨迹                       |
| `runtimeMetrics` | 模型调用和耗时统计                       |

`blocks` 的主要类型：

| 类型          | 含义 |
| ------------- | ---- |
| `title`     | 标题 |
| `paragraph` | 段落 |
| `table`     | 表格 |
| `image`     | 图片 |

## 状态语义

| 状态                | 含义                                                                   |
| ------------------- | ---------------------------------------------------------------------- |
| `success`         | 基础解析和必要增强完成                                                 |
| `partial_success` | 基础解析成功，但模型、图片理解、embedding 或 QA 有降级、pending 或失败 |
| `failed`          | 基础解析失败，例如格式不支持、文件签名校验失败或文件损坏               |

例如：上传图片但没有配置 VLM 时，系统应返回 `partial_success`，图片描述会标记为 pending。

## 常用 API

| 方法      | 路径                                                                | 说明                   |
| --------- | ------------------------------------------------------------------- | ---------------------- |
| `POST`  | `/api/documents/analyze`                                          | 上传文件并创建解析任务 |
| `GET`   | `/api/documents/tasks/{task_id}`                                  | 查询任务状态           |
| `GET`   | `/api/documents/tasks/{task_id}/result`                           | 获取任务结果           |
| `PATCH` | `/api/documents/tasks/{task_id}/result/files/{file_index}/blocks` | 保存结构块校正         |
| `PATCH` | `/api/documents/tasks/{task_id}/result/files/{file_index}/chunks` | 保存知识库切片校正     |
| `GET`   | `/api/documents/tasks/{task_id}/result/files/{file_index}/export` | 导出 blocks/chunks     |
| `POST`  | `/api/documents/tasks/{task_id}/knowledge/index`                  | 构建或重建知识库索引   |
| `GET`   | `/api/documents/tasks/{task_id}/knowledge/index`                  | 查询索引状态           |
| `POST`  | `/api/documents/tasks/{task_id}/knowledge/ask`                    | 知识库问答             |
| `GET`   | `/api/documents/tasks/{task_id}/assets/{file_name}`               | 访问任务图片资源       |

导出接口支持：

```text
target=blocks|chunks|both
format=json|jsonl
```

示例：

```text
/api/documents/tasks/{task_id}/result/files/0/export?target=chunks&format=jsonl
```

## 数据存储

默认数据目录：

```text
data/
```

常见子目录：

```text
data/tasks/{task_id}/
data/tasks/{task_id}/assets/
data/vector_store/chroma/
```

注意：当前任务结果主要保存在内存中，服务重启后任务状态和任务结果可能丢失。上传文件、assets 和 Chroma 向量库数据会按配置目录落盘。

## 常见问题

**1. 端口 8001 启动失败怎么办？**

换一个端口，例如 `8010`：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

**2. 为什么 metadata 或图片描述是 pending？**

通常是没有配置模型 API key、关闭了相关功能开关，或模型调用失败。基础解析成功时，系统会尽量返回 `partial_success`，并在 `qualityHints`、`agentTrace`、`runtimeMetrics` 中说明原因。

**3. 为什么构建知识库索引失败？**

常见原因是没有配置 embedding API key、没有可入库 chunk，或 Chroma 目录权限异常。先确认 `EMBEDDING_ENABLED=true`、`DASHSCOPE_API_KEY` 有效，并且至少有一个 chunk 的 `ingest_enabled` 不是 `false`。

**4. 保存 chunks 后会自动更新索引吗？**

不会。保存 chunks 只修改当前任务结果，需要手动点击“构建/重建索引”。

**5. 原始 JSON 字段导出和 blocks/chunks 导出有什么区别？**

结构块和知识库切片导出走后端标准导出接口，支持 JSON 和 JSONL。原始 JSON 字段选择导出是前端本地裁剪当前文件结果，适合调试和只导出部分字段。

更完整的使用说明、字段解释和常见问题可在系统启动后访问 `/system` 查看。

## 项目边界

DocAgent 不是通用 OCR 平台，也不是复杂多智能体自治系统。它的核心是围绕多模态文档解析、结构化治理和行业知识库入库构建的工作流式 AI 应用。

当前更适合用于：

- 多格式文档结构化解析
- 行业知识库入库前处理
- 文档结构化与人工校正流程
- AI 应用工程、模型降级和可观测性展示

## 版权与许可

- Logo 和前端版权署名保留为 `yangyh03`。
- 允许阅读、学习和参考，禁止去署名包装为他人原创项目或未经许可商业化/二次发布。
