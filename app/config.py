# app/config.py：配置文件

from dataclasses import dataclass
from pathlib import Path
import os


def _env_bool(name: str, default: str = "true") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value not in {"0", "false", "no", "off"}


@dataclass(frozen=True) # frozen=True：创建之后不允许随便修改
class Settings:
    app_name: str = "DocAgent"
    api_prefix: str = "/api" # api_prefix：设置接口前缀
    data_dir: Path = Path(os.getenv("DOCAGENT_DATA_DIR", "data")).resolve()

    max_upload_mb: int = int(os.getenv("DOCAGENT_MAX_UPLOAD_MB", "100"))


    # aliyun LLM 基础配置
    @property
    def llm_base_url(self) -> str:
        return os.getenv("DASHSCOPE_BASE_URL", "https://api.openai.com/v1/chat/completions")

    @property
    def llm_api_key(self) -> str:
        return os.getenv("DASHSCOPE_API_KEY", "EMPTY")

    @property
    def llm_model(self) -> str:
        return os.getenv("LLM_MODEL", "qwen3-vl-flash")


    # 其他功能开关配置
    @property
    def metadata_enabled(self) -> bool:
        ''' METADATA_ENABLED：是否启用元数据功能 '''
        return _env_bool("METADATA_ENABLED", "true")

    @property
    def vision_enabled(self) -> bool:
        ''' VISION_ENABLED：是否启用视觉功能 '''
        return _env_bool("VISION_ENABLED", "true")

    @property
    def qa_enabled(self) -> bool:
        ''' QA_ENABLED：是否只返回检索片段，不调用 LLM 生成回答 '''
        return _env_bool("QA_ENABLED", "true")

    @property
    def model_timeout_seconds(self) -> float:
        return float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))

    @property
    def model_retry_times(self) -> int:
        return max(0, int(os.getenv("MODEL_RETRY_TIMES", "1")))

    @property
    def vision_max_images_per_file(self) -> int:
        return max(0, int(os.getenv("VISION_MAX_IMAGES_PER_FILE", "20")))


    # Embedding / 向量库配置
    @property
    def embedding_base_url(self) -> str:
        return os.getenv("DASHSCOPE_BASE_URL", "https://api.openai.com/v1/chat/completions")

    @property
    def embedding_api_key(self) -> str:
        return os.getenv("DASHSCOPE_API_KEY", "EMPTY")

    @property
    def embedding_enabled(self) -> bool:
        return _env_bool("EMBEDDING_ENABLED", "true")

    @property
    def embedding_model(self) -> str:
        return os.getenv("EMBEDDING_MODEL", "text-embedding-v4")

    @property
    def embedding_batch_size(self) -> int:
        return max(1, min(int(os.getenv("EMBEDDING_BATCH_SIZE", "10")), 10))

    @property
    def vector_store_dir(self) -> Path:
        return Path(os.getenv("VECTOR_STORE_DIR", str(self.data_dir / "vector_store" / "chroma"))).resolve()


    # 远程图片下载配置
    @property
    def remote_image_download_enabled(self) -> bool:
        value = os.getenv("REMOTE_IMAGE_DOWNLOAD_ENABLED", "true").strip().lower()
        return value not in {"0", "false", "no", "off"}
    @property
    def remote_image_timeout_seconds(self) -> float:
        return float(os.getenv("REMOTE_IMAGE_TIMEOUT_SECONDS", "10"))
    @property
    def remote_image_max_mb(self) -> int:
        return int(os.getenv("REMOTE_IMAGE_MAX_MB", "10"))


    # 本地保存网页 zip 包解压限制
    @property
    def html_archive_max_files(self) -> int:
        return int(os.getenv("HTML_ARCHIVE_MAX_FILES", "1000"))

    @property
    def html_archive_max_file_mb(self) -> int:
        return int(os.getenv("HTML_ARCHIVE_MAX_FILE_MB", "50"))

    @property
    def html_archive_max_total_mb(self) -> int:
        return int(os.getenv("HTML_ARCHIVE_MAX_TOTAL_MB", "200"))


settings = Settings()
