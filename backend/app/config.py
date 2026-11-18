"""Application settings, read from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every value comes from the environment, with sensible defaults."""

    # Database
    DATABASE_URL: str = "sqlite:///./data/study_buddy.db"

    # Auth
    SECRET_KEY: str = "dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Vector store
    CHROMA_PATH: str = "./data/chroma"
    COLLECTION_NAME: str = "documents"

    # Model server
    OLLAMA_URL: str = "http://localhost:11434"
    MODEL_NAME: str = "llama3.2:1b"

    # RAG
    CHUNK_WORDS: int = 220
    OVERLAP_WORDS: int = 50
    MAX_RESULTS: int = 5
    CONFIDENCE_THRESHOLD: float = 0.75

    # Uploads
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_BYTES: int = 5_000_000

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
