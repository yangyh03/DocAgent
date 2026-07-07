const state = {
  taskId: "",
  task: null,
  result: null,
  selectedIndex: 0,
  pollTimer: null,
  visibleBlockTypes: new Set(["title", "paragraph", "table", "image"]),
  editingBlocks: false,
  draftBlocks: [],
  editingChunks: false,
  draftChunks: [],
  indexStatus: null,
  qaAnswer: "",
  qaSources: [],
  recentTasks: [],
  selectedRecentTaskIds: new Set(),
  deletingRecentTasks: false,
  jsonExportFields: new Set(),
  jsonExportAll: false,
  jsonAdvancedFieldsVisible: false,
};

const SUPPORTED_EXTENSIONS = new Set([
  ".docx",
  ".pdf",
  ".html",
  ".htm",
  ".zip",
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".bmp",
  ".gif",
  ".tif",
  ".tiff",
]);

const JSON_EXPORT_TREE = [
  {
    id: "basic",
    label: "文件基础信息",
    fields: [
      ["fileName", "文件名"],
      ["fileType", "文件类型"],
      ["createDate", "创建日期"],
      ["status", "文件状态"],
      ["errorMessage", "失败原因"],
      ["fileSource", "来源系统"],
      ["fileUrl", "文件地址", "本地路径，默认不导出"],
    ],
  },
  {
    id: "content",
    label: "正文内容",
    fields: [["fileContent", "正文文本"]],
  },
  {
    id: "metadata",
    label: "元信息",
    fields: [
      ["metadata.author", "作者"],
      ["metadata.posted_time", "发布时间"],
      ["metadata.organization", "机构"],
      ["metadata.topic", "主题"],
      ["metadata.summary", "摘要"],
      ["metadata.extraction_mode", "抽取模式"],
      ["metadata", "metadata 完整对象", "高级：包含 parser/LLM 产生的所有元信息", true],
    ],
  },
  {
    id: "blocks",
    label: "结构块 blocks",
    fields: [
      ["blocks.type", "block 类型"],
      ["blocks.content", "block 内容"],
      ["blocks.metadata.source", "来源"],
      ["blocks.metadata.page_number", "页码"],
      ["blocks.metadata.description", "图片描述"],
      ["blocks.metadata.extracted_text", "图片文字"],
      ["blocks.metadata.image_role", "图片作用"],
      ["blocks.metadata.vision_status", "视觉状态"],
      ["blocks.metadata.ocr_candidate", "OCR 候选"],
      ["blocks.metadata.row_count", "表格行数"],
      ["blocks.metadata.column_count", "表格列数"],
      ["blocks.metadata.rows", "表格 rows"],
      ["blocks.metadata.path", "图片本地路径", "本地路径，默认不导出"],
    ],
  },
  {
    id: "assets",
    label: "资源 assets",
    fields: [
      ["assets.file_name", "资源文件名"],
      ["assets.mime_type", "MIME 类型"],
      ["assets.path", "资源本地路径", "本地路径，默认不导出"],
    ],
  },
  {
    id: "chunks",
    label: "知识库切片 chunks",
    fields: [
      ["chunks.chunk_id", "切片 ID"],
      ["chunks.content", "切片内容"],
      ["chunks.metadata.block_types", "来源 block 类型"],
      ["chunks.metadata.source_file", "来源文件"],
      ["chunks.metadata.page_number", "页码"],
      ["chunks.metadata.asset_refs", "资源引用"],
      ["chunks.metadata.chunk_index", "切片序号"],
      ["chunks.metadata.char_count", "字符数"],
      ["chunks.metadata.heading_path", "标题路径"],
      ["chunks.metadata.ingest_enabled", "是否参与入库"],
      ["chunks.metadata.edited", "是否人工编辑"],
      ["chunks.metadata.edit_source", "编辑来源"],
      ["chunks.metadata", "切片 metadata 完整对象", "高级：保留全部入库附加信息", true],
    ],
  },
  {
    id: "debug",
    label: "质量与调试",
    fields: [
      ["qualityHints.level", "质量级别"],
      ["qualityHints.code", "质量代码"],
      ["qualityHints.message", "质量提示"],
      ["agentTrace.node", "执行节点"],
      ["agentTrace.status", "节点状态"],
      ["agentTrace.duration_ms", "节点耗时"],
      ["agentTrace.fallback_used", "节点是否降级"],
      ["agentTrace.message", "节点说明"],
      ["agentTrace.error", "节点错误"],
      ["runtimeMetrics.model_call_count", "模型调用次数"],
      ["runtimeMetrics.success_count", "模型成功次数"],
      ["runtimeMetrics.failed_count", "模型失败次数"],
      ["runtimeMetrics.fallback_count", "模型降级次数"],
      ["runtimeMetrics.total_duration_ms", "模型总耗时"],
      ["runtimeMetrics.by_stage", "按阶段汇总", "高级：按 metadata/vision/embedding/qa 聚合", true],
      ["runtimeMetrics.events.stage", "模型事件阶段", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.model_type", "模型类型", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.model", "模型名称", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.status", "模型事件状态", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.duration_ms", "模型事件耗时", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.fallback_used", "模型事件是否降级", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.input_items", "模型输入数量", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.output_items", "模型输出数量", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.error", "模型错误", "高级：单次模型事件明细", true],
      ["runtimeMetrics.events.details", "模型事件 details", "高级：单次模型事件明细", true],
      ["qualityHints", "qualityHints 完整数组", "高级：质量提示完整结构", true],
      ["agentTrace", "agentTrace 完整数组", "高级：工作流完整轨迹", true],
      ["runtimeMetrics", "runtimeMetrics 完整对象", "高级：模型运行指标完整结构", true],
    ],
  },
];

const JSON_EXPORT_PRESETS = {
  business: [
    "fileName",
    "fileType",
    "createDate",
    "status",
    "fileContent",
    "metadata.author",
    "metadata.posted_time",
    "metadata.organization",
    "metadata.topic",
    "metadata.summary",
    "metadata.extraction_mode",
    "blocks.type",
    "blocks.content",
    "blocks.metadata.source",
    "blocks.metadata.page_number",
    "blocks.metadata.description",
    "blocks.metadata.extracted_text",
    "blocks.metadata.image_role",
    "blocks.metadata.vision_status",
    "blocks.metadata.ocr_candidate",
    "blocks.metadata.row_count",
    "blocks.metadata.column_count",
    "blocks.metadata.rows",
    "assets.file_name",
    "assets.mime_type",
  ],
  rag: [
    "fileName",
    "fileType",
    "metadata.topic",
    "metadata.summary",
    "metadata.author",
    "metadata.posted_time",
    "chunks.chunk_id",
    "chunks.content",
    "chunks.metadata.block_types",
    "chunks.metadata.source_file",
    "chunks.metadata.page_number",
    "chunks.metadata.asset_refs",
    "chunks.metadata.chunk_index",
    "chunks.metadata.char_count",
    "chunks.metadata.heading_path",
    "chunks.metadata.ingest_enabled",
  ],
  debug: ["*"],
};

const $ = (id) => document.getElementById(id);

