from pathlib import Path
from typing import List
from llama_index.readers.docling import DoclingReader
from llama_index.node_parser.docling import DoclingNodeParser
from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document
import logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    '.txt', '.md', '.pdf', '.docx', '.pptx', '.xlsx',
    '.html', '.htm', '.asciidoc', '.adoc'
}

SIMPLE_TEXT_EXTENSIONS = {'.txt', '.md'}

def chunk_document_from_file(file_path: str, chunk_size: int = 500):
    logger.info(f"[DOCLING] chunk_document_from_file called for: {file_path}")
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()
    logger.info(f"[DOCLING] File extension: {extension}, chunk_size: {chunk_size}")

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")

    if extension in SIMPLE_TEXT_EXTENSIONS:
        logger.info(f"[DOCLING] Using SimpleDirectoryReader for text file")
        reader = SimpleDirectoryReader(input_files=[str(file_path)])
        documents = reader.load_data()
        logger.info(f"[DOCLING] SimpleDirectoryReader returned {len(documents)} documents")

        if not documents:
            error_msg = f"Could not load document: {file_path}"
            logger.error(f"[DOCLING] {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"[DOCLING] Using SentenceSplitter for chunking")
        splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=50)
        nodes = splitter.get_nodes_from_documents(documents)
        logger.info(f"[DOCLING] SentenceSplitter returned {len(nodes)} nodes")
    else:
        logger.info(f"[DOCLING] Using DoclingReader for complex document")
        reader = DoclingReader()

        logger.info(f"[DOCLING] Loading document with DoclingReader")
        documents = reader.load_data(file_path=str(file_path))
        logger.info(f"[DOCLING] DoclingReader returned {len(documents)} documents")

        if not documents:
            error_msg = f"Could not load document: {file_path}"
            logger.error(f"[DOCLING] {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"[DOCLING] Using DoclingNodeParser")
        node_parser = DoclingNodeParser()
        nodes = node_parser.get_nodes_from_documents(documents)
        logger.info(f"[DOCLING] DoclingNodeParser returned {len(nodes)} nodes")

    if nodes:
        first_text = nodes[0].get_content()
        preview = first_text[:80] + "..." if len(first_text) > 80 else first_text
        logger.info(f"[DOCLING] First node preview: {preview}")

    logger.info(f"[DOCLING] Created {len(nodes)} nodes from {file_path_obj.name}")
    return nodes


def extract_metadata(file_path: str) -> dict[str, str]:
    file_path_obj = Path(file_path)

    return {
        "file_name": file_path_obj.name,
        "file_type": file_path_obj.suffix,
        "path": str(file_path_obj.parent)
    }
