"""Embedding provider with 3-tier fallback: local model -> SiliconFlow API -> None."""

from __future__ import annotations

import logging
import os
import sys
import json
import hashlib
import struct

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(__file__))
from config import get_embedding_config, load_config, save_config


class BaseProvider:
    """Base embedding provider interface."""
    name = "base"
    model_name = ""
    dimensions = 0

    def available(self):
        return False

    def encode(self, texts):
        """Encode texts to embeddings. Returns list[list[float]] or None."""
        return None


class LocalProvider(BaseProvider):
    """Local sentence-transformers with BAAI/bge-small-zh-v1.5."""
    name = "local"
    model_name = "BAAI/bge-small-zh-v1.5"
    dimensions = 512

    def __init__(self):
        self._model = None

    def available(self):
        try:
            import sentence_transformers
            return True
        except ImportError:
            return False

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self.dimensions = self._model.get_sentence_embedding_dimension()
        return self._model

    def encode(self, texts):
        if not self.available():
            return None
        model = self._load_model()
        embeddings = model.encode(texts, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]


class APIProvider(BaseProvider):
    """SiliconFlow API with BAAI/bge-m3."""
    name = "siliconflow"
    model_name = "BAAI/bge-m3"
    dimensions = 1024

    def __init__(self, api_key="", base_url="", model=""):
        self.api_key = api_key
        self.base_url = base_url or "https://api.siliconflow.cn/v1/embeddings"
        if model:
            self.model_name = model

    def available(self):
        return bool(self.api_key)

    def encode(self, texts):
        if not self.available():
            return None
        import urllib.request
        import urllib.error

        # API accepts max ~64 texts per batch
        all_embeddings = []
        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            payload = json.dumps({
                "model": self.model_name,
                "input": batch,
                "encoding_format": "float"
            }).encode("utf-8")

            req = urllib.request.Request(
                self.base_url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                # Sort by index to maintain order
                data = sorted(result["data"], key=lambda x: x["index"])
                all_embeddings.extend([d["embedding"] for d in data])
                if self.dimensions == 0 and data:
                    self.dimensions = len(data[0]["embedding"])
            except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError) as e:
                logger.error("SiliconFlow API error on batch %d-%d: %s", i, i + batch_size, e)
                raise RuntimeError(f"SiliconFlow API error: {e}")

        return all_embeddings


class NoneProvider(BaseProvider):
    """Fallback: no embedding available."""
    name = "none"

    def available(self):
        return False

    def encode(self, texts):
        return None


def get_provider(config=None):
    """Factory: return the best available embedding provider.

    Priority based on config['embedding']['provider']:
    - "auto": try local -> siliconflow -> none
    - "local": local only, fall back to none
    - "siliconflow": API only, fall back to none
    - "none": always none
    """
    if config is None:
        config = get_embedding_config()

    provider_type = config.get("provider", "auto")

    if provider_type == "none":
        return NoneProvider()

    if provider_type == "local":
        p = LocalProvider()
        return p if p.available() else NoneProvider()

    if provider_type == "siliconflow":
        p = APIProvider(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", ""),
            model=config.get("model", "")
        )
        return p if p.available() else NoneProvider()

    # auto: try local first, then API
    local = LocalProvider()
    if local.available():
        return local

    api_key = config.get("api_key", "")
    if api_key:
        api = APIProvider(
            api_key=api_key,
            base_url=config.get("base_url", ""),
            model=config.get("model", "")
        )
        if api.available():
            return api

    return NoneProvider()


def text_hash(text):
    """Compute a short hash of text for change detection."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def embedding_to_blob(embedding):
    """Convert list[float] to bytes (BLOB) for SQLite storage."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def blob_to_embedding(blob):
    """Convert BLOB bytes back to list[float]."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