const els = {
  fileInput: $("fileInput"),
  fileSummary: $("fileSummary"),
  serverSource: $("serverSource"),
  uploadButton: $("uploadButton"),
  refreshButton: $("refreshButton"),
  taskId: $("taskId"),
  taskIdCopy: $("taskIdCopy"),
  taskStatus: $("taskStatus"),
  recentTasksCount: $("recentTasksCount"),
  recentTaskSelectAll: $("recentTaskSelectAll"),
  recentTaskDeleteButton: $("recentTaskDeleteButton"),
  recentTaskList: $("recentTaskList"),
  progressPanel: $("progressPanel"),
  progressPercent: $("progressPercent"),
  progressCount: $("progressCount"),
  progressBar: $("progressBar"),
  progressStep: $("progressStep"),
  progressFile: $("progressFile"),
  pollState: $("pollState"),
  fileCount: $("fileCount"),
  fileList: $("fileList"),
  currentTitle: $("currentTitle"),
  metricBlocks: $("metricBlocks"),
  metricChunks: $("metricChunks"),
  metricAssets: $("metricAssets"),
  metricTrace: $("metricTrace"),
  alertBox: $("alertBox"),
  overviewList: $("overviewList"),
  qualityHints: $("qualityHints"),
  contentView: $("contentView"),
  blocksView: $("blocksView"),
  blockFilterSummary: $("blockFilterSummary"),
  editBlocksButton: $("editBlocksButton"),
  saveBlocksButton: $("saveBlocksButton"),
  cancelBlocksButton: $("cancelBlocksButton"),
  exportBlocksJsonButton: $("exportBlocksJsonButton"),
  exportBlocksJsonlButton: $("exportBlocksJsonlButton"),
  chunksView: $("chunksView"),
  editChunksButton: $("editChunksButton"),
  saveChunksButton: $("saveChunksButton"),
  cancelChunksButton: $("cancelChunksButton"),
  exportChunksJsonButton: $("exportChunksJsonButton"),
  exportChunksJsonlButton: $("exportChunksJsonlButton"),
  buildIndexButton: $("buildIndexButton"),
  indexStatusList: $("indexStatusList"),
  indexStatusNote: $("indexStatusNote"),
  qaBuildIndexButton: $("qaBuildIndexButton"),
  questionInput: $("questionInput"),
  topKInput: $("topKInput"),
  askButton: $("askButton"),
  answerView: $("answerView"),
  sourceView: $("sourceView"),
  runtimeSummary: $("runtimeSummary"),
  runtimeEvents: $("runtimeEvents"),
  traceView: $("traceView"),
  jsonView: $("jsonView"),
  openJsonFieldExportButton: $("openJsonFieldExportButton"),
  copyJsonButton: $("copyJsonButton"),
  jsonExportDialog: $("jsonExportDialog"),
  jsonFieldTree: $("jsonFieldTree"),
  jsonExportSummary: $("jsonExportSummary"),
  toggleJsonAdvancedButton: $("toggleJsonAdvancedButton"),
  closeJsonExportButton: $("closeJsonExportButton"),
  cancelJsonExportButton: $("cancelJsonExportButton"),
  confirmJsonExportButton: $("confirmJsonExportButton"),
};

els.fileInput.addEventListener("change", () => {
  const files = Array.from(els.fileInput.files || []);
  if (!files.length) {
    els.fileSummary.textContent = "可多选，结果按文件切换";
    return;
  }
  const unsupported = findUnsupportedFiles(files);
  const names = files.slice(0, 2).map((file) => file.name).join("、");
  els.fileSummary.textContent = files.length > 2 ? `${names} 等 ${files.length} 个文件` : names;
  if (unsupported.length) {
    showAlert(`暂不支持：${unsupported.map((file) => file.name).join("、")}`);
  } else {
    clearAlert();
  }
});

els.uploadButton.addEventListener("click", uploadDocuments);
els.refreshButton.addEventListener("click", () => {
  if (state.taskId) pollTask(true);
});

els.taskIdCopy.addEventListener("click", copyTaskId);
els.editBlocksButton.addEventListener("click", startBlockEditing);
els.saveBlocksButton.addEventListener("click", saveBlockCorrections);
els.cancelBlocksButton.addEventListener("click", cancelBlockEditing);
els.exportBlocksJsonButton.addEventListener("click", () => exportCurrentFile("blocks", "json"));
els.exportBlocksJsonlButton.addEventListener("click", () => exportCurrentFile("blocks", "jsonl"));
els.editChunksButton.addEventListener("click", startChunkEditing);
els.saveChunksButton.addEventListener("click", saveChunkCorrections);
els.cancelChunksButton.addEventListener("click", cancelChunkEditing);
els.exportChunksJsonButton.addEventListener("click", () => exportCurrentFile("chunks", "json"));
els.exportChunksJsonlButton.addEventListener("click", () => exportCurrentFile("chunks", "jsonl"));
els.buildIndexButton.addEventListener("click", buildKnowledgeIndex);
els.qaBuildIndexButton.addEventListener("click", buildKnowledgeIndex);
els.askButton.addEventListener("click", askKnowledge);
els.openJsonFieldExportButton.addEventListener("click", openJsonFieldExportDialog);
els.copyJsonButton.addEventListener("click", copyCurrentJson);
els.closeJsonExportButton.addEventListener("click", closeJsonFieldExportDialog);
els.cancelJsonExportButton.addEventListener("click", closeJsonFieldExportDialog);
els.confirmJsonExportButton.addEventListener("click", exportSelectedJson);
els.toggleJsonAdvancedButton.addEventListener("click", toggleJsonAdvancedFields);
els.recentTaskSelectAll.addEventListener("change", toggleAllRecentTasks);
els.recentTaskDeleteButton.addEventListener("click", deleteSelectedRecentTasks);
els.recentTaskList.addEventListener("click", (event) => {
  const checkbox = event.target.closest("[data-recent-task-check]");
  if (checkbox) {
    toggleRecentTaskSelection(checkbox.dataset.recentTaskCheck, checkbox.checked);
    return;
  }
  const button = event.target.closest("[data-recent-task-id]");
  if (button) restoreRecentTask(button.dataset.recentTaskId);
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

document.querySelectorAll(".block-filter").forEach((input) => {
  input.addEventListener("change", () => {
    state.visibleBlockTypes = new Set(
      Array.from(document.querySelectorAll(".block-filter:checked")).map((item) => item.value),
    );
    renderBlocks(currentFile()?.blocks || []);
  });
});

document.querySelectorAll("[data-json-preset]").forEach((button) => {
  button.addEventListener("click", () => applyJsonExportPreset(button.dataset.jsonPreset));
});

els.jsonExportDialog.addEventListener("click", (event) => {
  if (event.target === els.jsonExportDialog) closeJsonFieldExportDialog();
});

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab-view").forEach((view) => {
    view.classList.toggle("active", view.id === `tab-${name}`);
  });
}

