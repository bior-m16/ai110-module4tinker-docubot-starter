"""
Core DocuBot class responsible for:
- Loading documents from the docs/ folder
- Building a simple retrieval index (Phase 1)
- Retrieving relevant snippets (Phase 1)
- Supporting retrieval only answers
- Supporting RAG answers when paired with Gemini (Phase 2)
"""

import os
import glob
import math
import re

MAX_CHUNK_CHARS = 1200

# Refusal guardrail: a section must share this many distinct query terms to
# count as evidence (see DocuBot.has_enough_evidence).
MIN_MATCHED_TERMS = 2

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "at", "for", "and", "or", "do", "does", "how", "what", "which", "where",
    "when", "who", "why", "there", "any", "these", "this", "that", "it", "i",
    "we", "you", "my", "our", "with", "about", "mention",
}


class DocuBot:
    def __init__(self, docs_folder="docs", llm_client=None):
        """
        docs_folder: directory containing project documentation files
        llm_client: optional Gemini client for LLM based answers
        """
        # Resolve relative paths against this file so the working directory
        # the program is launched from does not matter.
        if not os.path.isabs(docs_folder):
            docs_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), docs_folder)
        self.docs_folder = docs_folder
        self.llm_client = llm_client

        # Load documents into memory
        self.documents = self.load_documents()  # List of (filename, text)

        # Split documents into small sections and index those
        self.chunks = self.chunk_documents(self.documents)  # List of (filename, text)

        # Build a retrieval index (implemented in Phase 1)
        self.index = self.build_index(self.chunks)

    # -----------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------

    def load_documents(self):
        """
        Loads all .md and .txt files inside docs_folder.
        Returns a list of tuples: (filename, text)
        """
        docs = []
        pattern = os.path.join(self.docs_folder, "*.*")
        for path in glob.glob(pattern):
            if path.endswith(".md") or path.endswith(".txt"):
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()
                filename = os.path.basename(path)
                docs.append((filename, text))
        return docs

    # -----------------------------------------------------------
    # Chunking
    # -----------------------------------------------------------

    def chunk_documents(self, documents):
        """
        Splits each (filename, text) document into smaller sections.
        Returns a list of (filename, chunk_text); each chunk starts with its
        heading line so it keeps its topic.
        """
        chunks = []
        for filename, text in documents:
            doc_chunks = self._chunk_text(text)
            if len(doc_chunks) > 1:
                # The "# Title" intro blurb matches on topic words but rarely
                # answers anything; the sections below it do.
                doc_chunks = [c for c in doc_chunks if not c.startswith("# ")]
            for chunk in doc_chunks:
                chunks.append((filename, chunk))
        return chunks

    def _chunk_text(self, text):
        # 1. Split on markdown headings, ignoring "#" lines inside code fences.
        sections = []  # list of (heading_line, body_lines)
        heading, body = "", []
        in_fence = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
            if not in_fence and re.match(r"#{1,3}\s", line):
                sections.append((heading, body))
                heading, body = line, []
            else:
                body.append(line)
        sections.append((heading, body))

        # 2. Split oversized sections on blank lines (never inside a fence).
        chunks = []
        for heading, body in sections:
            if not "".join(body).strip():
                continue  # heading with no body (e.g. "## Tables"): nothing to retrieve
            pieces, current, in_fence = [], [], False
            for line in body:
                if line.strip().startswith("```"):
                    in_fence = not in_fence
                if not line.strip() and not in_fence and current:
                    pieces.append("\n".join(current))
                    current = []
                else:
                    current.append(line)
            if current:
                pieces.append("\n".join(current))

            group = ""
            for piece in pieces:
                if group and len(heading) + len(group) + len(piece) > MAX_CHUNK_CHARS:
                    chunks.append(f"{heading}\n{group}".strip())
                    group = ""
                group = f"{group}\n\n{piece}" if group else piece
            if group:
                chunks.append(f"{heading}\n{group}".strip())
        return chunks

    # -----------------------------------------------------------
    # Tokenization
    # -----------------------------------------------------------

    @staticmethod
    def _stem(word):
        """Very light stemming so "tokens" matches "token"."""
        for suffix in ("ions", "ion", "ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: -len(suffix)]
        return word

    def _tokenize(self, text):
        """Lowercase, split into words, drop stopwords, and stem."""
        # "log in" / "log-in" / "sign in" are the same idea as "login".
        text = re.sub(r"\b(?:log|sign)[\s-]+in\b", "login", text.lower())
        words = re.findall(r"[a-z0-9_]+", text)
        return [self._stem(w) for w in words if w not in STOPWORDS]

    # -----------------------------------------------------------
    # Index Construction (Phase 1)
    # -----------------------------------------------------------

    def build_index(self, chunks):
        """
        Build a tiny inverted index mapping lowercase words to the chunks
        they appear in.

        chunks: list of (filename, chunk_text)
        Returns {"token": [chunk_id, ...]} where chunk_id is a position in chunks.
        """
        index = {}
        for chunk_id, (_, text) in enumerate(chunks):
            for token in self._tokenize(text):
                ids = index.setdefault(token, [])
                if not ids or ids[-1] != chunk_id:
                    ids.append(chunk_id)
        return index

    # -----------------------------------------------------------
    # Scoring and Retrieval (Phase 1)
    # -----------------------------------------------------------

    def score_document(self, query, text):
        """
        TODO (Phase 1):
        Return a simple relevance score for how well the text matches the query.

        Suggested baseline:
        - Convert query into lowercase words
        - Count how many appear in the text
        - Return the count as the score
        """
        text_tokens = self._tokenize(text)
        text_set = set(text_tokens)
        query_tokens = set(self._tokenize(query))
        matched = [token for token in query_tokens if token in text_set]
        if not matched:
            return 0
        # Each matched word is weighted by how rare it is across all sections,
        # so a word like "database" (in most sections) counts for less than
        # "connect" (in few).
        weight = sum(self._idf(token) for token in matched)
        # A query word in the section's heading is a strong topical signal.
        heading_tokens = set(self._tokenize(text.splitlines()[0]))
        weight += sum(self._idf(token) for token in matched if token in heading_tokens)
        # Small tie-break: more occurrences of query words ranks higher.
        hits = sum(1 for token in text_tokens if token in query_tokens)
        return weight + 0.1 * hits / (hits + 10)

    def _idf(self, token):
        """Rarer tokens (found in fewer sections) get a higher weight."""
        sections_with_token = len(self.index.get(token, []))
        return math.log(1 + len(self.chunks) / max(sections_with_token, 1))

    def retrieve(self, query, top_k=3):
        """
        Use the index and scoring function to select top_k relevant sections.

        Return a list of (filename, section_text) sorted by score descending.
        """
        candidates = set()
        for token in set(self._tokenize(query)):
            candidates.update(self.index.get(token, []))

        results = []
        for chunk_id in sorted(candidates):
            filename, text = self.chunks[chunk_id]
            if not self.has_enough_evidence(query, text):
                continue
            score = self.score_document(query, text)
            results.append((score, filename, text))

        results.sort(key=lambda r: r[0], reverse=True)
        return [(filename, text) for _, filename, text in results[:top_k]]

    def has_enough_evidence(self, query, text):
        """
        Refusal guardrail: True only if this section is meaningful evidence
        for the query.

        A section counts as evidence when it contains at least
        MIN_MATCHED_TERMS distinct query terms (or every query term, for
        queries shorter than that). One shared word, like "docs" in
        "payment processing in these docs", is coincidence, not evidence.

        If no section passes, retrieve returns [] and both answer modes say
        "I do not know based on these docs." (RAG never calls the LLM).
        """
        query_terms = set(self._tokenize(query))
        if not query_terms:
            return False
        matched = query_terms & set(self._tokenize(text))
        required = min(MIN_MATCHED_TERMS, len(query_terms))
        return len(matched) >= required

    # -----------------------------------------------------------
    # Answering Modes
    # -----------------------------------------------------------

    def answer_retrieval_only(self, query, top_k=3):
        """
        Phase 1 retrieval only mode.
        Returns raw snippets and filenames with no LLM involved.
        """
        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        formatted = []
        for filename, text in snippets:
            formatted.append(f"[{filename}]\n{text}\n")

        return "\n---\n".join(formatted)

    def answer_rag(self, query, top_k=3):
        """
        Phase 2 RAG mode.
        Uses student retrieval to select snippets, then asks Gemini
        to generate an answer using only those snippets.
        """
        if self.llm_client is None:
            raise RuntimeError(
                "RAG mode requires an LLM client. Provide a GeminiClient instance."
            )

        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        return self.llm_client.answer_from_snippets(query, snippets)

    # -----------------------------------------------------------
    # Bonus Helper: concatenated docs for naive generation mode
    # -----------------------------------------------------------

    def full_corpus_text(self):
        """
        Returns all documents concatenated into a single string.
        This is used in Phase 0 for naive 'generation only' baselines.
        """
        return "\n\n".join(text for _, text in self.documents)
