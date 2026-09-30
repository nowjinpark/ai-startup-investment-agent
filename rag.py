import hashlib
import os
import threading
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


class BGEEmbeddings(Embeddings):
    def __init__(self, model_name, cache_dir):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device=os.getenv('EMBEDDING_DEVICE', 'cpu'),
                                         cache_folder=cache_dir, trust_remote_code=False)
        self.lock = threading.Lock()

    def embed_documents(self, texts):
        with self.lock:
            return self.model.encode(texts, batch_size=8, normalize_embeddings=True,
                                     show_progress_bar=False).tolist()

    def embed_query(self, text):
        return self.embed_documents([text])[0]


class Corpus:
    def __init__(self, sources, config, cache_dir, embeddings=None):
        from langchain_classic.embeddings import CacheBackedEmbeddings
        from langchain_classic.storage import LocalFileStore
        self.config = config
        if len(sources) > 200:
            raise ValueError('전체 RAG 자료는 200쪽 이하여야 합니다.')
        self.sources = {s['source_id']: s for s in sources}
        if len(self.sources) != len(sources):
            raise ValueError('중복 source_id가 있습니다.')
        cache_dir = Path(cache_dir)
        model_name = config['embedding_model']
        base = embeddings or BGEEmbeddings(model_name, os.getenv('EMBEDDING_CACHE', str(cache_dir / 'models')))
        self.base_embeddings = base
        self.embeddings = CacheBackedEmbeddings.from_bytes_store(
            base, LocalFileStore(str(cache_dir / 'embeddings')),
            namespace=hashlib.sha256((model_name + ':normalized-v1').encode()).hexdigest()[:16],
            query_embedding_cache=True, key_encoder='sha256')
        splitter = RecursiveCharacterTextSplitter(chunk_size=config['chunk_size'],
                                                  chunk_overlap=config['chunk_overlap'])
        self.chunks = []
        for source in sources:
            for i, text in enumerate(splitter.split_text(source['text'])):
                self.chunks.append(Document(page_content=text, metadata={
                    'source_id': source['source_id'], 'chunk_id': f"{source['source_id']}:c{i+1}",
                    'company_id': source['company_id'],
                    'doc_types': source.get('doc_types', [source['doc_type']])}))
        self.indexes = {}
        self.lock = threading.Lock()
        self.history = []

    def _scope(self, company_id, doc_type):
        def matches(d):
            owner = d.metadata['company_id']
            # 같은 기업의 자료는 수집 분류와 무관하게 공유합니다.
            # 기술 정보가 시장 기사에 포함되는 경우도 검색합니다.
            if company_id is not None and owner == company_id:
                return True
            if doc_type is None:
                return company_id is None or owner == company_id
            role_ok = doc_type in d.metadata['doc_types'] or ('company' in d.metadata['doc_types'] and owner == company_id)
            if doc_type == 'company':
                return role_ok and (company_id is None or owner == company_id)
            return role_ok and (owner == company_id or (doc_type == 'market' and owner == '__sector__'))
        return [d for d in self.chunks if matches(d)]

    def retrieve(self, question, company_id, doc_type, k=None):
        from langchain_community.vectorstores import FAISS
        if k is not None and (type(k) is not int or k < 1):
            raise ValueError('k는 1 이상의 정수여야 합니다.')
        key = (company_id, doc_type)
        with self.lock:
            if key not in self.indexes:
                documents = self._scope(company_id, doc_type)
                self.indexes[key] = FAISS.from_documents(documents, self.embeddings) if documents else None
            index = self.indexes[key]
        if index is None:
            with self.lock:
                self.history.append({'question': question, 'company_id': company_id, 'doc_type': doc_type,
                                     'chunk_ids': [], 'source_ids': []})
            return []
        docs = index.as_retriever(search_kwargs={'k': k or self.config['top_k']}).invoke(question)
        result = [{**self.sources[d.metadata['source_id']], 'chunk_id': d.metadata['chunk_id'],
                   'text': d.page_content} for d in docs]
        with self.lock:
            self.history.append({'question': question, 'company_id': company_id, 'doc_type': doc_type,
                                 'chunk_ids': [x['chunk_id'] for x in result],
                                 'source_ids': [x['source_id'] for x in result]})
        return result

    def evidence_for(self, queries, company_id, doc_type):
        selected = {}
        for query in queries:
            for chunk in self.retrieve(query, company_id, doc_type):
                selected[chunk['chunk_id']] = chunk
        return list(selected.values())

    def source_pages(self, chunks):
        return [self.sources[x] for x in dict.fromkeys(c['source_id'] for c in chunks)]