async function uploadDocuments() {
  const files = Array.from(els.fileInput.files || []);
  if (!files.length) {
    showAlert("请先选择要解析的文件。");
    return;
  }
  const unsupported = findUnsupportedFiles(files);
  if (unsupported.length) {
    showAlert(`暂不支持这些文件格式：${unsupported.map((file) => file.name).join("、")}。请上传 DOCX、PDF、HTML、HTML ZIP 网页包或常见位图图片。`);
    return;
  }

  clearAlert();
  setBusy(true);
  const form = new FormData();
  files.forEach((file) => form.append("multiFiles", file));
  form.append("serverSource", els.serverSource.value.trim() || "frontend-demo");

  try {
    const response = await fetch("/api/documents/analyze", {
      method: "POST",
      body: form,
    });
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
  state.taskId = payload.task_id;
  state.result = null;
  state.indexStatus = null;
  state.qaAnswer = "";
  state.qaSources = [];
    state.selectedIndex = 0;
    renderTask({ task_id: payload.task_id, status: payload.status, message: payload.message });
    await loadRecentTasks();
    renderEmptyResult("任务已提交，正在解析。");
    startPolling();
  } catch (error) {
    showAlert(`上传失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function startPolling() {
  stopPolling();
  els.pollState.textContent = "polling";
  pollTask();
  state.pollTimer = window.setInterval(() => pollTask(), 1000);
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  els.pollState.textContent = "idle";
}

async function pollTask(manual = false) {
  if (!state.taskId) {
    if (manual) showAlert("当前没有可刷新的任务。");
    return;
  }
  try {
    const response = await fetch(`/api/documents/tasks/${state.taskId}`);
    if (!response.ok) throw new Error(await response.text());
    const task = await response.json();
    state.task = task;
    renderTask(task);
    if (["success", "partial_success", "failed"].includes(task.status)) {
      stopPolling();
      await fetchResult();
    }
  } catch (error) {
    stopPolling();
    showAlert(`查询任务失败：${error.message}`);
  }
}

async function fetchResult() {
  const response = await fetch(`/api/documents/tasks/${state.taskId}/result`);
  if (!response.ok) {
    showAlert(`查询结果失败：${await response.text()}`);
    return;
  }
  state.result = await response.json();
  state.selectedIndex = 0;
  renderTask({
    task_id: state.result.task_id || state.taskId,
    status: state.result.status,
    message: state.result.message,
    progress: fallbackProgress(state.result),
  });
  renderFileList();
  renderCurrentFile();
  await loadRecentTasks();
  await fetchIndexStatus();
}

async function loadRecentTasks() {
  try {
    const response = await fetch("/api/documents/tasks?limit=20");
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    state.recentTasks = payload.items || [];
    const availableIds = new Set(state.recentTasks.map((task) => task.task_id));
    state.selectedRecentTaskIds = new Set(
      Array.from(state.selectedRecentTaskIds).filter((taskId) => availableIds.has(taskId)),
    );
    renderRecentTasks();
  } catch (error) {
    state.recentTasks = [];
    state.selectedRecentTaskIds.clear();
    renderRecentTasks(`历史任务加载失败：${error.message}`);
  }
}

function renderRecentTasks(message = "") {
  const tasks = state.recentTasks || [];
  els.recentTasksCount.textContent = `${tasks.length} tasks`;
  if (message) {
    els.recentTaskList.className = "recent-task-list empty";
    els.recentTaskList.textContent = message;
    updateRecentTaskDeleteActions();
    return;
  }
  if (!tasks.length) {
    els.recentTaskList.className = "recent-task-list empty";
    els.recentTaskList.textContent = "暂无历史任务";
    updateRecentTaskDeleteActions();
    return;
  }
  els.recentTaskList.className = "recent-task-list";
  els.recentTaskList.innerHTML = tasks
    .map((task) => {
      const active = task.task_id === state.taskId ? " active" : "";
      const checked = state.selectedRecentTaskIds.has(task.task_id) ? " checked" : "";
      const fileNames = Array.isArray(task.file_names) && task.file_names.length ? task.file_names.join("、") : `${task.file_count || 0} files`;
      return `
        <div class="recent-task-item${active}">
          <label class="recent-task-check" title="选择任务">
            <input type="checkbox" data-recent-task-check="${escapeHtml(task.task_id)}"${checked} />
          </label>
          <button class="recent-task-open" type="button" data-recent-task-id="${escapeHtml(task.task_id)}">
            <span class="recent-task-main">
              <strong>${escapeHtml(fileNames)}</strong>
              <small>${escapeHtml(shortTaskId(task.task_id))} · ${escapeHtml(formatDateTime(task.updated_at))}</small>
            </span>
            <span class="status-badge ${escapeHtml(task.status || "")}">${escapeHtml(formatStatus(task.status))}</span>
          </button>
        </div>
      `;
    })
    .join("");
  updateRecentTaskDeleteActions();
}

function toggleRecentTaskSelection(taskId, checked) {
  if (!taskId) return;
  if (checked) {
    state.selectedRecentTaskIds.add(taskId);
  } else {
    state.selectedRecentTaskIds.delete(taskId);
  }
  updateRecentTaskDeleteActions();
}

function toggleAllRecentTasks() {
  const taskIds = (state.recentTasks || []).map((task) => task.task_id).filter(Boolean);
  if (els.recentTaskSelectAll.checked) {
    state.selectedRecentTaskIds = new Set(taskIds);
  } else {
    state.selectedRecentTaskIds.clear();
  }
  renderRecentTasks();
}

function updateRecentTaskDeleteActions() {
  const tasks = state.recentTasks || [];
  const taskIds = new Set(tasks.map((task) => task.task_id));
  const selectedCount = Array.from(state.selectedRecentTaskIds).filter((taskId) => taskIds.has(taskId)).length;
  els.recentTaskSelectAll.disabled = !tasks.length || state.deletingRecentTasks;
  els.recentTaskSelectAll.checked = tasks.length > 0 && selectedCount === tasks.length;
  els.recentTaskSelectAll.indeterminate = selectedCount > 0 && selectedCount < tasks.length;
  els.recentTaskDeleteButton.disabled = selectedCount === 0 || state.deletingRecentTasks;
  els.recentTaskDeleteButton.textContent = selectedCount > 0 ? `删除选中 (${selectedCount})` : "删除选中";
}

async function deleteSelectedRecentTasks() {
  const taskIds = Array.from(state.selectedRecentTaskIds);
  if (!taskIds.length) {
    showAlert("请先选择要删除的历史任务。");
    return;
  }
  const confirmed = window.confirm(`确定删除选中的 ${taskIds.length} 个历史任务吗？对应任务文件和知识库索引也会被清理。`);
  if (!confirmed) return;

  state.deletingRecentTasks = true;
  updateRecentTaskDeleteActions();
  const deletingCurrentTask = taskIds.includes(state.taskId);
  try {
    const failures = [];
    await Promise.all(
      taskIds.map(async (taskId) => {
        const response = await fetch(`/api/documents/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
        if (!response.ok) failures.push(`${shortTaskId(taskId)}: ${await response.text()}`);
      }),
    );
    state.selectedRecentTaskIds.clear();
    if (deletingCurrentTask) resetCurrentTaskAfterDeletion();
    await loadRecentTasks();
    if (failures.length) {
      showAlert(`部分任务删除失败：${failures.join("；")}`);
    } else {
      showAlert("选中的历史任务已删除。");
    }
  } catch (error) {
    showAlert(`删除历史任务失败：${error.message}`);
  } finally {
    state.deletingRecentTasks = false;
    updateRecentTaskDeleteActions();
  }
}

function resetCurrentTaskAfterDeletion() {
  stopPolling();
  state.taskId = "";
  state.task = null;
  state.result = null;
  state.selectedIndex = 0;
  state.indexStatus = null;
  state.qaAnswer = "";
  state.qaSources = [];
  renderTask({ task_id: "", status: "unknown", progress: {} });
  renderFileList();
  renderEmptyResult("当前任务已删除。");
}

async function restoreRecentTask(taskId) {
  if (!taskId) return;
  stopPolling();
  state.taskId = taskId;
  state.result = null;
  state.indexStatus = null;
  state.qaAnswer = "";
  state.qaSources = [];
  state.selectedIndex = 0;
  clearAlert();
  renderEmptyResult("正在恢复历史任务。");
  try {
    const response = await fetch(`/api/documents/tasks/${encodeURIComponent(taskId)}`);
    if (!response.ok) throw new Error(await response.text());
    const task = await response.json();
    state.task = task;
    renderTask(task);
    renderRecentTasks();
    if (["success", "partial_success", "failed"].includes(task.status)) {
      await fetchResult();
    } else {
      renderEmptyResult("任务尚未完成，继续轮询状态。");
      startPolling();
    }
  } catch (error) {
    showAlert(`恢复任务失败：${error.message}`);
  }
}

function renderTask(task) {
  const taskId = task.task_id || state.taskId || "";
  els.taskId.textContent = taskId || "-";
  const status = String(task.status || "unknown");
  els.taskStatus.textContent = formatStatus(status);
  els.taskStatus.className = `status-badge ${status}`;
  renderProgress(task.progress || {});
}

function renderFileList() {
  const files = state.result?.data || [];
  els.fileCount.textContent = `${files.length} files`;
  if (!files.length) {
    els.fileList.className = "file-list empty";
    els.fileList.textContent = "暂无结果";
    return;
  }
  els.fileList.className = "file-list";
  els.fileList.innerHTML = files
    .map((file, index) => {
      const active = index === state.selectedIndex ? " active" : "";
      const status = String(file.status || "success");
      return `
        <button class="file-item${active}" type="button" data-index="${index}">
          <span class="file-item-head">
            <strong>${escapeHtml(file.fileName || `文件 ${index + 1}`)}</strong>
            <em class="status-badge ${escapeHtml(status)}">${escapeHtml(formatStatus(status))}</em>
          </span>
          <span class="file-meta">${escapeHtml(fileListMeta(file))}</span>
        </button>
      `;
    })
    .join("");
  els.fileList.querySelectorAll(".file-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedIndex = Number(button.dataset.index);
      cancelBlockEditing();
      cancelChunkEditing();
      renderFileList();
      renderCurrentFile();
    });
  });
}

