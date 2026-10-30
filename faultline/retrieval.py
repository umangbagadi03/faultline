"""
Lightweight RAG: BM25 search over
  1. failure playbooks (faultline/knowledge/*.md)
  2. past autopsies (incident memory: "have we seen this before?")

Why not a vector DB? The corpus is small (tens to thousands of docs) and the
queries are full of exact tokens like tool names and error codes.
Keyword search (BM25) is accurate here, explainable and needs zero infra.
"""

import math
import re
from collections import Counter
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


class BM25:
    def __init__(self, docs: list[dict], k1: float = 1.5, b: float = 0.75):
        # each doc: {"id": ..., "title": ..., "text": ..., "kind": ...}
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize(d["title"] + " " + d["text"]) for d in docs]
        self.avg_len = sum(len(t) for t in self.doc_tokens) / max(len(docs), 1)

        doc_freq = Counter()
        for tokens in self.doc_tokens:
            for token in set(tokens):
                doc_freq[token] += 1
        n = len(docs)
        self.idf = {}
        for token, df in doc_freq.items():
            self.idf[token] = math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        query_tokens = tokenize(query)
        results = []
        for doc, tokens in zip(self.docs, self.doc_tokens):
            counts = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                if token not in counts:
                    continue
                tf = counts[token]
                norm = 1 - self.b + self.b * len(tokens) / self.avg_len
                score += self.idf[token] * tf * (self.k1 + 1) / (tf + self.k1 * norm)
            if score > 0:
                results.append({**doc, "score": round(score, 2)})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]


def load_playbooks() -> list[dict]:
    docs = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text()
        title = text.splitlines()[0].lstrip("# ").strip()
        docs.append({"id": path.stem.upper(), "title": title, "text": text, "kind": "playbook"})
    return docs


def get_playbook(failure_class: str) -> str:
    path = KNOWLEDGE_DIR / f"{failure_class.lower()}.md"
    if path.exists():
        return path.read_text()
    return ""


def autopsy_docs(autopsies) -> list[dict]:
    """Turn past autopsies into searchable documents."""
    docs = []
    for a in autopsies:
        if not a.root_cause:
            continue
        text = f"{a.root_cause.failure_class} {a.root_cause.title} {a.root_cause.explanation}"
        if a.fix:
            text += " fix: " + a.fix.summary
        docs.append({"id": a.trace_id, "title": a.root_cause.title, "text": text, "kind": "incident"})
    return docs


def retrieve(query: str, past_autopsies, exclude_id: str = "") -> dict:
    playbooks = BM25(load_playbooks()).search(query, top_k=2)

    incidents = []
    past = [d for d in autopsy_docs(past_autopsies) if d["id"] != exclude_id]
    if past:
        incidents = BM25(past).search(query, top_k=3)

    return {"playbooks": playbooks, "incidents": incidents}
