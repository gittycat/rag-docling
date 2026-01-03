"""Dataset registry for evaluation v2."""

from evaluation_v2.data_models import (
    EvaluationDataset,
    EvalDocument,
    EvalTestCase,
    DatasetInfo,
)
from evaluation_v2.datasets.ragbench import RAGBenchDataset
from evaluation_v2.datasets.qasper import QasperDataset
from evaluation_v2.datasets.squad_v2 import SquadV2Dataset
from evaluation_v2.datasets.hotpotqa import HotpotQADataset
from evaluation_v2.datasets.ms_marco import MSMARCODataset

__all__ = [
    "EvaluationDataset",
    "EvalDocument",
    "EvalTestCase",
    "DatasetInfo",
    "RAGBenchDataset",
    "QasperDataset",
    "SquadV2Dataset",
    "HotpotQADataset",
    "MSMARCODataset",
    "get_dataset",
    "list_datasets",
]

DATASET_REGISTRY: dict[str, type[EvaluationDataset]] = {
    "ragbench": RAGBenchDataset,
    "qasper": QasperDataset,
    "squad_v2": SquadV2Dataset,
    "hotpotqa": HotpotQADataset,
    "ms_marco": MSMARCODataset,
}


def get_dataset(name: str, **kwargs) -> EvaluationDataset:
    name_lower = name.lower()
    if name_lower not in DATASET_REGISTRY:
        available = ", ".join(DATASET_REGISTRY.keys())
        raise ValueError(f"Unknown dataset: {name}. Available: {available}")
    return DATASET_REGISTRY[name_lower](**kwargs)


def list_datasets() -> list[str]:
    return list(DATASET_REGISTRY.keys())