function renderCurrentFile() {
  const file = currentFile();
  if (!file) {
    renderEmptyResult("暂无解析结果。");
    return;
  }

  els.currentTitle.textContent = displayTitle(file);
  els.metricBlocks.textContent = String(file.blocks?.length || 0);
  els.metricChunks.textContent = String(file.chunks?.length || 0);
  els.metricAssets.textContent = String(file.assets?.length || 0);
  els.metricTrace.textContent = String(file.agentTrace?.length || 0);

  if (file.status === "failed" || state.result?.status === "failed" || file.metadata?.validation_error) {
    showAlert(file.errorMessage || file.metadata?.validation_error || state.result?.message || "解析失败");
  } else {
    clearAlert();
  }

  renderOverview(file);
  renderQualityHints(file);
  els.contentView.textContent = file.fileContent || "暂无正文";
  updateBlockEditorActions();
  renderBlocks(activeBlocks());
  updateChunkEditorActions();
  renderChunks(activeChunks());
  renderKnowledgePanel();
  renderRuntimeMetrics(file);
  renderTrace(file.agentTrace || []);
  els.jsonView.textContent = JSON.stringify(file, null, 2);
}

function renderEmptyResult(message) {
  state.editingBlocks = false;
  state.draftBlocks = [];
  state.editingChunks = false;
  state.draftChunks = [];
  updateBlockEditorActions();
  updateChunkEditorActions();
  els.currentTitle.textContent = "等待解析结果";
  els.metricBlocks.textContent = "0";
  els.metricChunks.textContent = "0";
  els.metricAssets.textContent = "0";
  els.metricTrace.textContent = "0";
  els.overviewList.innerHTML = "";
  els.qualityHints.innerHTML = `<div class="hint">${escapeHtml(message)}</div>`;
  els.contentView.textContent = message;
  els.blocksView.className = "block-list empty";
  els.blocksView.textContent = "暂无结构块";
  if (els.blockFilterSummary) els.blockFilterSummary.textContent = "显示 0 / 0 个结构块";
  els.chunksView.className = "chunk-list empty";
  els.chunksView.textContent = "暂无切片";
  renderKnowledgePanel();
  renderRuntimeMetrics(null);
  els.traceView.innerHTML = "";
  els.jsonView.textContent = state.result ? JSON.stringify(state.result, null, 2) : "暂无 JSON";
}

function renderOverview(file) {
  const metadata = file.metadata || {};
  const rows = [
    ["文件名", file.fileName],
    ["类型", file.fileType],
    ["文件状态", formatStatus(file.status || "success")],
    ["任务状态", formatStatus(state.result?.status || "-")],
    ...(file.status === "failed" && file.errorMessage ? [["失败原因", file.errorMessage]] : []),
    ["创建日期", file.createDate],
    ["文件地址", file.fileUrl, { secret: true }],
    ["图片作用", imageRoleSummary(file)],
    ["主题", metadata.topic],
    ["作者", metadata.author],
    ["发布时间", metadata.posted_time],
    ["机构", metadata.organization],
    ["摘要", metadata.summary],
    ["来源", file.fileSource],
  ];
  els.overviewList.innerHTML = rows
    .filter(([, value]) => shouldShowOverviewValue(value))
    .map(([label, value, options]) => `
      <div>
        <dt>${escapeHtml(label)}</dt>
        <dd>${options?.secret ? renderSecretValue(value) : escapeHtml(value)}</dd>
      </div>
    `)
    .join("");
  els.overviewList.querySelectorAll("[data-secret-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleSecretValue(button));
  });
}

function shouldShowOverviewValue(value) {
  if (value === undefined || value === null) return false;
  const text = String(value).trim();
  return !isUnknownValue(text);
}

function isUnknownValue(value) {
  const text = String(value ?? "").trim();
  return text === "" || text === "未知" || text.toLowerCase() === "unknown";
}

function displayTitle(file) {
  const topic = file?.metadata?.topic;
  if (!isUnknownValue(topic)) return topic;
  if (!isUnknownValue(file?.fileName)) return file.fileName;
  return "解析结果";
}

function fileListMeta(file) {
  const parts = [file.fileType || "UNKNOWN"];
  const topic = file?.metadata?.topic;
  if (!isUnknownValue(topic)) parts.push(topic);
  return parts.join(" · ");
}

function imageRoleSummary(file) {
  if (!isUploadedImageFile(file)) return "";
  const roleLabels = {
    scan_page: "扫描页",
    document_page: "文档页",
    text_page: "文本页",
    screenshot: "截图",
    chart: "图表",
    photo: "照片",
    illustration: "插图",
    diagram: "示意图",
    unknown: "unknown",
  };
  const roles = Array.from(
    new Set(
      (file.blocks || [])
        .filter((block) => block.type === "image")
        .map((block) => String(block.metadata?.image_role || "").trim())
        .filter((role) => role && role !== "unknown"),
    ),
  );
  if (!roles.length) return "";
  return roles.map((role) => roleLabels[role] || role).join("、");
}

function isUploadedImageFile(file) {
  const imageTypes = new Set(["JPG", "JPEG", "PNG", "WEBP", "BMP", "GIF", "TIF", "TIFF"]);
  return imageTypes.has(String(file?.fileType || "").toUpperCase());
}

function renderSecretValue(value) {
  const text = String(value || "");
  return `
    <span class="secret-value" data-secret-text="${escapeHtml(text)}">${escapeHtml(maskSecret(text))}</span>
    <button class="icon-button inline-icon-button" type="button" data-secret-toggle aria-label="显示或隐藏字段" title="显示或隐藏字段">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
        <circle cx="12" cy="12" r="3"></circle>
      </svg>
    </button>
  `;
}

function toggleSecretValue(button) {
  const valueElement = button.parentElement?.querySelector(".secret-value");
  if (!valueElement) return;
  const raw = valueElement.dataset.secretText || "";
  const visible = valueElement.dataset.visible === "true";
  valueElement.textContent = visible ? maskSecret(raw) : raw;
  valueElement.dataset.visible = visible ? "false" : "true";
}

function maskSecret(value) {
  const text = String(value || "");
  if (!text) return "";
  if (text.length <= 12) return "••••••••";
  return `${text.slice(0, 6)}••••••••${text.slice(-6)}`;
}

function renderQualityHints(file) {
  const hints = Array.isArray(file.qualityHints) ? file.qualityHints : [];
  if (!hints.length) {
    els.qualityHints.innerHTML = `<div class="hint">暂无质量提示。</div>`;
    return;
  }
  els.qualityHints.innerHTML = hints
    .map((hint) => {
      const level = hint.level || "info";
      return `
        <div class="hint ${escapeHtml(level)}">
          <strong>${escapeHtml(hint.message || "暂无提示")}</strong>
          <small>${escapeHtml(hint.code || "quality_hint")}</small>
        </div>
      `;
    })
    .join("");
}

