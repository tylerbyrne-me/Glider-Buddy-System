# LLM Chatbot Integration Plan

## Overview
Enhance the existing keyword-based chatbot with local LLM capabilities using Ollama, vector search, and intelligent query processing.

## Current State
- ✅ Basic keyword-based FAQ matching
- ✅ FAQ database with questions/answers
- ✅ Related resources (documents, tips)
- ✅ Feedback collection
- ✅ Chatbot UI

## Target State
- ✅ All current features
- ✅ Vector-based semantic search (ChromaDB)
- ✅ Local LLM for intelligent responses (Ollama)
- ✅ SQL query generation from natural language
- ✅ Enhanced documentation search
- ✅ Fallback to keyword matching if LLM unavailable
- ✅ Configurable LLM usage (on/off)

## Architecture

### Hybrid Approach (Recommended)
```
User Query
    ↓
1. Intent Detection → Identify query type (troubleshooting, procedure, general)
    ↓
2. Targeted Vector Search:
   - Troubleshooting queries → Search docs/tips with category="troubleshooting"
   - Procedure queries → Search docs with category="procedures"
   - General queries → Search all sources
    ↓
3. Check Vector FAQ Search (ChromaDB) → Fast, semantic matching
    ↓ (if no good match)
4. Check Keyword Matching (Current) → Fallback
    ↓ (if no match)
5. Check Documentation Vector Search → Find relevant docs (with category/tag filtering)
    ↓ (if docs found)
6. Check Tips Vector Search → Find relevant tips (with category/tag filtering)
    ↓ (if sources found)
7. Use LLM to synthesize answer from multiple sources
    ↓ (if no sources)
8. Use LLM for general response
    ↓ (if LLM unavailable)
9. Return "I don't know" with links to search
```

### Key Feature: Category/Tag Filtering
- **Troubleshooting queries** automatically filter to:
  - Documents with `category="troubleshooting"` or `tags` containing "troubleshooting"
  - Tips with `category="troubleshooting"` or relevant tags
- **Semantic search** finds relevant content even if exact words don't match
- **Multi-source synthesis** combines official docs + community tips

## Implementation Plan

### Phase 1: Vector Search Integration (Week 1)
**Goal**: Add semantic search without LLM dependency

1. **Add Dependencies**
   - `chromadb` - Vector database
   - `sentence-transformers` - Embeddings

2. **Enhance ChatbotService**
   - Add vector search method
   - Keep keyword matching as fallback
   - Initialize ChromaDB collection on startup

3. **FAQ Vectorization**
   - Create migration/script to populate ChromaDB from existing FAQs
   - Auto-vectorize new FAQs on creation
   - Update FAQs in vector store when modified
   - Store category and tags in metadata for filtering

4. **Documentation Vectorization**
   - Extract text from knowledge base documents (already have `searchable_content`)
   - Store embeddings in ChromaDB with metadata:
     - `category` (e.g., "troubleshooting", "procedures")
     - `tags` (comma-separated)
     - `doc_id`, `title`, `file_type`
   - Link back to original documents
   - **Key**: Documents tagged "troubleshooting" will be prioritized for troubleshooting queries

5. **Tips Vectorization**
   - Extract content from shared tips
   - Store embeddings in ChromaDB with metadata:
     - `category` (e.g., "troubleshooting", "best-practices")
     - `tags` (comma-separated)
     - `tip_id`, `title`
   - **Key**: Tips with troubleshooting category will be found for troubleshooting queries

**Benefits**: Better semantic matching, no LLM required yet

---

### Phase 2: LLM Integration (Week 2)
**Goal**: Add intelligent responses using local LLM

1. **Add Ollama Dependency**
   - `ollama` Python package
   - Configuration for model selection
   - Health check endpoint

2. **LLM Service Layer**
   - Create `LLMService` class
   - Handle Ollama connection
   - Error handling and fallbacks

3. **Enhanced Query Processing**
   - Intent classification (FAQ, SQL, Documentation, General)
   - Context building from matched resources
   - LLM prompt engineering
   - Response synthesis

4. **Configuration**
   - Add to `app/config.py`:
     - `LLM_ENABLED` (bool)
     - `LLM_MODEL` (str, e.g., "mistral:7b")
     - `LLM_FALLBACK_TO_KEYWORDS` (bool)

**Benefits**: Intelligent responses, handles complex queries

---

### Phase 3: SQL Query Generation (Week 3)
**Goal**: Allow natural language database queries

1. **Database Schema Introspection**
   - Function to get schema info
   - Format for LLM context

2. **SQL Generation Service**
   - LLM prompt for SQL generation
   - Query validation
   - Safe execution (read-only, limits)

3. **Query Execution**
   - Execute generated SQL
   - Format results
   - LLM explanation of results

4. **Security**
   - Read-only queries only
   - Row limits
   - Query logging
   - Admin-only or restricted access

**Benefits**: Natural language database queries

---

### Phase 4: Learning & Analytics (Week 4)
**Goal**: Improve over time

1. **Enhanced Analytics**
   - Track query patterns
   - Identify gaps in FAQ coverage
   - Monitor LLM vs keyword performance

2. **Auto-FAQ Generation**
   - Identify common unanswered questions
   - Generate FAQ candidates using LLM
   - Admin review workflow

