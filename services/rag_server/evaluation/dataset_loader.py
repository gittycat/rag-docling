import json
from pathlib import Path
from pydantic import BaseModel


class GoldenQA(BaseModel):
    question: str
    answer: str
    document: str
    context_hint: str | None = None
    query_type: str | None = None


def load_golden_qa_dataset(dataset_path: str | Path) -> list[GoldenQA]:
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with open(dataset_path, "r") as f:
        data = json.load(f)

    return [GoldenQA(**item) for item in data]


def get_default_dataset_path() -> Path:
    return Path(__file__).parent.parent / "eval_data" / "golden_qa.json"


def load_default_dataset() -> list[GoldenQA]:
    return load_golden_qa_dataset(get_default_dataset_path())