function renderBlocks(blocks) {
  const visibleBlocks = blocks.filter((block) => state.visibleBlockTypes.has(block.type || "paragraph"));
  if (els.blockFilterSummary) {
    els.blockFilterSummary.textContent = `显示 ${visibleBlocks.length} / ${blocks.length} 个结构块`;
  }
  if (!blocks.length) {
    els.blocksView.className = "block-list empty";
    els.blocksView.textContent = "暂无结构块";
    return;
  }
  if (!visibleBlocks.length) {
    els.blocksView.className = "block-list empty";
    els.blocksView.textContent = "当前筛选条件下没有结构块";
    return;
  }
  els.blocksView.className = "block-list";
  els.blocksView.innerHTML = visibleBlocks
    .map((block, index) => {
      const content = block.content || block.metadata?.description || "";
      const meta = summarizeMetadata(block.metadata, [
        "level",
        "page_number",
        "file_name",
        "source",
        "image_role",
        "vision_status",
      ]);
      const originalIndex = blocks.indexOf(block) + 1;
      const preview = block.type === "image" ? renderImagePreview(block) : "";
      const editable = state.editingBlocks
        ? `<textarea class="block-editor" data-block-index="${originalIndex - 1}">${escapeHtml(content)}</textarea>`
        : `<div class="item-content">${escapeHtml(content || "空内容")}</div>`;
      const deleteAction = state.editingBlocks
        ? `<button class="ghost-button compact-button danger-button" type="button" data-delete-block="${originalIndex - 1}">删除 block</button>`
        : "";
      return `
        <article class="block-item">
          <div class="item-head">
            <span class="type-badge">${escapeHtml(block.type || "paragraph")}</span>
            <span class="meta-line">#${originalIndex}</span>
          </div>
          ${preview}
          ${editable}
          ${deleteAction}
          ${meta ? `<div class="meta-line">${escapeHtml(meta)}</div>` : ""}
        </article>
      `;
    })
    .join("");
  els.blocksView.querySelectorAll("img[data-preview]").forEach((image) => {
    image.addEventListener("error", () => {
      image.closest(".image-preview")?.classList.add("failed");
    });
  });
  els.blocksView.querySelectorAll(".block-editor").forEach((input) => {
    input.addEventListener("input", () => updateDraftBlockContent(Number(input.dataset.blockIndex), input.value));
  });
  els.blocksView.querySelectorAll("[data-delete-block]").forEach((button) => {
    button.addEventListener("click", () => deleteDraftBlock(Number(button.dataset.deleteBlock)));
  });
}

function renderChunks(chunks) {
  if (!chunks.length) {
    els.chunksView.className = "chunk-list empty";
    els.chunksView.textContent = "暂无切片";
    return;
  }
  els.chunksView.className = "chunk-list";
  els.chunksView.innerHTML = chunks
    .map((chunk) => {
      const metadata = chunk.metadata || {};
      const types = Array.isArray(metadata.block_types) ? metadata.block_types.join(", ") : "-";
      const assetRefs = Array.isArray(metadata.asset_refs) ? metadata.asset_refs.join(", ") : "";
      const index = chunks.indexOf(chunk);
      const ingestEnabled = metadata.ingest_enabled !== false;
      const editor = state.editingChunks
        ? `<textarea class="block-editor" data-chunk-index="${index}">${escapeHtml(chunk.content || "")}</textarea>`
        : `<div class="item-content">${escapeHtml(chunk.content || "空内容")}</div>`;
      const toggle = state.editingChunks
        ? `
          <label class="ingest-toggle">
            <input type="checkbox" data-chunk-ingest="${index}" ${ingestEnabled ? "checked" : ""} />
            参与入库
          </label>
        `
        : `<span class="meta-line">${ingestEnabled ? "参与入库" : "不入库"}</span>`;
      return `
        <article class="chunk-item${ingestEnabled ? "" : " disabled"}">
          <div class="item-head">
            <span class="type-badge">${escapeHtml(chunk.chunk_id || "chunk")}</span>
            <span class="meta-line">${escapeHtml(types)} · ${metadata.char_count || 0} chars</span>
          </div>
          ${toggle}
          ${editor}
          <div class="meta-line">page=${escapeHtml(metadata.page_number ?? "-")} asset_refs=${escapeHtml(assetRefs || "-")}</div>
        </article>
      `;
    })
    .join("");
  els.chunksView.querySelectorAll(".block-editor[data-chunk-index]").forEach((input) => {
    input.addEventListener("input", () => updateDraftChunkContent(Number(input.dataset.chunkIndex), input.value));
  });
  els.chunksView.querySelectorAll("[data-chunk-ingest]").forEach((input) => {
    input.addEventListener("change", () => updateDraftChunkEnabled(Number(input.dataset.chunkIngest), input.checked));
  });
}

function renderKnowledgePanel() {
  const enabledCount = enabledChunkCount();
  const status = state.indexStatus || {
    status: "not_built",
    indexed: false,
    indexed_count: 0,
    skipped_count: 0,
    message: state.taskId ? "索引未构建" : "等待任务结果",
  };
  const rows = [
    ["索引状态", formatIndexStatus(status.status)],
    ["可入库切片", enabledCount],
    ["已入库切片", status.indexed_count ?? 0],
    ["跳过切片", status.skipped_count ?? 0],
    ["最后构建", status.last_built_at || ""],
  ];
  els.indexStatusList.innerHTML = rows
    .filter(([, value]) => shouldShowOverviewValue(value))
    .map(([label, value]) => `
      <div>
        <dt>${escapeHtml(label)}</dt>
        <dd>${escapeHtml(value)}</dd>
      </div>
    `)
    .join("");
  els.indexStatusNote.textContent = status.message || "";
  els.indexStatusNote.title = status.message || "";
  const canIndex = Boolean(state.taskId && enabledCount > 0);
  els.buildIndexButton.disabled = !canIndex;
  els.qaBuildIndexButton.disabled = !canIndex;
  els.askButton.disabled = !state.taskId || !status.indexed;
  els.answerView.textContent = state.qaAnswer || "暂无回答";
  renderSources(state.qaSources || []);
}

