from pydantic import BaseModel


class DocumentListResponse(BaseModel):
    documents: list[dict]


class DeleteResponse(BaseModel):
    status: str
    message: str


class UploadResponse(BaseModel):
    status: str
    uploaded: int
    documents: list[dict]


class TaskInfo(BaseModel):
    task_id: str
    filename: str


class BatchUploadResponse(BaseModel):
    status: str
    batch_id: str
    tasks: list[TaskInfo]


class BatchProgressResponse(BaseModel):
    batch_id: str
    total: int
    completed: int
    tasks: dict


class FileCheckItem(BaseModel):
    filename: str
    size: int
    hash: str


class FileCheckRequest(BaseModel):
    files: list[FileCheckItem]


class FileCheckResult(BaseModel):
    filename: str
    exists: bool
    document_id: str | None = None
    existing_filename: str | None = None
    reason: str | None = None


class FileCheckResponse(BaseModel):
    results: dict[str, FileCheckResult]
