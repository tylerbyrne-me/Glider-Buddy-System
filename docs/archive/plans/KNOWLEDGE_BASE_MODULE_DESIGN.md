# Knowledge Base Module Design

## Overview
A comprehensive knowledge management system for training materials, reference documentation, pilot notes, and FAQ/chatbot functionality.

## Features

### 1. Document Management
- Upload and store PDFs, Word documents, and PowerPoint presentations
- Full-text search across document content
- Document categorization and tagging
- Version control for updated documents
- Access control (public, pilot-only, admin-only)

### 2. User Notes & Canvases
- Personal notes/canvases for each pilot
- Rich text editing support
- Organization by categories/tags
- Quick reference capabilities

### 3. Collaborative Tips & Tricks
- Shared knowledge base where pilots can contribute tips
- Community-editable notes (with permission controls)
- Voting/rating system for helpful tips
- Searchable across all shared content

### 4. FAQ/Chatbot System
- Curated FAQ database
- Natural language query processing
- Context-aware responses
- Links to relevant documents and resources
- Learning from user interactions

## Database Schema

### New Tables Required

#### 1. `knowledge_documents` Table
Stores metadata for uploaded training/reference documents.

```python
class KnowledgeDocument(SQLModel, table=True):
    __tablename__ = "knowledge_documents"
    
    id: Optional[int] = SQLModelField(primary_key=True)
    title: str = SQLModelField(index=True)
    description: Optional[str] = None
    file_path: str  # Path to stored file
    file_name: str  # Original filename
    file_type: str  # pdf, docx, pptx
    file_size: int  # Bytes
    category: Optional[str] = SQLModelField(index=True)  # e.g., "training", "reference", "procedures"
    tags: Optional[str] = None  # Comma-separated tags
    access_level: str = SQLModelField(default="pilot")  # "public", "pilot", "admin"
    
    # Full-text search content (extracted text)
    searchable_content: Optional[str] = SQLModelField(sa_column=Column(Text))
    
    # Metadata
    uploaded_by_username: str
    uploaded_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    version: int = SQLModelField(default=1)
    is_active: bool = SQLModelField(default=True, index=True)
    
    # Relationships
    document_versions: List["KnowledgeDocumentVersion"] = Relationship(back_populates="document")
```

#### 2. `knowledge_document_versions` Table
Tracks document version history.

```python
class KnowledgeDocumentVersion(SQLModel, table=True):
    __tablename__ = "knowledge_document_versions"
    
    id: Optional[int] = SQLModelField(primary_key=True)
    document_id: int = SQLModelField(foreign_key="knowledge_documents.id", index=True)
    file_path: str
    version: int
    uploaded_by_username: str
    uploaded_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    change_notes: Optional[str] = None
    
    document: "KnowledgeDocument" = Relationship(back_populates="document_versions")
```

#### 3. `user_notes` Table
Personal notes/canvases for individual pilots.

```python
class UserNote(SQLModel, table=True):
    __tablename__ = "user_notes"
    
    id: Optional[int] = SQLModelField(primary_key=True)
    user_id: int = SQLModelField(foreign_key="users.id", index=True)
    title: str = SQLModelField(index=True)
    content: str = SQLModelField(sa_column=Column(Text))  # Rich text/HTML
    category: Optional[str] = SQLModelField(index=True)  # User-defined categories
    tags: Optional[str] = None
    is_pinned: bool = SQLModelField(default=False, index=True)
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user: "UserInDB" = Relationship()
```

#### 4. `shared_tips` Table
Community-shared tips and tricks.

```python
class SharedTip(SQLModel, table=True):
    __tablename__ = "shared_tips"
    
    id: Optional[int] = SQLModelField(primary_key=True)
    title: str = SQLModelField(index=True)
    content: str = SQLModelField(sa_column=Column(Text))
    category: Optional[str] = SQLModelField(index=True)  # e.g., "troubleshooting", "best_practices"
    tags: Optional[str] = None
    
    # Collaboration
    created_by_username: str
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    last_edited_by_username: Optional[str] = None
    
    # Engagement metrics
    helpful_count: int = SQLModelField(default=0)
    view_count: int = SQLModelField(default=0)
    is_featured: bool = SQLModelField(default=False, index=True)
    is_archived: bool = SQLModelField(default=False, index=True)
    
    # Relationships
    tip_contributions: List["TipContribution"] = Relationship(back_populates="tip")
```