function renderSources(sources) {
  if (!sources.length) {
    els.sourceView.className = "source-list empty";
    els.sourceView.textContent = "暂无来源";
    return;
  }
  els.sourceView.className = "source-list";
  els.sourceView.innerHTML = sources
    .map((source, index) => {
      const metadata = source.metadata || {};
      const headingPath = Array.isArray(metadata.heading_path) ? metadata.heading_path.join(" > ") : "";
      return `
        <article class="source-item">
          <div class="item-head">
            <span class="type-badge">source ${index + 1}</span>
            <span class="meta-line">score=${escapeHtml(source.score ?? "-")}</span>
          </div>
          <div class="item-content">${escapeHtml(source.content || "")}</div>
          <div class="meta-line">
            ${escapeHtml(metadata.file_name || "-")} · chunk=${escapeHtml(metadata.chunk_id || "-")} · page=${escapeHtml(metadata.page_number ?? "-")}
          </div>
          ${headingPath ? `<div class="meta-line">${escapeHtml(headingPath)}</div>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderTrace(trace) {
  if (!trace.length) {
    els.traceView.innerHTML = `<tr><td colspan="5">暂无执行轨迹</td></tr>`;
    return;
  }
  els.traceView.innerHTML = trace
    .map((item) => `
      <tr>
        <td><strong>${escapeHtml(item.node || "-")}</strong></td>
        <td><span class="trace-status ${escapeHtml(item.status || "")}">${escapeHtml(formatStatus(item.status || "-"))}</span></td>
        <td>${escapeHtml(String(item.duration_ms ?? 0))} ms</td>
        <td>${item.fallback_used ? "yes" : "no"}</td>
        <td>
          ${escapeHtml(item.message || "")}
          ${item.error ? `<div class="meta-line">${escapeHtml(item.error)}</div>` : ""}
        </td>
      </tr>
    `)
    .join("");
}

function renderRuntimeMetrics(file) {
  const fileMetrics = file?.runtimeMetrics || {};
  const taskMetrics = state.result?.runtimeMetrics || state.task?.runtimeMetrics || {};
  const summaryRows = [
    ["任务模型调用", taskMetrics.model_call_count ?? 0],
    ["任务 fallback", taskMetrics.fallback_count ?? 0],
    ["任务失败调用", taskMetrics.failed_count ?? 0],
    ["任务模型耗时", `${taskMetrics.total_duration_ms ?? 0} ms`],
    ["当前文件调用", fileMetrics.model_call_count ?? 0],
    ["当前文件 fallback", fileMetrics.fallback_count ?? 0],
    ["当前文件失败", fileMetrics.failed_count ?? 0],
    ["当前文件耗时", `${fileMetrics.total_duration_ms ?? 0} ms`],
  ];
  els.runtimeSummary.innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="runtime-kpi">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const events = [
    ...((fileMetrics.events || []).map((event) => ({ ...event, scope: "file" }))),
    ...((taskMetrics.events || [])
      .filter((event) => !isDuplicateRuntimeEvent(event, fileMetrics.events || []))
      .map((event) => ({ ...event, scope: "task" }))),
  ];
  if (!events.length) {
    els.runtimeEvents.className = "runtime-events empty";
    els.runtimeEvents.textContent = "暂无模型调用记录";
    return;
  }
  els.runtimeEvents.className = "runtime-events";
  els.runtimeEvents.innerHTML = events
    .map((event) => `
      <article class="runtime-event">
        <div class="item-head">
          <span class="type-badge">${escapeHtml(runtimeStageLabel(event.stage))}</span>
          <span class="trace-status ${escapeHtml(event.status || "")}">${escapeHtml(formatStatus(event.status || "-"))}</span>
        </div>
        <dl class="runtime-event-grid">
          <div><dt>scope</dt><dd>${escapeHtml(event.scope || "-")}</dd></div>
          <div><dt>model</dt><dd>${escapeHtml(event.model || "-")}</dd></div>
          <div><dt>type</dt><dd>${escapeHtml(event.model_type || "-")}</dd></div>
          <div><dt>duration</dt><dd>${escapeHtml(event.duration_ms ?? 0)} ms</dd></div>
          <div><dt>fallback</dt><dd>${event.fallback_used ? "yes" : "no"}</dd></div>
          <div><dt>items</dt><dd>${escapeHtml(event.input_items ?? 0)} → ${escapeHtml(event.output_items ?? 0)}</dd></div>
        </dl>
        ${event.error ? `<div class="meta-line">${escapeHtml(event.error)}</div>` : ""}
        ${event.details ? `<div class="meta-line">${escapeHtml(runtimeDetailsText(event.details))}</div>` : ""}
      </article>
    `)
    .join("");
}

function isDuplicateRuntimeEvent(event, fileEvents) {
  return (fileEvents || []).some((item) => {
    return (
      item.stage === event.stage &&
      item.model_type === event.model_type &&
      item.model === event.model &&
      item.status === event.status &&
      item.duration_ms === event.duration_ms &&
      item.error === event.error
    );
  });
}

function runtimeStageLabel(stage) {
  const labels = {
    metadata: "元信息抽取",
    vision: "图片理解",
    embedding: "向量入库",
    qa: "知识库问答",
  };
  return labels[stage] || stage || "runtime";
}

function runtimeDetailsText(details = {}) {
  const entries = Object.entries(details || {}).filter(([, value]) => value !== undefined && value !== null && value !== "");
  return entries.map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : value}`).join(" · ");
}

function currentFile() {
  return state.result?.data?.[state.selectedIndex] || null;
}

function activeBlocks() {
  return state.editingBlocks ? state.draftBlocks : currentFile()?.blocks || [];
}

function activeChunks() {
  return state.editingChunks ? state.draftChunks : currentFile()?.chunks || [];
}

function startBlockEditing() {
  const file = currentFile();
  if (!file || !Array.isArray(file.blocks) || !file.blocks.length) {
    showAlert("当前文件没有可编辑的结构块。");
    return;
  }
  state.editingBlocks = true;
  state.draftBlocks = cloneBlocks(file.blocks);
  updateBlockEditorActions();
  renderBlocks(activeBlocks());
}

function cancelBlockEditing() {
  state.editingBlocks = false;
  state.draftBlocks = [];
  updateBlockEditorActions();
  renderBlocks(currentFile()?.blocks || []);
}

async function saveBlockCorrections() {
  if (!state.taskId || !currentFile()) return;
  try {
    setBlockEditorBusy(true);
    const response = await fetch(
      `/api/documents/tasks/${encodeURIComponent(state.taskId)}/result/files/${state.selectedIndex}/blocks`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ blocks: state.draftBlocks }),
      },
    );
    if (!response.ok) throw new Error(await response.text());
    const updatedFile = await response.json();
    state.result.data[state.selectedIndex] = updatedFile;
    state.editingBlocks = false;
    state.draftBlocks = [];
    markIndexNeedsRebuild();
    await loadRecentTasks();
    renderFileList();
    renderCurrentFile();
  } catch (error) {
    showAlert(`保存校正失败：${error.message}`);
  } finally {
    setBlockEditorBusy(false);
  }
}

function updateDraftBlockContent(index, value) {
  if (!state.editingBlocks || !state.draftBlocks[index]) return;
  const block = state.draftBlocks[index];
  block.content = value;
  if (block.type === "image") {
    block.metadata = { ...(block.metadata || {}), description: value };
  }
}

function deleteDraftBlock(index) {
  if (!state.editingBlocks || index < 0 || index >= state.draftBlocks.length) return;
  state.draftBlocks.splice(index, 1);
  renderBlocks(activeBlocks());
}

function cloneBlocks(blocks) {
  return JSON.parse(JSON.stringify(blocks || []));
}

function updateBlockEditorActions() {
  els.editBlocksButton.classList.toggle("hidden", state.editingBlocks);
  els.saveBlocksButton.classList.toggle("hidden", !state.editingBlocks);
  els.cancelBlocksButton.classList.toggle("hidden", !state.editingBlocks);
  const hasBlocks = Boolean(currentFile()?.blocks?.length);
  els.exportBlocksJsonButton.disabled = !hasBlocks;
  els.exportBlocksJsonlButton.disabled = !hasBlocks;
}

function setBlockEditorBusy(isBusy) {
  els.editBlocksButton.disabled = isBusy;
  els.saveBlocksButton.disabled = isBusy;
  els.cancelBlocksButton.disabled = isBusy;
}

function startChunkEditing() {
  const file = currentFile();
  if (!file || !Array.isArray(file.chunks) || !file.chunks.length) {
    showAlert("当前文件没有可编辑的知识库切片。");
    return;
  }
  state.editingChunks = true;
  state.draftChunks = cloneChunks(file.chunks);
  updateChunkEditorActions();
  renderChunks(activeChunks());
}

function cancelChunkEditing() {
  state.editingChunks = false;
  state.draftChunks = [];
  updateChunkEditorActions();
  renderChunks(currentFile()?.chunks || []);
}

async function saveChunkCorrections() {
  if (!state.taskId || !currentFile()) return;
  try {
    setChunkEditorBusy(true);
    const response = await fetch(
      `/api/documents/tasks/${encodeURIComponent(state.taskId)}/result/files/${state.selectedIndex}/chunks`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunks: state.draftChunks }),
      },
    );
    if (!response.ok) throw new Error(await response.text());
    const updatedFile = await response.json();
    state.result.data[state.selectedIndex] = updatedFile;
    state.editingChunks = false;
    state.draftChunks = [];
    markIndexNeedsRebuild();
    await loadRecentTasks();
    renderFileList();
    renderCurrentFile();
  } catch (error) {
    showAlert(`保存切片失败：${error.message}`);
  } finally {
    setChunkEditorBusy(false);
  }
}

function updateDraftChunkContent(index, value) {
  if (!state.editingChunks || !state.draftChunks[index]) return;
  const chunk = state.draftChunks[index];
  chunk.content = value;
  chunk.metadata = { ...(chunk.metadata || {}), char_count: value.length };
  if (!value.trim()) {
    chunk.metadata.ingest_enabled = false;
  }
}

function updateDraftChunkEnabled(index, enabled) {
  if (!state.editingChunks || !state.draftChunks[index]) return;
  const chunk = state.draftChunks[index];
  chunk.metadata = { ...(chunk.metadata || {}), ingest_enabled: Boolean(enabled) };
}

function cloneChunks(chunks) {
  return JSON.parse(JSON.stringify(chunks || []));
}

function updateChunkEditorActions() {
  els.editChunksButton.classList.toggle("hidden", state.editingChunks);
  els.saveChunksButton.classList.toggle("hidden", !state.editingChunks);
  els.cancelChunksButton.classList.toggle("hidden", !state.editingChunks);
  const hasChunks = Boolean(currentFile()?.chunks?.length);
  els.exportChunksJsonButton.disabled = !hasChunks;
  els.exportChunksJsonlButton.disabled = !hasChunks;
}

function setChunkEditorBusy(isBusy) {
  els.editChunksButton.disabled = isBusy;
  els.saveChunksButton.disabled = isBusy;
  els.cancelChunksButton.disabled = isBusy;
}

function openJsonFieldExportDialog() {
  if (!currentFile()) {
    showAlert("暂无可导出的 JSON。");
    return;
  }
  state.jsonAdvancedFieldsVisible = false;
  applyJsonExportPreset("business", false);
  els.jsonExportDialog.classList.remove("hidden");
}

function closeJsonFieldExportDialog() {
  els.jsonExportDialog.classList.add("hidden");
}

function applyJsonExportPreset(name, keepDialogOpen = true) {
  const preset = JSON_EXPORT_PRESETS[name] || JSON_EXPORT_PRESETS.business;
  state.jsonExportAll = preset.includes("*");
  state.jsonExportFields = new Set(state.jsonExportAll ? allJsonExportFieldPaths() : preset);
  renderJsonFieldTree();
  if (keepDialogOpen) clearAlert();
}

function renderJsonFieldTree() {
  els.jsonFieldTree.classList.toggle("show-advanced", state.jsonAdvancedFieldsVisible);
  els.toggleJsonAdvancedButton.textContent = state.jsonAdvancedFieldsVisible ? "隐藏高级字段" : "显示高级字段";
  els.jsonFieldTree.innerHTML = JSON_EXPORT_TREE.map((group) => {
    const children = group.fields
      .map(([path, label, note, advanced]) => {
        const checked = state.jsonExportAll || state.jsonExportFields.has(path) ? " checked" : "";
        const noteHtml = note ? `<span class="json-field-note">${escapeHtml(note)}</span>` : "";
        const advancedClass = advanced ? " json-field-advanced" : "";
        const advancedAttr = advanced ? ' data-json-advanced="true"' : "";
        return `
          <label class="${advancedClass.trim()}">
            <input class="json-field-checkbox" type="checkbox" data-json-field="${escapeHtml(path)}"${advancedAttr}${checked} />
            <span>${escapeHtml(label)}</span>
            <code>${escapeHtml(path)}</code>
            ${noteHtml}
          </label>
        `;
      })
      .join("");
    return `
      <section class="json-field-group" data-json-group="${escapeHtml(group.id)}">
        <label>
          <input class="json-group-checkbox" type="checkbox" data-json-group-toggle="${escapeHtml(group.id)}" />
          <span>${escapeHtml(group.label)}</span>
        </label>
        <div class="json-field-children">${children}</div>
      </section>
    `;
  }).join("");

  els.jsonFieldTree.querySelectorAll(".json-group-checkbox").forEach((input) => {
    input.addEventListener("change", () => {
      state.jsonExportAll = false;
      const group = input.closest(".json-field-group");
      group.querySelectorAll(visibleJsonFieldSelector()).forEach((child) => {
        child.checked = input.checked;
      });
      updateJsonExportFieldsFromTree();
    });
  });
  els.jsonFieldTree.querySelectorAll(".json-field-checkbox").forEach((input) => {
    input.addEventListener("change", () => {
      state.jsonExportAll = false;
      updateJsonExportFieldsFromTree();
    });
  });
  syncJsonGroupCheckboxes();
  updateJsonExportSummary();
}

function toggleJsonAdvancedFields() {
  state.jsonAdvancedFieldsVisible = !state.jsonAdvancedFieldsVisible;
  renderJsonFieldTree();
}

function updateJsonExportFieldsFromTree() {
  state.jsonExportFields = new Set(
    Array.from(els.jsonFieldTree.querySelectorAll(".json-field-checkbox:checked"))
      .map((input) => input.dataset.jsonField)
      .filter(Boolean),
  );
  syncJsonGroupCheckboxes();
  updateJsonExportSummary();
}

function syncJsonGroupCheckboxes() {
  els.jsonFieldTree.querySelectorAll(".json-field-group").forEach((group) => {
    const toggle = group.querySelector(".json-group-checkbox");
    const children = Array.from(group.querySelectorAll(visibleJsonFieldSelector()));
    const checkedCount = children.filter((item) => item.checked).length;
    toggle.checked = checkedCount === children.length && children.length > 0;
    toggle.indeterminate = checkedCount > 0 && checkedCount < children.length;
  });
}

function updateJsonExportSummary() {
  const count = state.jsonExportAll ? allJsonExportFieldPaths().length : state.jsonExportFields.size;
  els.jsonExportSummary.textContent = state.jsonExportAll ? "将导出当前文件完整 JSON" : `已选择 ${count} 个字段`;
}

function exportSelectedJson() {
  const file = currentFile();
  if (!file) {
    showAlert("暂无可导出的 JSON。");
    return;
  }
  if (!state.jsonExportAll && state.jsonExportFields.size === 0) {
    showAlert("请至少选择一个要导出的字段。");
    return;
  }
  const payload = state.jsonExportAll ? deepClone(file) : buildSelectedJsonExport(file, state.jsonExportFields);
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json;charset=utf-8" });
  downloadBlob(blob, `docagent_file_${state.selectedIndex}_selected.json`);
  closeJsonFieldExportDialog();
}

async function copyCurrentJson() {
  const file = currentFile();
  const payload = file || state.result;
  if (!payload) {
    showAlert("暂无可复制的 JSON。");
    return;
  }
  const text = JSON.stringify(payload, null, 2);
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      fallbackCopyText(text);
    }
    showAlert("当前 JSON 已复制到剪贴板。");
  } catch (error) {
    fallbackCopyText(text);
    showAlert("当前 JSON 已复制到剪贴板。");
  }
}

function buildSelectedJsonExport(file, selectedPaths) {
  return pickJsonValueByPaths(file, selectedPaths, "") || {};
}

function pickJsonValueByPaths(value, selectedPaths, prefix) {
  if (prefix && selectedPaths.has(prefix)) {
    return deepClone(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => pickJsonValueByPaths(item, selectedPaths, prefix))
      .filter((item) => item !== undefined && !isEmptyJsonExportValue(item));
  }
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const result = {};
  Object.entries(value).forEach(([key, child]) => {
    const childPath = prefix ? `${prefix}.${key}` : key;
    if (!hasSelectedJsonPath(selectedPaths, childPath)) return;
    const picked = selectedPaths.has(childPath) ? deepClone(child) : pickJsonValueByPaths(child, selectedPaths, childPath);
    if (picked !== undefined && !isEmptyJsonExportValue(picked)) {
      result[key] = picked;
    }
  });
  return Object.keys(result).length ? result : undefined;
}

function hasSelectedJsonPath(selectedPaths, path) {
  if (selectedPaths.has(path)) return true;
  return Array.from(selectedPaths).some((selectedPath) => selectedPath.startsWith(`${path}.`));
}

function isEmptyJsonExportValue(value) {
  if (Array.isArray(value)) return value.length === 0;
  if (value && typeof value === "object") return Object.keys(value).length === 0;
  return false;
}

function allJsonExportFieldPaths() {
  return JSON_EXPORT_TREE.flatMap((group) => group.fields.map(([path]) => path));
}

function visibleJsonFieldSelector() {
  return state.jsonAdvancedFieldsVisible
    ? ".json-field-checkbox"
    : '.json-field-checkbox:not([data-json-advanced="true"])';
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

async function exportCurrentFile(target, format) {
  const file = currentFile();
  if (!state.taskId || !file) {
    showAlert("当前没有可导出的文件。");
    return;
  }
  if (target === "blocks" && !(file.blocks || []).length) {
    showAlert("当前文件没有可导出的结构块。");
    return;
  }
  if (target === "chunks" && !(file.chunks || []).length) {
    showAlert("当前文件没有可导出的知识库切片。");
    return;
  }
  const url = `/api/documents/tasks/${encodeURIComponent(state.taskId)}/result/files/${state.selectedIndex}/export?target=${encodeURIComponent(target)}&format=${encodeURIComponent(format)}`;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    const fallbackName = `docagent_file_${state.selectedIndex}_${target}.${format === "jsonl" ? "jsonl" : "json"}`;
    downloadBlob(blob, match?.[1] || fallbackName);
  } catch (error) {
    showAlert(`导出失败：${error.message}`);
  }
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

async function fetchIndexStatus() {
  if (!state.taskId) return;
  try {
    const response = await fetch(`/api/documents/tasks/${encodeURIComponent(state.taskId)}/knowledge/index`);
    if (!response.ok) return;
    state.indexStatus = await response.json();
    renderKnowledgePanel();
  } catch (error) {
    state.indexStatus = { status: "failed", indexed: false, message: `索引状态查询失败：${error.message}` };
    renderKnowledgePanel();
  }
}

async function buildKnowledgeIndex() {
  if (!state.taskId) return;
  if (enabledChunkCount() === 0) {
    showAlert("当前没有可入库切片，请先启用至少一个 chunk。");
    return;
  }
  try {
    setKnowledgeBusy(true);
    const response = await fetch(`/api/documents/tasks/${encodeURIComponent(state.taskId)}/knowledge/index`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rebuild: true }),
    });
    if (!response.ok) throw new Error(await response.text());
    state.indexStatus = await response.json();
    state.qaAnswer = "";
    state.qaSources = [];
    clearAlert();
    renderKnowledgePanel();
  } catch (error) {
    showAlert(`构建索引失败：${error.message}`);
    state.indexStatus = { status: "failed", indexed: false, message: "索引构建失败" };
    renderKnowledgePanel();
  } finally {
    setKnowledgeBusy(false);
  }
}

async function askKnowledge() {
  const question = els.questionInput.value.trim();
  if (!question) {
    showAlert("请输入问题。");
    return;
  }
  try {
    setKnowledgeBusy(true);
    const response = await fetch(`/api/documents/tasks/${encodeURIComponent(state.taskId)}/knowledge/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: Number(els.topKInput.value || 5) }),
    });
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    state.qaAnswer = payload.answer || "暂无回答";
    state.qaSources = payload.sources || [];
    clearAlert();
    renderKnowledgePanel();
  } catch (error) {
    showAlert(`问答失败：${error.message}`);
  } finally {
    setKnowledgeBusy(false);
  }
}

