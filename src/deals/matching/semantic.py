"""Optional semantic reranker using a multilingual embedding model.

Needs the extra dependencies:  pip install -e '.[semantic]'
The model (~470 MB) is downloaded from Hugging Face on first use and cached.

E5 models expect "query: " / "passage: " prefixes. We embed each offer as its
title plus the informative part of its category path, so "Klassische Pasta
(Barilla)" and "Nudeln" end up close together.
"""

from deals.models import Offer

MODEL = "intfloat/multilingual-e5-small"


class E5Reranker:
    def __init__(self, model_name: str = MODEL):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "Semantic matching needs sentence-transformers: pip install -e '.[semantic]'"
            ) from e
        self.model = SentenceTransformer(model_name)
        self._cache: dict[str, list[float]] = {}  # offer text -> embedding

    @staticmethod
    def offer_text(o: Offer) -> str:
        path = (o.category or "").split(" > ")
        category = " > ".join(path[3:]) if len(path) > 3 else (path[-1] if path else "")
        return f"{o.title} ({category})" if category else o.title

    def similarities(self, query: str, offers: list[Offer]) -> list[float]:
        texts = [self.offer_text(o) for o in offers]
        missing = list(dict.fromkeys(t for t in texts if t not in self._cache))
        if missing:
            vectors = self.model.encode([f"passage: {t}" for t in missing], batch_size=64,
                                        normalize_embeddings=True, show_progress_bar=False)
            self._cache.update(zip(missing, vectors))
        q = self.model.encode(f"query: {query}", normalize_embeddings=True)
        return [float(self._cache[t] @ q) for t in texts]