#### 5. `tip_contributions` Table
Tracks edits/contributions to shared tips.

```python
class TipContribution(SQLModel, table=True):
    __tablename__ = "tip_contributions"
    
    id: Optional[int] = SQLModelField(primary_key=True)
    tip_id: int = SQLModelField(foreign_key="shared_tips.id", index=True)
    contributed_by_username: str
    contribution_type: str  # "edit", "comment", "rating"
    content: Optional[str] = None  # For comments
    contributed_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    
    tip: "SharedTip" = Relationship(back_populates="tip_contributions")
```

#### 6. `faq_entries` Table
FAQ database for chatbot/knowledge base.

```python
class FAQEntry(SQLModel, table=True):
    __tablename__ = "faq_entries"
    
    id: Optional[int] = SQLModelField(primary_key=True)
    question: str = SQLModelField(index=True)
    answer: str = SQLModelField(sa_column=Column(Text))
    category: Optional[str] = SQLModelField(index=True)
    tags: Optional[str] = None
    
    # Search optimization
    keywords: Optional[str] = None  # Comma-separated keywords for matching
    searchable_content: str = SQLModelField(sa_column=Column(Text))  # question + answer + keywords
    
    # Related resources
    related_document_ids: Optional[str] = None  # Comma-separated document IDs
    related_tip_ids: Optional[str] = None  # Comma-separated tip IDs
    
    # Usage tracking
    view_count: int = SQLModelField(default=0)
    helpful_count: int = SQLModelField(default=0)
    not_helpful_count: int = SQLModelField(default=0)
    
    # Metadata
    created_by_username: str
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = SQLModelField(default=True, index=True)
```

#### 7. `chatbot_interactions` Table (Optional)
Tracks chatbot queries for learning and improvement.

```python
class ChatbotInteraction(SQLModel, table=True):
    __tablename__ = "chatbot_interactions"
    
    id: Optional[int] = SQLModelField(primary_key=True)
    user_id: Optional[int] = SQLModelField(foreign_key="users.id", index=True)
    query: str = SQLModelField(sa_column=Column(Text))
    response_type: str  # "faq_match", "document_match", "no_match"
    matched_faq_id: Optional[int] = SQLModelField(foreign_key="faq_entries.id")
    matched_document_ids: Optional[str] = None  # Comma-separated
    was_helpful: Optional[bool] = None  # User feedback
    interaction_timestamp: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
```

## File Storage Structure

```
web/static/
  knowledge_base/
    documents/
      {document_id}/
        v{version}/
          {filename}
    thumbnails/  # Optional: for PowerPoint previews
      {document_id}_v{version}.png
```

## Module Structure

### Router: `app/routers/knowledge_base.py`
- Document upload/download endpoints
- Search endpoints
- User notes CRUD
- Shared tips CRUD
- FAQ endpoints
- Chatbot query endpoint

### Service: `app/services/knowledge_base_service.py`
- Document processing (text extraction)
- Search logic
- Chatbot query processing
- Content indexing

### Models: `app/core/models/database.py` & `schemas.py`
- Database models (as defined above)
- Pydantic schemas for requests/responses

## Search Implementation Options

### Option 1: SQLite FTS (Full-Text Search)
- Built into SQLite
- No external dependencies
- Good for small to medium document sets
- Implementation: Create FTS virtual tables

### Option 2: Python-based Search (Whoosh, Meilisearch)
- More advanced features
- Better ranking algorithms
- Requires additional dependencies
- Better for larger document sets

### Option 3: Hybrid Approach
- Store extracted text in database
- Use SQL LIKE/ILIKE for basic search
- Add FTS for advanced queries
- Simple to implement, works well for moderate needs

**Recommendation**: Start with Option 3 (hybrid), can upgrade to Option 1 or 2 later if needed.

## Text Extraction Libraries