function markIndexNeedsRebuild() {
  if (!state.indexStatus?.indexed) return;
  state.indexStatus = {
    ...state.indexStatus,
    status: "needs_rebuild",
    indexed: false,
    message: "切片已修改，索引需要重建",
  };
}

function enabledChunkCount() {
  return (state.result?.data || []).reduce((count, file) => {
    return count + (file.chunks || []).filter((chunk) => {
      const content = String(chunk.content || "").trim();
      return content && chunk.metadata?.ingest_enabled !== false;
    }).length;
  }, 0);
}

function setKnowledgeBusy(isBusy) {
  els.buildIndexButton.disabled = isBusy || enabledChunkCount() === 0;
  els.qaBuildIndexButton.disabled = isBusy || enabledChunkCount() === 0;
  els.askButton.disabled = isBusy || !state.indexStatus?.indexed;
}

function setBusy(isBusy) {
  els.uploadButton.disabled = isBusy;
  els.uploadButton.querySelector("span").textContent = isBusy ? "上传中" : "上传并解析";
}

async function copyTaskId() {
  const value = els.taskId.textContent.trim();
  if (!value || value === "-") return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      fallbackCopyText(value);
    }
    flashCopyButton("已复制");
  } catch (error) {
    fallbackCopyText(value);
    flashCopyButton("已复制");
  }
}

