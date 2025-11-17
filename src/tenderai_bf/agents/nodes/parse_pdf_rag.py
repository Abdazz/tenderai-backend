"""RAG-based PDF parser for tender extraction using Chroma and LLM."""

import hashlib
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import docling
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from langchain.text_splitter import RecursiveCharacterTextSplitter

from ...config import settings
from ...logging import get_logger
from ...agents.extraction import extract_tenders_structured
from .vector_store import get_vector_store

logger = get_logger(__name__)


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF using Docling with fallback to pdfminer."""
    try:
        logger.info("Extracting text from PDF with OCR disabled", pdf_path=pdf_path)
        
        # Configure Docling to disable OCR
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False  # Disable OCR
        
        # Use DocumentConverter with OCR disabled
        converter = DocumentConverter(
            format_options={
                "pdf": PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        result = converter.convert(pdf_path)
        
        # Handle different Docling versions
        text = None
        
        # Try different ways to extract text based on API version
        if hasattr(result, 'document'):
            # Newer Docling versions have a .document attribute
            doc = result.document
            if hasattr(doc, 'export_to_markdown'):
                text = doc.export_to_markdown()
            elif hasattr(doc, 'render_as_markdown'):
                text = doc.render_as_markdown()
            elif hasattr(doc, 'export_to_text'):
                text = doc.export_to_text()
            elif hasattr(doc, 'text'):
                text = doc.text
        elif hasattr(result, 'render_as_markdown'):
            # Direct document object
            text = result.render_as_markdown()
        elif hasattr(result, 'export_to_markdown'):
            text = result.export_to_markdown()
        elif hasattr(result, 'export_to_text'):
            text = result.export_to_text()
        elif hasattr(result, 'text'):
            text = result.text
        
        if text:
            logger.info("PDF text extracted successfully with Docling", pdf_path=pdf_path, text_length=len(text))
            return text
        else:
            raise ValueError("Unable to extract text from Docling result - no suitable method found")
        
    except Exception as e:
        logger.error("Docling extraction failed, falling back to pdfminer", error=str(e), pdf_path=pdf_path)
        # Fallback to pdfminer if Docling fails
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            text = pdfminer_extract(pdf_path)
            logger.info("Fallback to pdfminer successful", pdf_path=pdf_path)
            return text
        except Exception as fallback_error:
            logger.error("Fallback extraction failed", error=str(fallback_error), exc_info=True)
            raise


def split_into_chunks(text: str, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None) -> List[str]:
    """Split text into overlapping chunks using RecursiveCharacterTextSplitter.
    
    This respects semantic boundaries (paragraphs, sentences, words) rather than
    blindly cutting at character count, producing higher quality chunks for RAG.
    """
    if chunk_size is None:
        chunk_size = settings.rag.chunk_size
    if chunk_overlap is None:
        chunk_overlap = settings.rag.chunk_overlap
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],  # Try these in order
        length_function=len,
        is_separator_regex=False
    )
    
    chunks = splitter.split_text(text)
    logger.info(
        "Text split into chunks using RecursiveCharacterTextSplitter",
        chunk_count=len(chunks),
        avg_chunk_size=len(text) // len(chunks) if chunks else 0
    )
    
    return chunks


def index_pdf_in_vector_store(
    pdf_path: str,
    source_name: str,
    filename: str,
    metadata: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Index PDF content in vector store."""
    try:
        # Extract text
        text = extract_text_from_pdf(pdf_path)
        
        # Split into chunks
        chunks = split_into_chunks(text)
        logger.info(
            "PDF split into chunks",
            pdf_path=pdf_path,
            chunk_count=len(chunks)
        )
        
        # Prepare metadata for each chunk
        base_metadata = {
            "source": source_name,
            "filename": filename,
            "date": datetime.now().isoformat(),
            "text_length": len(text)
        }
        
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_meta = base_metadata.copy()
            chunk_meta["page_number"] = i + 1
            chunk_meta["chunk_size"] = len(chunk)
            if metadata:
                chunk_meta.update(metadata)
            metadatas.append(chunk_meta)
        
        # Add to vector store
        vector_store = get_vector_store()
        doc_ids = vector_store.add_documents(
            source_name=source_name,
            documents=chunks,
            metadatas=metadatas
        )
        
        logger.info(
            "PDF indexed in vector store",
            pdf_path=pdf_path,
            source=source_name,
            indexed_documents=len(doc_ids)
        )
        
        return doc_ids
        
    except Exception as e:
        logger.error("Failed to index PDF", pdf_path=pdf_path, error=str(e), exc_info=True)
        raise


