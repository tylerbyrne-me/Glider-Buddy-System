# Phase 2: LLM Integration & Document Chunking - Complete

## What Was Implemented

### 1. LLM Service (`app/services/llm_service.py`)
- Ollama integration for local LLM inference
- Response synthesis from document context
- Intent classification (troubleshooting, procedure, general)
- Graceful fallback when LLM unavailable

### 2. Document Chunking (`app/services/chunking_service.py`)
- Splits large documents into smaller, searchable chunks
- Semantic chunking (by sections, paragraphs, sentences)
- Chunk overlap for context continuity
- Improved search precision for specific information

### 3. Enhanced Chatbot Response
- LLM synthesizes answers from retrieved documents
- Shows sources used in response
- Displays "AI-Generated Response" indicator
- Falls back to document links if LLM unavailable

### 4. Configuration Options Added
```python
# In app/config.py
llm_enabled: bool = True
llm_host: str = "http://localhost:11434"
llm_model: str = "mistral:7b"
llm_temperature: float = 0.7
llm_max_tokens: int = 500
llm_timeout: int = 60
llm_fallback_to_search: bool = True
```

### 5. Status Endpoint
- `GET /api/chatbot/status` - Check LLM and vector search status

---

## Setup Instructions

### Step 1: Install Ollama

**Windows:**
1. Download from: https://ollama.ai/download
2. Run the installer
3. Ollama will run as a service on port 11434

**Verify installation:**
```bash
ollama --version
```

### Step 2: Pull a Model

```bash
# Recommended model (good balance of speed/quality)
ollama pull mistral:7b

# Alternative: smaller, faster
ollama pull llama2:7b

# Alternative: better quality, slower
ollama pull mixtral:8x7b
```

### Step 3: Install Python Dependency

```bash
conda activate WorkPython
pip install ollama>=0.1.0
```

### Step 4: Re-vectorize Documents with Chunking

This improves search precision by splitting large documents:

```bash
cd "c:\Users\ty225269\Documents\Python Playground\Wave Glider Buddy System"
python scripts/revectorize_with_chunking.py
```

### Step 5: Restart FastAPI Server

```bash
# Stop current server (Ctrl+C)
# Start again
uvicorn app.app:app --reload
```

---

## How It Works

### Query Flow
```
User: "How do I check battery voltage?"
    ↓
1. Vector search finds relevant document chunks
    ↓
2. Context gathered from top matches
    ↓
3. LLM synthesizes answer from context
    ↓
4. Response with sources displayed
```

### Example Response
```
┌─────────────────────────────────────────────────┐
│ 🤖 AI-Generated Response                        │
│                                                 │
│ To check battery voltage on the Wave Glider:    │
│                                                 │
│ 1. Open WGMS and navigate to the Status tab     │
│ 2. Look for "Battery V" under Power section     │
│ 3. Normal range is 12.5-14.2V                   │
│ 4. If below 12V, the glider needs charging      │
│                                                 │
│ ────────────────────────────────────────────────│
│ 📚 Sources: document: WGMS User Guide (Part 3)  │
│                                                 │
│ [👍 Helpful] [👎 Not Helpful]                   │
└─────────────────────────────────────────────────┘

Related Resources:
  📄 WGMS User Guide
  📄 Pilot Tips and Sensor Commands
```

---

## Troubleshooting

### LLM Not Working

1. **Check Ollama is running:**
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. **Check model is installed:**
   ```bash
   ollama list
   ```

3. **Pull the model:**
   ```bash
   ollama pull mistral:7b
   ```

4. **Check status endpoint:**
   ```
   GET /api/chatbot/status
   ```

### Responses Too Slow

1. Use a smaller model:
   ```python
   # In config.py or .env
   llm_model = "llama2:7b"
   ```

2. Reduce max tokens:
   ```python
   llm_max_tokens = 300
   ```

### No Context Found

1. Re-run vectorization:
   ```bash
   python scripts/revectorize_with_chunking.py
   ```

2. Lower similarity threshold:
   ```python
   vector_similarity_threshold = 0.30
   ```

---

## Configuration Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `llm_enabled` | `True` | Enable/disable LLM |
| `llm_host` | `http://localhost:11434` | Ollama server URL |
| `llm_model` | `mistral:7b` | Model to use |
| `llm_temperature` | `0.7` | Creativity (0=factual, 1=creative) |
| `llm_max_tokens` | `500` | Max response length |
| `llm_timeout` | `60` | Request timeout (seconds) |
| `llm_fallback_to_search` | `True` | Show search results if LLM fails |

---

## Disabling LLM

If you want to use vector search without LLM:

```python
# In config.py or .env
llm_enabled = False
```

The chatbot will still work, showing matched documents and tips without synthesis.

---

## Next Steps (Optional)

### Phase 3: SQL Query Generation
- Natural language database queries
- "Show me all missions from last month"
- Admin-only feature

### Phase 4: Learning & Analytics
- Track common unanswered questions
- Auto-generate FAQ suggestions
- Improve matching over time