function fallbackCopyText(value) {
  const input = document.createElement("textarea");
  input.value = value;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  document.execCommand("copy");
  document.body.removeChild(input);
}

function flashCopyButton(label) {
  const previousTitle = els.taskIdCopy.title;
  const previousAria = els.taskIdCopy.getAttribute("aria-label");
  els.taskIdCopy.title = label;
  els.taskIdCopy.setAttribute("aria-label", label);
  window.setTimeout(() => {
    els.taskIdCopy.title = previousTitle || "复制 Task ID";
    els.taskIdCopy.setAttribute("aria-label", previousAria || "复制 Task ID");
  }, 1200);
}

function renderProgress(progress = {}) {
  const total = Number(progress.total_files || 0);
  const processed = Number(progress.processed_files || 0);
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
  const shouldShow = state.task?.status === "pending" || state.task?.status === "running";
  els.progressPanel.classList.toggle("hidden", !shouldShow);
  els.progressPercent.textContent = `${Math.round(percent)}%`;
  els.progressCount.textContent = `${processed} / ${total}`;
  els.progressBar.style.width = `${percent}%`;
  els.progressStep.textContent = progress.current_step || "等待解析";
  els.progressFile.textContent = progress.current_file || "-";
}

function fallbackProgress(payload = {}) {
  const progress = payload.progress || {};
  if (Number(progress.total_files || 0) > 0 || Number(progress.percent || 0) > 0) {
    return progress;
  }
  const fileCount = Array.isArray(payload.data) ? payload.data.length : 0;
  if (payload.status === "success") {
    return {
      total_files: fileCount,
      processed_files: fileCount,
      current_file: "",
      current_step: "解析完成",
      percent: 100,
    };
  }
  if (payload.status === "failed") {
    return {
      total_files: fileCount,
      processed_files: 0,
      current_file: "",
      current_step: "任务失败",
      percent: 0,
    };
  }
  return progress;
}

function formatStatus(status) {
  const labels = {
    pending: "等待中",
    running: "解析中",
    success: "成功",
    partial_success: "部分成功",
    failed: "失败",
    skipped: "跳过",
  };
  return labels[status] || status || "-";
}

function shortTaskId(taskId) {
  const value = String(taskId || "");
  return value.length > 10 ? `${value.slice(0, 8)}...` : value || "-";
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function findUnsupportedFiles(files) {
  return files.filter((file) => !SUPPORTED_EXTENSIONS.has(fileExtension(file.name)));
}

function fileExtension(name) {
  const index = String(name || "").lastIndexOf(".");
  return index >= 0 ? String(name).slice(index).toLowerCase() : "";
}

function renderImagePreview(block) {
  const fileName = block.metadata?.file_name;
  if (!fileName || !state.taskId) {
    return `<div class="image-preview unavailable">图片暂不可预览</div>`;
  }
  const url = `/api/documents/tasks/${encodeURIComponent(state.taskId)}/assets/${encodeURIComponent(fileName)}`;
  return `
    <figure class="image-preview">
      <img data-preview src="${escapeHtml(url)}" alt="${escapeHtml(fileName)}" loading="lazy" />
      <figcaption>${escapeHtml(fileName)}</figcaption>
      <span class="preview-fallback">图片暂不可预览</span>
    </figure>
  `;
}

function showAlert(message) {
  els.alertBox.textContent = message;
  els.alertBox.classList.remove("hidden");
}

function clearAlert() {
  els.alertBox.textContent = "";
  els.alertBox.classList.add("hidden");
}

function summarizeMetadata(metadata = {}, keys = []) {
  return keys
    .filter((key) => metadata[key] !== undefined && metadata[key] !== null && metadata[key] !== "")
    .map((key) => `${key}=${metadata[key]}`)
    .join(" · ");
}

function formatIndexStatus(status) {
  const labels = {
    not_built: "未构建",
    built: "已构建",
    failed: "构建失败",
    needs_rebuild: "需要重建",
  };
  return labels[status] || status || "未构建";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

renderKnowledgePanel();
renderRuntimeMetrics(null);
loadRecentTasks();