def query_tenders_from_index(
    source_name: str,
    query: str = "Extract all public procurement tenders",
    top_k: Optional[int] = None
) -> Dict[str, Any]:
    """Query similar documents from vector store."""
    try:
        vector_store = get_vector_store()
        
        results = vector_store.query_similar(
            source_name=source_name,
            query=query,
            top_k=top_k or settings.rag.top_k_results
        )
        
        logger.info(
            "Vector store query completed",
            source=source_name,
            results_count=len(results.get('documents', [[]])[0]) if results.get('documents') else 0
        )
        
        return results
        
    except Exception as e:
        logger.error("Failed to query vector store", source=source_name, error=str(e), exc_info=True)
        raise


def extract_tenders_with_llm(
    relevant_contexts: List[str],
    source_name: str
) -> List[Dict[str, Any]]:
    """Extract structured tender data using LLM with Pydantic validation."""
    try:
        # Prepare context - join the retrieved documents
        context = "\n\n".join(relevant_contexts[:settings.rag.top_k_results])
        
        logger.info(
            "Calling LLM for structured tender extraction",
            source=source_name,
            context_length=len(context),
            num_chunks=len(relevant_contexts)
        )
        
        # Log context preview for debugging
        logger.debug(
            "Context preview for LLM extraction",
            source=source_name,
            context_preview=context[:500],
            total_context_length=len(context)
        )
        
        # Use structured extraction with Pydantic validation
        extraction = extract_tenders_structured(
            context=context,
            source_name=source_name,
            max_retries=2
        )
        
        logger.info(
            "LLM extraction completed",
            source=source_name,
            extracted_tenders=extraction.total_extracted,
            confidence=extraction.confidence
        )
        
        # Convert Pydantic models to dicts
        tenders = [tender.model_dump() for tender in extraction.tenders]
        
        return tenders
        
    except ImportError as ie:
        logger.error("Required module not installed", error=str(ie))
        return []
    except Exception as e:
        logger.error("LLM extraction failed", error=str(e), exc_info=True)
        return []