3. **Feedback Loop**
   - Use feedback to improve matching
   - Retrain embeddings periodically
   - Update prompts based on failures

**Benefits**: Self-improving system

---

## Technical Details

### Dependencies to Add
```python
# requirements.txt additions
chromadb>=0.4.0          # Vector database
sentence-transformers>=2.2.0  # Embeddings
ollama>=0.1.0            # LLM client
```

### Configuration Options
```python
# app/config.py
class Settings(BaseSettings):
    # LLM Configuration
    llm_enabled: bool = False  # Master switch
    llm_model: str = "mistral:7b"  # Ollama model name
    llm_fallback_to_keywords: bool = True  # Use keyword if LLM fails
    llm_temperature: float = 0.7  # Response creativity
    llm_max_tokens: int = 500  # Response length limit
    
    # Vector Search Configuration
    vector_search_enabled: bool = True
    vector_similarity_threshold: float = 0.35  # Match threshold
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    
    # SQL Query Configuration
    sql_query_enabled: bool = False  # Admin-only feature
    sql_query_max_rows: int = 100  # Safety limit
```

### Service Architecture
```
ChatbotService (enhanced)
    ├── VectorSearchService (new)
    │   ├── ChromaDB client
    │   ├── Embedding generation
    │   └── Similarity search
    ├── LLMService (new)
    │   ├── Ollama client
    │   ├── Prompt building
    │   └── Response generation
    ├── SQLQueryService (new, optional)
    │   ├── Schema introspection
    │   ├── SQL generation
    │   └── Safe execution
    └── KeywordMatchingService (existing, fallback)
```

### Database Changes
- No schema changes needed
- Add ChromaDB storage directory: `data_store/chroma_db/`
- Optional: Add `llm_metadata` JSON field to `chatbot_interactions` for analytics

### Migration Path
1. **Phase 1**: Add vector search alongside keywords (no breaking changes)
2. **Phase 2**: Add LLM as optional enhancement (can disable)
3. **Phase 3**: Add SQL queries (admin-only, opt-in)
4. **Phase 4**: Add learning features (background tasks)

---

## Implementation Steps

### Step 1: Vector Search (No LLM Required)
1. Install ChromaDB and sentence-transformers
2. Create `VectorSearchService` class
3. Enhance `ChatbotService` to use vector search first
4. Create script to vectorize existing FAQs
5. Update FAQ creation/update to auto-vectorize
6. Test semantic matching

### Step 2: LLM Integration
1. Install Ollama and Python client
2. Create `LLMService` class
3. Add configuration options
4. Enhance query processing with LLM
5. Add health check for Ollama
6. Test with various queries

### Step 3: Documentation & Tips Integration
1. Vectorize knowledge base documents (use existing `searchable_content`)
2. Vectorize shared tips (use `content` field)
3. Add category/tag filtering for targeted searches:
   - Troubleshooting queries → filter to troubleshooting docs/tips
   - Procedure queries → filter to procedure docs
   - General queries → search all sources
4. Add documentation and tips search to query flow
5. Use LLM to synthesize answers from multiple sources (docs + tips + FAQs)
6. Test with troubleshooting scenarios

### Step 4: SQL Query (Optional)
1. Create SQL query service
2. Add admin-only endpoint
3. Implement safety checks
4. Test with sample queries

---

## Testing Strategy

### Unit Tests
- Vector search matching
- LLM service error handling
- Keyword fallback
- SQL query validation

### Integration Tests
- End-to-end query flow
- LLM unavailable scenarios
- Vector search + LLM combination
- Documentation search

### Performance Tests
- Response time benchmarks
- Vector search speed
- LLM response time
- Concurrent query handling

---

## Rollout Plan

### Phase 1 Rollout (Vector Search)
- ✅ No breaking changes
- ✅ Works with existing FAQs
- ✅ Can be enabled/disabled
- ✅ Immediate improvement in matching

### Phase 2 Rollout (LLM)
- ⚠️ Requires Ollama installation
- ⚠️ Optional feature (can disable)
- ⚠️ Fallback to keywords if LLM fails
- ✅ Gradual rollout possible

### Phase 3 Rollout (SQL)
- ⚠️ Admin-only initially
- ⚠️ Requires careful testing
- ⚠️ Security review needed
- ✅ Can be disabled

---

## Risk Mitigation

### LLM Unavailable
- Fallback to keyword matching
- Graceful degradation
- Health check monitoring

### Performance Issues
- Cache frequent queries
- Async LLM calls
- Timeout handling
- Rate limiting

### Security Concerns (SQL)
- Read-only queries only
- Row limits enforced
- Query logging
- Admin-only access

### Data Privacy
- All processing local (Ollama)
- No external API calls
- Data stays on-premises

---

## Success Metrics

1. **Matching Accuracy**: % of queries with good matches
2. **Response Quality**: User feedback scores
3. **Response Time**: Average query processing time
4. **LLM Usage**: % of queries using LLM vs keywords
5. **User Satisfaction**: Feedback helpful rate

---

## Next Steps

1. **Review this plan** - Does it meet requirements?
2. **Start with Phase 1** - Vector search (low risk, high value)
3. **Test thoroughly** - Before adding LLM complexity
4. **Iterate** - Based on user feedback