For extracting searchable text from documents:
- **PDF**: `PyPDF2` or `pdfplumber`
- **Word**: `python-docx` for .docx
- **PowerPoint**: `python-pptx` for .pptx

## Integration Points

### Existing System Integration
1. **User System**: Leverage existing `UserInDB` model
2. **Authentication**: Use existing `get_current_active_user` dependency
3. **File Storage**: Follow pattern from `mission_plans` upload
4. **Search Pattern**: Similar to `station_metadata` search endpoint

### Avoid Duplication
- **MissionNote**: Mission-specific notes, keep separate
- **Announcements**: System-wide announcements, different purpose
- **Forms**: Structured data entry, different use case

## API Endpoints (Proposed)

### Documents
- `POST /api/knowledge/documents/upload` - Upload document
- `GET /api/knowledge/documents` - List documents (with search/filter)
- `GET /api/knowledge/documents/{id}` - Get document metadata
- `GET /api/knowledge/documents/{id}/download` - Download file
- `GET /api/knowledge/documents/{id}/versions` - Get version history
- `PUT /api/knowledge/documents/{id}` - Update metadata
- `DELETE /api/knowledge/documents/{id}` - Archive document

### User Notes
- `GET /api/knowledge/user-notes` - Get user's notes
- `POST /api/knowledge/user-notes` - Create note
- `PUT /api/knowledge/user-notes/{id}` - Update note
- `DELETE /api/knowledge/user-notes/{id}` - Delete note

### Shared Tips
- `GET /api/knowledge/shared-tips` - List shared tips (with search)
- `POST /api/knowledge/shared-tips` - Create tip
- `PUT /api/knowledge/shared-tips/{id}` - Update tip
- `POST /api/knowledge/shared-tips/{id}/helpful` - Mark as helpful
- `DELETE /api/knowledge/shared-tips/{id}` - Archive tip

### FAQ/Chatbot
- `GET /api/knowledge/faq` - List FAQ entries
- `POST /api/knowledge/faq` - Create FAQ (admin)
- `POST /api/knowledge/chatbot/query` - Chatbot query endpoint
- `POST /api/knowledge/chatbot/feedback` - Provide feedback on response

### Search
- `GET /api/knowledge/search?q={query}&type={documents|tips|faq|all}` - Unified search

## Frontend Considerations

### New Pages Needed
1. **Knowledge Base Home** (`/knowledge_base.html`)
   - Search bar
   - Document categories
   - Recent documents
   - Featured tips

2. **Document Viewer** (`/knowledge_base/document/{id}.html`)
   - Document preview/download
   - Metadata
   - Related resources

3. **My Notes** (`/knowledge_base/my-notes.html`)
   - Personal notes list
   - Create/edit interface

4. **Shared Tips** (`/knowledge_base/tips.html`)
   - Browse tips
   - Create/edit tips
   - Voting/rating

5. **Chatbot Interface** (`/knowledge_base/chatbot.html` or embedded widget)
   - Chat interface
   - Query input
   - Response display
   - Feedback buttons

## Implementation Phases

### Phase 1: Core Document Management
- Database models
- Document upload/download
- Basic search
- Admin interface for document management

### Phase 2: User Notes
- Personal notes system
- Rich text editor integration
- Categories and tags

### Phase 3: Shared Tips
- Collaborative tips system
- Voting/rating
- Community features

### Phase 4: FAQ/Chatbot
- FAQ management
- Basic chatbot (keyword matching)
- Query processing

### Phase 5: Advanced Features
- Improved search (FTS or external)
- Machine learning for better chatbot responses
- Analytics and usage tracking

## Migration Strategy

1. Create Alembic migration for new tables
2. Add router to `app/app.py`
3. Create service layer
4. Build frontend components incrementally
5. Test with sample documents
6. Deploy and gather user feedback

## Security Considerations

- File upload validation (size limits, type checking)
- Path traversal prevention
- Access control enforcement
- Content sanitization for user-generated content
- Rate limiting on search/chatbot endpoints

## Performance Considerations

- Index database columns used in searches
- Cache frequently accessed documents
- Lazy load document content
- Pagination for search results
- Background job for text extraction on upload