def parse_pdf_with_rag(
    pdf_path: str,
    source_name: str,
    filename: str,
    metadata: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
    pdf_content: Optional[bytes] = None,
    use_direct_extraction: bool = True  # NEW: Skip RAG and extract directly from full text
) -> List[Dict[str, Any]]:
    """Parse PDF using RAG system or direct extraction.
    
    Args:
        pdf_path: Path to PDF file or URL
        source_name: Name of the source
        filename: Filename of the PDF
        metadata: Additional metadata
        use_llm: Whether to use LLM for extraction
        pdf_content: Optional PDF bytes (if provided, pdf_path is used for logging only)
        use_direct_extraction: If True, extract from full PDF text directly without RAG
    """
    try:
        # Log configuration at the start
        from ...utils.llm_utils import get_llm_instance
        
        llm = get_llm_instance()
        llm_model = getattr(llm, 'model_name', getattr(llm, 'model', 'unknown'))
        llm_provider = getattr(settings.llm, 'provider', 'unknown')
        
        logger.info(
            "Starting PDF parsing",
            pdf_path=pdf_path,
            source=source_name,
            use_llm=use_llm,
            use_direct_extraction=use_direct_extraction,
            has_content=pdf_content is not None,
            llm_provider=llm_provider,
            llm_model=llm_model,
            chunk_size=settings.rag.chunk_size,
            chunk_overlap=settings.rag.chunk_overlap
        )
        
        # If pdf_content is provided, save to temp file
        temp_file = None
        if pdf_content:
            temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            temp_file.write(pdf_content)
            temp_file.close()
            pdf_path = temp_file.name
            logger.info("PDF content saved to temp file", temp_path=pdf_path)
        
        # DIRECT EXTRACTION MODE: Extract all text and pass to LLM in chunks
        if use_direct_extraction:
            logger.info("Using DIRECT extraction mode (no RAG)", source=source_name)
            
            # Extract full text from PDF
            full_text = extract_text_from_pdf(pdf_path)
            
            logger.info(
                "Full PDF text extracted",
                source=source_name,
                text_length=len(full_text),
                text_preview=full_text[:500] if full_text else None
            )
            
            # Split into chunks to avoid token limits
            chunks = split_into_chunks(full_text)
            
            logger.info(
                "Text split into chunks for processing",
                source=source_name,
                num_chunks=len(chunks),
                avg_chunk_size=sum(len(c) for c in chunks) // len(chunks) if chunks else 0
            )
            
            # Process each chunk and collect all tenders
            all_tenders = []
            
            if use_llm and chunks:
                for i, chunk in enumerate(chunks, 1):
                    logger.info(
                        f"Processing chunk {i}/{len(chunks)}",
                        source=source_name,
                        chunk_size=len(chunk)
                    )
                    
                    try:
                        extraction = extract_tenders_structured(
                            context=chunk,
                            source_name=source_name,
                            max_retries=2
                        )
                        
                        # Add tenders from this chunk
                        chunk_tenders = []
                        for j, tender in enumerate(extraction.tenders, 1):
                            tender_dict = {
                                **tender.dict(),
                                'id': f"{source_name}_{i}_{j}",
                                'source': source_name,
                                'chunk_index': i
                            }
                            
                            # Generate content_hash for deduplication
                            hash_content = (
                                f"{tender_dict.get('type', '')}"
                                f"{tender_dict.get('entity', '')}"
                                f"{tender_dict.get('reference', '')}"
                                f"{tender_dict.get('tender_object', '')}"
                                f"{tender_dict.get('deadline', '')}"
                            )
                            tender_dict['content_hash'] = hashlib.sha256(hash_content.encode()).hexdigest()
                            
                            chunk_tenders.append(tender_dict)
                        
                        all_tenders.extend(chunk_tenders)
                        
                        logger.info(
                            f"Chunk {i} processed",
                            source=source_name,
                            tenders_found=len(chunk_tenders),
                            total_so_far=len(all_tenders)
                        )
                        
                    except Exception as e:
                        logger.error(
                            f"Failed to process chunk {i}",
                            source=source_name,
                            error=str(e)
                        )
                        continue
                
                logger.info(
                    "Direct extraction completed",
                    source=source_name,
                    total_chunks_processed=len(chunks),
                    total_tenders_extracted=len(all_tenders)
                )
                
                # Clean up temp file
                if temp_file:
                    import os
                    os.unlink(temp_file.name)
                
                return all_tenders
            else:
                logger.error("LLM not available or no chunks extracted", source=source_name)
                if temp_file:
                    import os
                    os.unlink(temp_file.name)
                return []
        
        # RAG MODE (original logic)
        logger.info("Using RAG extraction mode with ChromaDB", source=source_name)
        
        # Step 1: Index PDF content
        doc_ids = index_pdf_in_vector_store(
            pdf_path=pdf_path,
            source_name=source_name,
            filename=filename,
            metadata=metadata
        )
        
        # Step 2: Query similar documents
        # Use semantic query from settings (in French to match the documents)
        search_query = settings.rag.chroma.vector_search_query
        logger.info(
            "Using vector search query from settings",
            source=source_name,
            query=search_query
        )
        results = query_tenders_from_index(
            source_name=source_name,
            query=search_query
        )
        
        # Extract context documents from Chroma results
        # Chroma returns: {'documents': [[doc1, doc2, ...]], 'metadatas': [...], 'distances': [...], 'ids': [...]}
        # We want the first (and only) query result, which is a list of documents
        relevant_contexts = []
        if results.get('documents') and len(results['documents']) > 0 and results['documents'][0]:
            relevant_contexts = results['documents'][0]
        
        # Log detailed chunk information for debugging
        logger.info(
            "ChromaDB query results summary",
            source=source_name,
            total_chunks_returned=len(relevant_contexts),
            has_metadatas=bool(results.get('metadatas')),
            has_distances=bool(results.get('distances')),
            has_ids=bool(results.get('ids'))
        )
        
        # Log each chunk in detail
        if results.get('documents') and results['documents'][0]:
            metadatas = results.get('metadatas', [[]])[0] if results.get('metadatas') else []
            distances = results.get('distances', [[]])[0] if results.get('distances') else []
            ids = results.get('ids', [[]])[0] if results.get('ids') else []
            
            for idx, doc in enumerate(relevant_contexts):
                metadata = metadatas[idx] if idx < len(metadatas) else {}
                distance = distances[idx] if idx < len(distances) else None
                doc_id = ids[idx] if idx < len(ids) else None
                
                logger.info(
                    f"Chunk {idx + 1} details",
                    source=source_name,
                    chunk_id=doc_id,
                    distance=distance,
                    chunk_length=len(doc),
                    chunk_preview=doc if doc else None,
                    metadata=metadata
                )
        
        logger.info(
            "Retrieved relevant contexts from vector store",
            source=source_name,
            context_count=len(relevant_contexts),
            total_documents_indexed=len(results.get('ids', [[]])[0]) if results.get('ids') else 0
        )
        
        # Step 3: Extract tenders with LLM
        tenders = []
        if use_llm and relevant_contexts:
            tenders = extract_tenders_with_llm(
                relevant_contexts=relevant_contexts,
                source_name=source_name
            )
        else:
            logger.info("LLM extraction disabled or no context available")
        
        # Ensure all tenders have required fields and map to report format
        for idx, tender in enumerate(tenders):
            if isinstance(tender, dict):
                tender.setdefault('id', f"{source_name}_{idx}_{int(time.time())}")
                tender.setdefault('source', source_name)
                tender.setdefault('extracted_at', datetime.now().isoformat())
                
                # Map fields to what the report expects
                # title: Use first 100 chars of description or entity name
                if 'title' not in tender or not tender['title']:
                    if tender.get('description'):
                        tender['title'] = tender['description'][:100]
                    else:
                        tender['title'] = tender.get('entity', 'Appel d\'offres')
                
                # ref_no: Map from reference
                tender['ref_no'] = tender.get('reference', 'N/A')
                
                # source_url: Get from metadata (URL of the PDF quotidien)
                if metadata and metadata.get('url'):
                    tender['source_url'] = metadata['url']
                else:
                    tender['source_url'] = pdf_path
                
                # url: Also set url field for backward compatibility
                tender['url'] = tender.get('source_url', pdf_path)
                
                # deadline_at: Keep deadline as is
                tender['deadline_at'] = tender.get('deadline', 'N/A')
                
                # published_at: Extract from quotidien title (e.g., "QUOTIDIEN No 001 - 02/01/2025")
                # or use metadata if available
                published_at = 'N/A'
                if metadata and metadata.get('title'):
                    import re
                    # Try to extract date from title like "QUOTIDIEN No 001 - 02/01/2025"
                    date_match = re.search(r'(\d{2}/\d{2}/\d{4})', metadata['title'])
                    if date_match:
                        published_at = date_match.group(1)
                tender['published_at'] = published_at
                
                # is_relevant: Based on relevance_score
                relevance_score = tender.get('relevance_score', 0.0)
                tender['is_relevant'] = relevance_score >= 0.5
                
                # Generate unique content_hash for each tender based on its specific content
                # Use entity + reference + description to create a unique hash
                hash_content = (
                    f"{tender.get('entity', '')}"
                    f"{tender.get('reference', '')}"
                    f"{tender.get('description', '')}"
                    f"{tender.get('deadline', '')}"
                )
                tender['content_hash'] = hashlib.sha256(hash_content.encode()).hexdigest()
        
        logger.info(
            "RAG parsing completed successfully",
            pdf_path=pdf_path,
            source=source_name,
            extracted_tenders=len(tenders)
        )
        
        return tenders
        
    except Exception as e:
        logger.error(
            "RAG parsing failed",
            pdf_path=pdf_path,
            source=source_name,
            error=str(e),
            exc_info=True
        )
        raise
