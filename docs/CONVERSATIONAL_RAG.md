# Conversational RAG Architecture

## Overview

The system uses LlamaIndex's `ChatEngine` with `condense_plus_context` mode for multi-turn conversations. Each user session maintains conversation history in memory, enabling context-aware follow-up questions.

## Chat Engine Mode: condense_plus_context

### How It Works

1. Takes the latest user question + conversation history
2. Reformulates the question into a standalone query (e.g., "What about his views on startups?" → "What are Paul Graham's views on startups?")
3. Retrieves relevant context from the vector store using the reformulated query
4. Passes both the reformulated query AND chat history to the LLM
5. Generates response with full conversational context

### Why This Mode

- Most versatile: Handles both knowledge base queries AND conversational questions
- Can answer meta-questions like "What was my first question?"
- Automatically contextualizes ambiguous follow-ups ("What about X?" requires prior context)
- Better than `context` mode (doesn't contextualize) or `condense_question` mode (struggles with meta-questions)

## Session Management

### Session ID

- UUID generated client-side
- Stored in `localStorage` for persistence across page reloads
- Each session has independent conversation history

### In-Memory Storage

- `SimpleChatStore` stores chat history per session
- Survives container restarts within same process
- Suitable for single-user/development scenarios
- Production would need Redis or database backing

### Session Isolation

Each session maintains:
- Independent conversation history
- Separate chat memory buffer
- Isolated context tracking

## Chat Memory Configuration

### Token Limit

Auto-detected from LLM's context window (50% allocation):
- gemma3:4b: 131K context window → 65K tokens for chat history
- Remaining tokens: ~40% for retrieved context, ~10% for response

### Memory Management

- `ChatMemoryBuffer` automatically truncates old messages when token limit reached
- Strategy: Sliding window - keeps most recent messages within token budget
- Older messages dropped first to stay within limit

### Context Window Detection

Automatically introspects model's context window:
```python
context_window = Settings.llm.metadata.context_window
chat_memory_tokens = int(context_window * 0.5)  # 50% allocation
```

## Chat History UI

### Style

Claude Chat/ChatGPT-like interface:
- Full conversation history displayed above
- Fixed input at bottom
- Clean, modern design

### Layout Components

- **User messages**: Blue bubble, right-aligned
- **Assistant messages**: Left-aligned, markdown-rendered
- **Auto-scroll**: Scrolls to bottom on new messages
- **New Chat button**: Clears session and reloads page

### UI Implementation

Location: `services/fastapi_web_app/templates/home.html`

Key features:
- Session ID stored in localStorage
- JavaScript fetches chat history after each query
- Markdown rendering for assistant responses
- Smooth scrolling to new messages

## API Endpoints

### POST /query

Accepts conversational queries with session tracking:

**Request:**
```json
{
  "query": "What does Paul Graham say about startups?",
  "session_id": "abc123-def456-..."  // Optional, auto-generates if missing
}
```

**Response:**
```json
{
  "answer": "Paul Graham discusses...",
  "sources": [...],
  "session_id": "abc123-def456-..."
}
```

### GET /chat/history/{session_id}

Returns full conversation history for session:

**Response:**
```json
{
  "session_id": "abc123-def456-...",
  "messages": [
    {"role": "user", "content": "What does Paul Graham say about startups?"},
    {"role": "assistant", "content": "Paul Graham discusses..."}
  ]
}
```

### POST /chat/clear

Clears chat history for session:

**Request:**
```json
{
  "session_id": "abc123-def456-..."
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Chat history cleared for session abc123-def456-..."
}
```

## Model Flexibility

### LLM Model Configuration

Configured via `LLM_MODEL` env var (default: gemma3:4b):
```bash
LLM_MODEL=llama3:8b  # Switch to different model
```

### Embeddings Configuration

Configured via `EMBEDDING_MODEL` env var (default: nomic-embed-text):
```bash
EMBEDDING_MODEL=qwen3-embedding:8b  # Switch embeddings
```

### Automatic Context Window Adjustment

- System automatically detects model's context window
- Chat memory token limit adjusts based on detected window
- No code changes needed when switching models
- Just rebuild containers after changing env vars

Example:
```python
# Automatic detection at startup
context_window = Settings.llm.metadata.context_window
print(f"Detected context window: {context_window} tokens")

# Allocate 50% for chat history
chat_memory_tokens = int(context_window * 0.5)
```

## Implementation Files

### Backend

- `services/rag_server/core_logic/chat_memory.py`: Session-based `ChatMemoryBuffer` management
- `services/rag_server/core_logic/rag_pipeline.py`: `index.as_chat_engine(chat_mode="condense_plus_context")`
- `services/rag_server/main.py`: API endpoints with session_id support

### Frontend

- `services/fastapi_web_app/main.py`: Session management + chat history retrieval
- `services/fastapi_web_app/templates/home.html`: Conversational UI with history display

## Key Functions

### get_or_create_chat_memory(session_id)

Returns `ChatMemoryBuffer` for session:
```python
def get_or_create_chat_memory(session_id: str) -> ChatMemoryBuffer:
    if session_id not in SESSION_MEMORIES:
        token_limit = get_token_limit_for_chat_history()
        SESSION_MEMORIES[session_id] = ChatMemoryBuffer.from_defaults(
            token_limit=token_limit
        )
    return SESSION_MEMORIES[session_id]
```

### get_token_limit_for_chat_history()

Introspects LLM context window and allocates 50% for chat history:
```python
def get_token_limit_for_chat_history() -> int:
    context_window = Settings.llm.metadata.context_window
    return int(context_window * 0.5)
```

### get_chat_history(session_id)

Returns list of `ChatMessage` objects:
```python
def get_chat_history(session_id: str) -> list[ChatMessage]:
    memory = get_or_create_chat_memory(session_id)
    return memory.get_all()
```

### clear_session_memory(session_id)

Clears chat history for session:
```python
def clear_session_memory(session_id: str) -> None:
    if session_id in SESSION_MEMORIES:
        del SESSION_MEMORIES[session_id]
```

## Chat Flow

1. **User loads page** → JavaScript generates/retrieves session_id from `localStorage`
2. **User submits query** → Form includes session_id (hidden field)
3. **Backend receives query + session_id** → Retrieves/creates `ChatMemoryBuffer`
4. **Chat engine uses memory** → Reformulates query → Retrieves context → Generates response
5. **Chat history updated automatically** by LlamaIndex
6. **Frontend fetches full chat history** → Displays all messages
7. **User submits follow-up** → Process repeats with same session_id

## Testing Conversational Context

### Example Multi-Turn Conversation

```bash
Q1: "What does Paul Graham say about startups?"
A1: [Answer about startups]

Q2: "What about work?"  # Ambiguous - needs context
A2: [Answer about work, correctly interpreted]

Q3: "What was my first question?"  # Meta-question
A3: "Your first question was about what Paul Graham says about startups."
```

### Monitoring Logs

```bash
docker compose logs rag-server | grep -E "(CHAT|session|condense)"
```

### Expected Log Output

```
[CHAT_MEMORY] Detected model context window: 131072 tokens
[CHAT_MEMORY] Allocating 65536 tokens for chat history (50% of context window)
[CHAT_MEMORY] Created new memory for session: abc123...
[RAG] Using retrieval_top_k=10, reranker_enabled=True, session_id=abc123...
[condense_plus_context] Condensed question: What are Paul Graham's views on startups?
```

## Configuration Examples

### Changing LLM Model

```yaml
# docker-compose.yml
environment:
  - LLM_MODEL=llama3:8b  # Switch from gemma3:4b
  - EMBEDDING_MODEL=nomic-embed-text
```

### Adjusting Token Allocation

Modify `get_token_limit_for_chat_history()` in `chat_memory.py`:
```python
def get_token_limit_for_chat_history() -> int:
    context_window = Settings.llm.metadata.context_window
    return int(context_window * 0.6)  # Increase to 60%
```

### Session Persistence

For production, replace in-memory storage with Redis:
```python
from llama_index.storage.chat_store.redis import RedisChatStore

chat_store = RedisChatStore(redis_url="redis://localhost:6379")
memory = ChatMemoryBuffer.from_defaults(
    token_limit=token_limit,
    chat_store=chat_store,
    chat_store_key=session_id
)
```

## Best Practices

1. **Session Management**: Always generate unique session IDs client-side
2. **Token Limits**: Monitor chat history size for long conversations
3. **Memory Cleanup**: Implement session expiration for production (e.g., 24 hours)
4. **Error Handling**: Handle missing session_id gracefully (auto-generate)
5. **UI Feedback**: Show loading state during query processing
6. **Scroll Behavior**: Auto-scroll to latest message on new responses
7. **Context Awareness**: Test with ambiguous follow-up questions to verify contextualization
