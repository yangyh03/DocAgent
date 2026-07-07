from __future__ import annotations

import json
from datetime import datetime
from time import perf_counter
from typing import Any

from app.config import settings
from app.llm.agents import answer_question_with_llm, embed_texts, is_embedding_enabled, is_qa_enabled
from app.schemas import FileResult, KnowledgeAskResponse, KnowledgeIndexStatus, KnowledgeSource
from app.services.task_service import task_service


class KnowledgeService:
    """任务级 Chroma 向量库服务。"""

    def __init__(self) -> None:
        self._status: dict[str, dict[str, Any]] = {}

    def collection_name(self, task_id: str) -> str:
        return f"docagent_task_{task_id}"

    def delete_index(self, task_id: str) -> bool:
        collection_name = self.collection_name(task_id)
        self._status.pop(task_id, None)
        try:
            self._get_client().delete_collection(collection_name)
            return True
        except Exception:
            return False

    def get_index_status(self, task_id: str) -> KnowledgeIndexStatus:
        if task_service.get_task(task_id) is None:
            raise KeyError(task_id)
        collection_name = self.collection_name(task_id)
        cached = self._status.get(task_id)
        if cached:
            return KnowledgeIndexStatus(task_id=task_id, collection_name=collection_name, **cached)
        try:
            collection = self._get_client().get_collection(collection_name)
            count = int(collection.count())
        except Exception:
            count = 0
        return KnowledgeIndexStatus(
            task_id=task_id,
            collection_name=collection_name,
            indexed=count > 0,
            indexed_count=count,
            status="built" if count > 0 else "not_built",
            message="索引已构建" if count > 0 else "索引未构建",
        )

    def build_index(self, task_id: str, file_indices: list[int] | None = None, rebuild: bool = True) -> KnowledgeIndexStatus:
        results = task_service.get_result(task_id)
        if results is None:
            raise KeyError(task_id)
        if not is_embedding_enabled():
            task_service.add_runtime_event(
                task_id,
                self._model_event(
                    stage="embedding",
                    model_type="embedding",
                    model=settings.embedding_model,
                    status="skipped",
                    fallback_used=True,
                    error="未配置 EMBEDDING_API_KEY 或 EMBEDDING_ENABLED=false",
                ),
            )
            raise ValueError("未配置 EMBEDDING_API_KEY，无法构建向量索引")

        selected = self._select_files(results, file_indices)
        entries, skipped_count = self._collect_enabled_chunks(task_id, selected)
        collection_name = self.collection_name(task_id)
        if not entries:
            status = {
                "indexed": False,
                "indexed_count": 0,
                "skipped_count": skipped_count,
                "status": "failed",
                "message": "当前任务没有可入库切片",
                "last_built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._status[task_id] = status
            return KnowledgeIndexStatus(task_id=task_id, collection_name=collection_name, **status)

        start = perf_counter()
        try:
            client = self._get_client()
            if rebuild:
                try:
                    client.delete_collection(collection_name)
                except Exception:
                    pass
            collection = client.get_or_create_collection(collection_name)
            embeddings = embed_texts([entry["content"] for entry in entries])
            collection.upsert(
                ids=[entry["id"] for entry in entries],
                documents=[entry["content"] for entry in entries],
                metadatas=[entry["metadata"] for entry in entries],
                embeddings=embeddings,
            )
            task_service.add_runtime_event(
                task_id,
                self._model_event(
                    stage="embedding",
                    model_type="embedding",
                    model=settings.embedding_model,
                    status="success",
                    duration_ms=self._duration_ms(start),
                    input_items=len(entries),
                    output_items=len(embeddings),
                    details={
                        "batch_size": settings.embedding_batch_size,
                        "batch_count": (len(entries) + settings.embedding_batch_size - 1) // settings.embedding_batch_size,
                        "rebuild": rebuild,
                    },
                ),
            )
        except Exception as exc:
            task_service.add_runtime_event(
                task_id,
                self._model_event(
                    stage="embedding",
                    model_type="embedding",
                    model=settings.embedding_model,
                    status="failed",
                    duration_ms=self._duration_ms(start),
                    fallback_used=True,
                    input_items=len(entries),
                    output_items=0,
                    error=str(exc),
                ),
            )
            raise
        status = {
            "indexed": True,
            "indexed_count": len(entries),
            "skipped_count": skipped_count,
            "status": "built",
            "message": f"索引构建完成，已入库 {len(entries)} 个切片",
            "last_built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._status[task_id] = status
        return KnowledgeIndexStatus(task_id=task_id, collection_name=collection_name, **status)

    def ask(self, task_id: str, question: str, top_k: int = 5) -> KnowledgeAskResponse:
        if task_service.get_task(task_id) is None:
            raise KeyError(task_id)
        if not question.strip():
            raise ValueError("问题不能为空")
        status = self.get_index_status(task_id)
        if not status.indexed:
            raise ValueError("当前任务尚未构建知识库索引")
        if not is_embedding_enabled():
            task_service.add_runtime_event(
                task_id,
                self._model_event(
                    stage="qa",
                    model_type="embedding",
                    model=settings.embedding_model,
                    status="skipped",
                    fallback_used=True,
                    error="未配置 EMBEDDING_API_KEY 或 EMBEDDING_ENABLED=false",
                ),
            )
            raise ValueError("未配置 EMBEDDING_API_KEY，无法检索向量索引")

        top_k = max(1, min(int(top_k or 5), 10))
        retrieval_start = perf_counter()
        try:
            query_embedding = embed_texts([question])[0]
            collection = self._get_client().get_collection(self.collection_name(task_id))
            raw = collection.query(query_embeddings=[query_embedding], n_results=top_k)
            sources = self._normalize_query_result(raw)
            task_service.add_runtime_event(
                task_id,
                self._model_event(
                    stage="qa",
                    model_type="embedding",
                    model=settings.embedding_model,
                    status="success",
                    duration_ms=self._duration_ms(retrieval_start),
                    input_items=1,
                    output_items=len(sources),
                    details={"top_k": top_k, "retrieved_count": len(sources)},
                ),
            )
        except Exception as exc:
            task_service.add_runtime_event(
                task_id,
                self._model_event(
                    stage="qa",
                    model_type="embedding",
                    model=settings.embedding_model,
                    status="failed",
                    duration_ms=self._duration_ms(retrieval_start),
                    fallback_used=True,
                    input_items=1,
                    output_items=0,
                    error=str(exc),
                    details={"top_k": top_k},
                ),
            )
            raise
        if is_qa_enabled():
            qa_start = perf_counter()
            try:
                answer = answer_question_with_llm(question, [source.model_dump() for source in sources])
                mode = "llm"
                task_service.add_runtime_event(
                    task_id,
                    self._model_event(
                        stage="qa",
                        model_type="llm",
                        model=settings.llm_model,
                        status="success",
                        duration_ms=self._duration_ms(qa_start),
                        input_items=len(sources),
                        output_items=1,
                        details={"top_k": top_k},
                    ),
                )
            except Exception as exc:
                answer = "问答模型调用失败，已返回相关来源片段。"
                mode = "retrieval_only"
                task_service.add_runtime_event(
                    task_id,
                    self._model_event(
                        stage="qa",
                        model_type="llm",
                        model=settings.llm_model,
                        status="failed",
                        duration_ms=self._duration_ms(qa_start),
                        fallback_used=True,
                        input_items=len(sources),
                        output_items=0,
                        error=str(exc),
                        details={"top_k": top_k},
                    ),
                )
        else:
            answer = "未配置问答模型，已返回相关来源片段。"
            mode = "retrieval_only"
            task_service.add_runtime_event(
                task_id,
                self._model_event(
                    stage="qa",
                    model_type="llm",
                    model=settings.llm_model,
                    status="skipped",
                    fallback_used=True,
                    input_items=len(sources),
                    output_items=0,
                    error="未配置 QA 模型或 QA_ENABLED=false",
                    details={"top_k": top_k, "retrieved_count": len(sources)},
                ),
            )
        return KnowledgeAskResponse(
            answer=answer,
            sources=sources,
            retrievalTrace={
                "task_id": task_id,
                "collection_name": self.collection_name(task_id),
                "top_k": top_k,
                "retrieved_count": len(sources),
                "mode": mode,
                "embedding_model": settings.embedding_model,
                "llm_model": settings.llm_model if mode == "llm" else "",
            },
        )

    def _get_client(self):
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("未安装 chromadb，请先安装依赖后再构建知识库索引") from exc
        settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(settings.vector_store_dir))

    def _select_files(self, results: list[FileResult], file_indices: list[int] | None) -> list[tuple[int, FileResult]]:
        if file_indices is None:
            return list(enumerate(results))
        selected: list[tuple[int, FileResult]] = []
        for index in file_indices:
            if index < 0 or index >= len(results):
                raise IndexError(index)
            selected.append((index, results[index]))
        return selected

    def _collect_enabled_chunks(
        self,
        task_id: str,
        selected: list[tuple[int, FileResult]],
    ) -> tuple[list[dict[str, Any]], int]:
        entries: list[dict[str, Any]] = []
        skipped_count = 0
        for file_index, file_result in selected:
            for chunk in file_result.chunks:
                content = chunk.content.strip()
                if not content or chunk.metadata.get("ingest_enabled") is False:
                    skipped_count += 1
                    continue
                chunk_id = chunk.chunk_id
                entries.append(
                    {
                        "id": f"{task_id}:{file_index}:{chunk_id}",
                        "content": content,
                        "metadata": self._chunk_metadata(task_id, file_index, file_result, chunk_id, chunk.metadata),
                    }
                )
        return entries, skipped_count

    def _chunk_metadata(
        self,
        task_id: str,
        file_index: int,
        file_result: FileResult,
        chunk_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        values = {
            "task_id": task_id,
            "file_index": file_index,
            "file_name": file_result.fileName,
            "chunk_id": chunk_id,
            "chunk_index": metadata.get("chunk_index", ""),
            "block_types": metadata.get("block_types", []),
            "page_number": metadata.get("page_number", ""),
            "asset_refs": metadata.get("asset_refs", []),
            "heading_path": metadata.get("heading_path", []),
        }
        return {key: self._metadata_value(value) for key, value in values.items()}

    def _metadata_value(self, value: Any) -> str | int | float | bool:
        if isinstance(value, (str, int, float, bool)):
            return value
        if value is None:
            return ""
        return json.dumps(value, ensure_ascii=False)

    def _normalize_query_result(self, raw: dict[str, Any]) -> list[KnowledgeSource]:
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        sources: list[KnowledgeSource] = []
        for index, content in enumerate(documents):
            distance = distances[index] if index < len(distances) else None
            score = None if distance is None else round(1 / (1 + float(distance)), 6)
            sources.append(
                KnowledgeSource(
                    content=str(content or ""),
                    score=score,
                    metadata=self._restore_metadata(metadatas[index] if index < len(metadatas) else {}),
                )
            )
        return sources

    def _restore_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        restored = dict(metadata or {})
        for key in ("block_types", "asset_refs", "heading_path"):
            value = restored.get(key)
            if isinstance(value, str) and value.startswith("["):
                try:
                    restored[key] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        return restored

    def _duration_ms(self, start: float) -> int:
        return max(0, int((perf_counter() - start) * 1000))

    def _model_event(
        self,
        *,
        stage: str,
        model_type: str,
        model: str = "",
        status: str = "success",
        duration_ms: int = 0,
        fallback_used: bool = False,
        input_items: int = 0,
        output_items: int = 0,
        error: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "model_type": model_type,
            "model": model,
            "status": status,
            "duration_ms": duration_ms,
            "fallback_used": fallback_used,
            "input_items": input_items,
            "output_items": output_items,
            "error": error,
            "details": details or {},
        }


knowledge_service = KnowledgeService()
