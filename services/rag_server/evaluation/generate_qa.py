"""Generate synthetic Q&A pairs from documents using Claude.

This module provides utilities for automatically generating diverse Q&A pairs
from documents to expand the golden dataset for evaluation.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional
from anthropic import Anthropic


GENERATION_PROMPT = """Given this document, generate {num_questions} diverse Q&A pairs for RAG evaluation.

Requirements:
- Mix of factual (direct lookup) and reasoning (inference) questions
- Include easy, medium, and hard difficulty levels
- Questions should require specific context from the document
- Answers should be concise but complete (1-3 sentences)
- Each question should test a different aspect or section of the document

Document:
{document_text}

Output ONLY a valid JSON array with this exact structure (no markdown, no explanation):
[
  {{
    "question": "...",
    "answer": "...",
    "query_type": "factual",
    "difficulty": "easy",
    "context_hint": "brief hint about where answer is found"
  }},
  ...
]

Make sure to output ONLY the JSON array, nothing else."""


def generate_qa_for_document(
    doc_path: Path,
    num_questions: int = 10,
    model: str = "claude-sonnet-4-20250514",
    max_chars: int = 15000,
) -> List[dict]:
    """Generate Q&A pairs for a single document using Claude.

    Args:
        doc_path: Path to document file
        num_questions: Number of Q&A pairs to generate (default: 10)
        model: Claude model to use (default: claude-sonnet-4-20250514)
        max_chars: Maximum characters to send (default: 15000)

    Returns:
        List of generated Q&A dictionaries

    Raises:
        ValueError: If ANTHROPIC_API_KEY is not set
        FileNotFoundError: If document doesn't exist
        json.JSONDecodeError: If Claude response is not valid JSON

    Example:
        >>> qa_pairs = generate_qa_for_document(Path("document.txt"), num_questions=5)
        >>> print(f"Generated {len(qa_pairs)} Q&A pairs")
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is required")

    if not doc_path.exists():
        raise FileNotFoundError(f"Document not found: {doc_path}")

    # Read document
    text = doc_path.read_text()

    # Truncate if too long
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Document truncated...]"

    # Call Claude
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": GENERATION_PROMPT.format(
                    num_questions=num_questions, document_text=text
                ),
            }
        ],
    )

    # Parse response
    response_text = response.content[0].text.strip()

    # Remove markdown code blocks if present
    if response_text.startswith("```"):
        # Extract JSON from markdown code block
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text

    try:
        qa_pairs = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"Failed to parse Claude response as JSON: {response_text[:200]}...",
            e.doc,
            e.pos,
        )

    # Add document ID
    doc_id = doc_path.stem
    for qa in qa_pairs:
        qa["document"] = doc_id

    return qa_pairs


def generate_qa_for_directory(
    dir_path: Path,
    num_questions_per_doc: int = 10,
    file_pattern: str = "*.txt",
    output_path: Optional[Path] = None,
    model: str = "claude-sonnet-4-20250514",
) -> List[dict]:
    """Generate Q&A pairs for all documents in a directory.

    Args:
        dir_path: Directory containing documents
        num_questions_per_doc: Number of Q&A pairs per document
        file_pattern: Glob pattern for files (default: "*.txt")
        output_path: Optional path to save results
        model: Claude model to use

    Returns:
        List of all generated Q&A dictionaries

    Example:
        >>> qa_pairs = generate_qa_for_directory(
        ...     Path("./documents"),
        ...     num_questions_per_doc=5,
        ...     output_path=Path("generated_qa.json")
        ... )
    """
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {dir_path}")

    all_qa = []
    docs = list(dir_path.glob(file_pattern))

    print(f"Found {len(docs)} documents matching {file_pattern}")

    for doc_path in docs:
        print(f"Generating Q&A for {doc_path.name}...")
        try:
            qa_pairs = generate_qa_for_document(
                doc_path, num_questions=num_questions_per_doc, model=model
            )
            all_qa.extend(qa_pairs)
            print(f"  ✓ Generated {len(qa_pairs)} Q&A pairs")
        except Exception as e:
            print(f"  ✗ Error: {e}")

    print(f"\nTotal generated: {len(all_qa)} Q&A pairs")

    # Save if output path provided
    if output_path:
        save_generated_qa(all_qa, output_path)
        print(f"Saved to {output_path}")

    return all_qa


def save_generated_qa(qa_pairs: List[dict], output_path: Path) -> None:
    """Save generated Q&A pairs to JSON file.

    Args:
        qa_pairs: List of Q&A dictionaries
        output_path: Path to save JSON file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(qa_pairs, f, indent=2)


def merge_with_golden_dataset(
    generated_qa: List[dict],
    golden_dataset_path: Path,
    output_path: Path,
) -> None:
    """Merge generated Q&A with existing golden dataset.

    Args:
        generated_qa: List of generated Q&A dictionaries
        golden_dataset_path: Path to existing golden_qa.json
        output_path: Path to save merged dataset

    Example:
        >>> generated = generate_qa_for_document(Path("doc.txt"))
        >>> merge_with_golden_dataset(
        ...     generated,
        ...     Path("eval_data/golden_qa.json"),
        ...     Path("eval_data/golden_qa_expanded.json")
        ... )
    """
    # Load existing dataset
    with open(golden_dataset_path, "r") as f:
        existing_data = json.load(f)

    # Handle both list format and dict format
    if isinstance(existing_data, dict):
        existing_qa = existing_data.get("test_cases", [])
    else:
        existing_qa = existing_data

    # Merge
    merged_qa = existing_qa + generated_qa

    # Add IDs if missing
    for i, qa in enumerate(merged_qa):
        if "id" not in qa:
            qa["id"] = f"tc{i+1:03d}"

    # Save in v2.0 format
    output_data = {
        "version": "2.0",
        "created": "2025-12-07",
        "test_cases": merged_qa,
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"Merged {len(existing_qa)} existing + {len(generated_qa)} generated")
    print(f"Total: {len(merged_qa)} Q&A pairs")


def main():
    """CLI for generating Q&A pairs."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic Q&A pairs")
    parser.add_argument("input", type=Path, help="Document file or directory")
    parser.add_argument(
        "-n",
        "--num-questions",
        type=int,
        default=10,
        help="Number of questions per document",
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="Output JSON file (default: stdout)"
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model to use",
    )
    parser.add_argument(
        "--pattern",
        default="*.txt",
        help="File pattern for directory (default: *.txt)",
    )
    args = parser.parse_args()

    # Generate
    if args.input.is_file():
        qa_pairs = generate_qa_for_document(
            args.input, num_questions=args.num_questions, model=args.model
        )
    elif args.input.is_dir():
        qa_pairs = generate_qa_for_directory(
            args.input,
            num_questions_per_doc=args.num_questions,
            file_pattern=args.pattern,
            model=args.model,
        )
    else:
        print(f"Error: {args.input} is not a file or directory")
        return

    # Output
    if args.output:
        save_generated_qa(qa_pairs, args.output)
        print(f"Saved {len(qa_pairs)} Q&A pairs to {args.output}")
    else:
        print(json.dumps(qa_pairs, indent=2))


if __name__ == "__main__":
    main()
