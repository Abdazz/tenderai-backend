"""Vector store management for RAG system using Chroma."""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from ...config import settings
from ...logging import get_logger

logger = get_logger(__name__)


class VectorStore:
    """Manages vector embeddings and similarity search using Chroma."""
    
    def __init__(self):
        """Initialize Chroma vector store."""
        self.rag_config = settings.rag
        self.collection_prefix = self.rag_config.chroma.collection_prefix
        
        # Initialize embedding model (Chroma 1.3.4+ has built-in embeddings)
        logger.info(
            "Initializing vector store",
            embedding_model=self.rag_config.embedding_model,
            chroma_version="1.3.4+"
        )
        
        # Initialize Chroma client
        self._init_chroma_client()
    
    def _init_chroma_client(self) -> None:
        """Initialize Chroma client with persistence (Chroma 1.3.4+ API)."""
        persist_dir = Path(self.rag_config.chroma.persist_directory)
        persist_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            "Initializing Chroma client",
            persist_directory=str(persist_dir),
            mode="persistent"
        )
        
        # Chroma 1.3.4+ uses simplified persistent client
        self.client = chromadb.PersistentClient(
            path=str(persist_dir)
        )
    
    def get_or_create_collection(
        self,
        source_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Get or create a collection for a source (Chroma 1.3.4+)."""
        collection_name = f"{self.collection_prefix}_{source_name.replace(' ', '_').lower()}"
        
        logger.debug(
            "Getting or creating collection",
            collection_name=collection_name,
            source=source_name
        )
        
        # Chroma 1.3.4+ uses get_or_create_collection
        collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata=metadata or {"source": source_name, "created": datetime.now().isoformat()},
            # Use default embeddings (all-MiniLM-L6-v2)
        )
        
        return collection
    
    def add_documents(
        self,
        source_name: str,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """Add documents to the vector store (Chroma 1.3.4+)."""
        if not documents:
            logger.error("No documents to add", source=source_name)
            return []
        
        collection = self.get_or_create_collection(source_name)
        
        # Generate IDs if not provided
        if ids is None:
            ids = [
                hashlib.md5(f"{source_name}_{doc}_{i}".encode()).hexdigest()
                for i, doc in enumerate(documents)
            ]
        
        logger.info(
            "Adding documents to Chroma",
            source=source_name,
            document_count=len(documents),
            collection=collection.name
        )
        
        # Chroma 1.3.4+ automatically generates embeddings
        # No need to pass embeddings parameter
        try:
            collection.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
        except Exception as e:
            logger.error(
                "Failed to upsert documents",
                error=str(e),
                source=source_name,
                exc_info=True
            )
            raise
        
        logger.info(
            "Documents added successfully",
            source=source_name,
            added_count=len(documents)
        )
        
        return ids
    
    def query_similar(
        self,
        source_name: str,
        query: str,
        top_k: Optional[int] = None,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Query similar documents (Chroma 1.3.4+)."""
        if top_k is None:
            top_k = self.rag_config.top_k_results
        
        collection = self.get_or_create_collection(source_name)
        
        logger.debug(
            "Querying similar documents",
            source=source_name,
            query=query[:100],  # Log first 100 chars
            top_k=top_k
        )
        
        try:
            # Chroma 1.3.4+ query API
            results = collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where
            )
            
            logger.debug(
                "Chroma query results",
                source=source_name,
                documents_count=len(results.get('documents', [[]])[0]) if results.get('documents') else 0,
                has_documents=bool(results.get('documents')),
                has_metadatas=bool(results.get('metadatas')),
                has_distances=bool(results.get('distances')),
                has_ids=bool(results.get('ids')),
                top_k=top_k
            )
            
            # Log first result distances if available
            if results.get('distances') and results['distances'][0]:
                logger.debug(
                    "Query distances",
                    source=source_name,
                    distances=results['distances'][0][:3]  # Log first 3 distances
                )
            
            return results
        except Exception as e:
            logger.error(
                "Query failed",
                error=str(e),
                source=source_name,
                exc_info=True
            )
            raise
    
    def delete_source_documents(
        self,
        source_name: str,
        where: Optional[Dict[str, Any]] = None
    ) -> int:
        """Delete documents from a source."""
        collection = self.get_or_create_collection(source_name)
        
        logger.info(
            "Deleting documents",
            source=source_name,
            collection=collection.name
        )
        
        try:
            if where:
                # Delete with filter
                collection.delete(where=where)
            else:
                # Delete all documents for this source
                collection.delete(where={"source": source_name})
            
            return collection.count()
        except Exception as e:
            logger.error(
                "Delete failed",
                error=str(e),
                source=source_name,
                exc_info=True
            )
            raise
    
    def get_collection_stats(self, source_name: str) -> Dict[str, Any]:
        """Get statistics about a collection."""
        collection = self.get_or_create_collection(source_name)
        
        stats = {
            "collection_name": collection.name,
            "document_count": collection.count(),
            "metadata": collection.metadata
        }
        
        return stats
    
    def list_collections(self) -> List[str]:
        """List all collections in the vector store."""
        collections = self.client.list_collections()
        return [c.name for c in collections]
    
    def reset_collection(self, source_name: str) -> None:
        """Reset/delete a collection."""
        collection_name = f"{self.collection_prefix}_{source_name.replace(' ', '_').lower()}"
        
        logger.error(
            "Resetting collection",
            source=source_name,
            collection=collection_name
        )
        
        try:
            self.client.delete_collection(name=collection_name)
        except Exception as e:
            logger.error(
                "Failed to delete collection",
                error=str(e),
                collection=collection_name
            )
    
    def close(self) -> None:
        """Close the vector store connection."""
        logger.info("Closing vector store")
        # Chroma handles cleanup automatically


# Global vector store instance
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get or create the global vector store instance."""
    global _vector_store
    
    if _vector_store is None:
        logger.info("Initializing global vector store")
        try:
            _vector_store = VectorStore()
        except Exception as e:
            logger.error(
                "Failed to initialize vector store",
                error=str(e),
                exc_info=True
            )
            raise
    
    return _vector_store


def initialize_vector_store() -> None:
    """Initialize the global vector store."""
    get_vector_store()
