# Knowledge Base Module - Implementation Example

This document shows code examples following your existing patterns and standards.

## Database Models (app/core/models/database.py)

```python
# Add to existing database.py

# --- Knowledge Base Database Models ---
class KnowledgeDocument(SQLModel, table=True):
    """Knowledge base document database table."""
    __tablename__ = "knowledge_documents"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    title: str = SQLModelField(index=True, description="Document title")
    description: Optional[str] = SQLModelField(default=None, description="Document description")
    file_path: str = SQLModelField(description="Path to stored file")
    file_name: str = SQLModelField(description="Original filename")
    file_type: str = SQLModelField(index=True, description="File type: pdf, docx, pptx")
    file_size: int = SQLModelField(description="File size in bytes")
    category: Optional[str] = SQLModelField(default=None, index=True, description="Document category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    access_level: str = SQLModelField(default="pilot", index=True, description="Access level: public, pilot, admin")
    
    # Full-text search content (extracted text)
    searchable_content: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="Extracted text for searching")
    
    # Metadata
    uploaded_by_username: str = SQLModelField(index=True, description="Username who uploaded")
    uploaded_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Upload timestamp"
    )
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="Last update timestamp"
    )
    version: int = SQLModelField(default=1, description="Current version number")
    is_active: bool = SQLModelField(default=True, index=True, description="Whether document is active")
    
    # Relationships
    document_versions: List["KnowledgeDocumentVersion"] = Relationship(back_populates="document")


class KnowledgeDocumentVersion(SQLModel, table=True):
    """Document version history."""
    __tablename__ = "knowledge_document_versions"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    document_id: int = SQLModelField(foreign_key="knowledge_documents.id", index=True)
    file_path: str = SQLModelField(description="Path to version file")
    version: int = SQLModelField(description="Version number")
    uploaded_by_username: str = SQLModelField(description="Username who uploaded this version")
    uploaded_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    change_notes: Optional[str] = SQLModelField(default=None, description="Notes about changes")
    
    document: "KnowledgeDocument" = Relationship(back_populates="document_versions")


class UserNote(SQLModel, table=True):
    """User personal notes database table."""
    __tablename__ = "user_notes"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    user_id: int = SQLModelField(foreign_key="users.id", index=True, description="User who owns this note")
    title: str = SQLModelField(index=True, description="Note title")
    content: str = SQLModelField(sa_column=Column(Text), description="Note content (rich text)")
    category: Optional[str] = SQLModelField(default=None, index=True, description="User-defined category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    is_pinned: bool = SQLModelField(default=False, index=True, description="Whether note is pinned")
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    
    # Relationships
    user: "UserInDB" = Relationship()


class SharedTip(SQLModel, table=True):
    """Shared tips and tricks database table."""
    __tablename__ = "shared_tips"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    title: str = SQLModelField(index=True, description="Tip title")
    content: str = SQLModelField(sa_column=Column(Text), description="Tip content")
    category: Optional[str] = SQLModelField(default=None, index=True, description="Tip category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    
    # Collaboration
    created_by_username: str = SQLModelField(index=True, description="Username who created")
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    last_edited_by_username: Optional[str] = SQLModelField(default=None, description="Username who last edited")
    
    # Engagement metrics
    helpful_count: int = SQLModelField(default=0, description="Number of helpful votes")
    view_count: int = SQLModelField(default=0, description="Number of views")
    is_featured: bool = SQLModelField(default=False, index=True, description="Whether tip is featured")
    is_archived: bool = SQLModelField(default=False, index=True, description="Whether tip is archived")
    
    # Relationships
    tip_contributions: List["TipContribution"] = Relationship(back_populates="tip")


class TipContribution(SQLModel, table=True):
    """Tip contribution/edit history."""
    __tablename__ = "tip_contributions"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    tip_id: int = SQLModelField(foreign_key="shared_tips.id", index=True)
    contributed_by_username: str = SQLModelField(description="Username who contributed")
    contribution_type: str = SQLModelField(description="Type: edit, comment, rating")
    content: Optional[str] = SQLModelField(default=None, sa_column=Column(Text), description="Contribution content")
    contributed_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    
    tip: "SharedTip" = Relationship(back_populates="tip_contributions")


class FAQEntry(SQLModel, table=True):
    """FAQ entry database table."""
    __tablename__ = "faq_entries"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    question: str = SQLModelField(index=True, description="FAQ question")
    answer: str = SQLModelField(sa_column=Column(Text), description="FAQ answer")
    category: Optional[str] = SQLModelField(default=None, index=True, description="FAQ category")
    tags: Optional[str] = SQLModelField(default=None, description="Comma-separated tags")
    
    # Search optimization
    keywords: Optional[str] = SQLModelField(default=None, description="Comma-separated keywords")
    searchable_content: str = SQLModelField(sa_column=Column(Text), description="Combined searchable content")
    
    # Related resources
    related_document_ids: Optional[str] = SQLModelField(default=None, description="Comma-separated document IDs")
    related_tip_ids: Optional[str] = SQLModelField(default=None, description="Comma-separated tip IDs")
    
    # Usage tracking
    view_count: int = SQLModelField(default=0, description="Number of views")
    helpful_count: int = SQLModelField(default=0, description="Helpful votes")
    not_helpful_count: int = SQLModelField(default=0, description="Not helpful votes")
    
    # Metadata
    created_by_username: str = SQLModelField(description="Username who created")
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    is_active: bool = SQLModelField(default=True, index=True, description="Whether FAQ is active")
```

## Service Layer (app/services/knowledge_base_service.py)

Following your SERVICE_STANDARDS.md - this handles complex business logic:

```python
"""
Knowledge Base Service

Handles document processing, text extraction, search logic, and chatbot processing.
"""

import logging
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timezone

from sqlmodel import select, or_, and_
from sqlalchemy import func

from ..core.models import database as models
from ..core.db import SQLModelSession

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Service for knowledge base operations."""
    
    def __init__(self):
        """Initialize the knowledge base service."""
        pass
    
    async def extract_text_from_document(
        self,
        file_path: Path,
        file_type: str
    ) -> str:
        """
        Extract searchable text from a document.
        
        Args:
            file_path: Path to the document file
            file_type: Type of file (pdf, docx, pptx)
            
        Returns:
            Extracted text content
        """
        try:
            if file_type == "pdf":
                return await self._extract_pdf_text(file_path)
            elif file_type == "docx":
                return await self._extract_docx_text(file_path)
            elif file_type == "pptx":
                return await self._extract_pptx_text(file_path)
            else:
                logger.warning(f"Unsupported file type for text extraction: {file_type}")
                return ""
        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
            return ""
    
    async def _extract_pdf_text(self, file_path: Path) -> str:
        """Extract text from PDF."""
        try:
            import PyPDF2
            text = ""
            with open(file_path, "rb") as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return ""
    
    async def _extract_docx_text(self, file_path: Path) -> str:
        """Extract text from Word document."""
        try:
            from docx import Document
            doc = Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text
        except Exception as e:
            logger.error(f"Error extracting DOCX text: {e}")
            return ""
    
    async def _extract_pptx_text(self, file_path: Path) -> str:
        """Extract text from PowerPoint."""
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            text = ""
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
            return text
        except Exception as e:
            logger.error(f"Error extracting PPTX text: {e}")
            return ""
    
    async def search_documents(
        self,
        session: SQLModelSession,
        query: Optional[str] = None,
        category: Optional[str] = None,
        file_type: Optional[str] = None,
        access_level: Optional[str] = None,
        limit: int = 50
    ) -> List[models.KnowledgeDocument]:
        """
        Search knowledge base documents.
        
        Args:
            session: Database session
            query: Search query string
            category: Filter by category
            file_type: Filter by file type
            access_level: Filter by access level
            limit: Maximum results
            
        Returns:
            List of matching documents
        """
        statement = select(models.KnowledgeDocument).where(
            models.KnowledgeDocument.is_active == True
        )
        
        # Apply filters
        if category:
            statement = statement.where(models.KnowledgeDocument.category == category)
        if file_type:
            statement = statement.where(models.KnowledgeDocument.file_type == file_type)
        if access_level:
            statement = statement.where(models.KnowledgeDocument.access_level == access_level)
        
        # Apply search query
        if query:
            # Search in title, description, and searchable_content
            search_filter = or_(
                models.KnowledgeDocument.title.ilike(f"%{query}%"),
                models.KnowledgeDocument.description.ilike(f"%{query}%"),
                models.KnowledgeDocument.searchable_content.ilike(f"%{query}%"),
                models.KnowledgeDocument.tags.ilike(f"%{query}%")
            )
            statement = statement.where(search_filter)
        
        statement = statement.order_by(
            models.KnowledgeDocument.uploaded_at_utc.desc()
        ).limit(limit)
        
        results = session.exec(statement).all()
        return results
    
    async def process_chatbot_query(
        self,
        session: SQLModelSession,
        query: str,
        limit: int = 5
    ) -> Dict:
        """
        Process a chatbot query and return relevant results.
        
        Args:
            session: Database session
            query: User's query string
            limit: Maximum results to return
            
        Returns:
            Dictionary with matched FAQs, documents, and tips
        """
        query_lower = query.lower()
        
        # Search FAQs
        faq_statement = select(models.FAQEntry).where(
            and_(
                models.FAQEntry.is_active == True,
                or_(
                    models.FAQEntry.question.ilike(f"%{query}%"),
                    models.FAQEntry.answer.ilike(f"%{query}%"),
                    models.FAQEntry.searchable_content.ilike(f"%{query}%"),
                    models.FAQEntry.keywords.ilike(f"%{query}%")
                )
            )
        ).limit(limit)
        
        faqs = session.exec(faq_statement).all()
        
        # Search documents
        documents = await self.search_documents(session, query=query, limit=limit)
        
        # Search tips
        tip_statement = select(models.SharedTip).where(
            and_(
                models.SharedTip.is_archived == False,
                or_(
                    models.SharedTip.title.ilike(f"%{query}%"),
                    models.SharedTip.content.ilike(f"%{query}%"),
                    models.SharedTip.tags.ilike(f"%{query}%")
                )
            )
        ).limit(limit)
        
        tips = session.exec(tip_statement).all()
        
        return {
            "faqs": faqs,
            "documents": documents,
            "tips": tips,
            "query": query
        }
```

## Router (app/routers/knowledge_base.py)

Following your CODE_STANDARDS.md - routers handle HTTP endpoints:

```python
"""
Knowledge Base Router

Handles HTTP endpoints for knowledge base functionality.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import FileResponse
from typing import List, Optional
from pathlib import Path
from datetime import datetime, timezone

from sqlmodel import select
from ..core import models
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user, get_current_admin_user
from ..services.knowledge_base_service import KnowledgeBaseService
import logging
import shutil

router = APIRouter(tags=["Knowledge Base"])
logger = logging.getLogger(__name__)

# Initialize service
kb_service = KnowledgeBaseService()

# File storage directory
KB_DOCUMENTS_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "static" / "knowledge_base" / "documents"
KB_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/api/knowledge/documents/upload", response_model=dict)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Query(..., description="Document title"),
    description: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    access_level: str = Query("pilot", description="Access level: public, pilot, admin"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Upload a knowledge base document.
    Requires active user authentication.
    """
    logger.info(f"User '{current_user.username}' uploading document: {file.filename}")
    
    # Validate file type
    allowed_types = {
        "application/pdf": "pdf",
        "application/msword": "doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    }
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: PDF, DOC, DOCX, PPTX"
        )
    
    file_type = allowed_types[file.content_type]
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Create document directory structure
    # Get next document ID
    max_id_stmt = select(func.max(models.KnowledgeDocument.id))
    max_id = session.exec(max_id_stmt).first() or 0
    doc_id = max_id + 1
    
    doc_dir = KB_DOCUMENTS_DIR / str(doc_id) / "v1"
    doc_dir.mkdir(parents=True, exist_ok=True)
    
    # Save file
    file_extension = Path(file.filename).suffix
    safe_filename = f"{doc_id}_v1{file_extension}"
    file_path = doc_dir / safe_filename
    
    with file_path.open("wb") as f:
        f.write(content)
    
    # Extract text for search
    searchable_content = await kb_service.extract_text_from_document(file_path, file_type)
    
    # Create database record
    document = models.KnowledgeDocument(
        title=title,
        description=description,
        file_path=str(file_path.relative_to(KB_DOCUMENTS_DIR.parent.parent.parent)),
        file_name=file.filename,
        file_type=file_type,
        file_size=file_size,
        category=category,
        tags=tags,
        access_level=access_level,
        searchable_content=searchable_content,
        uploaded_by_username=current_user.username,
    )
    
    session.add(document)
    session.commit()
    session.refresh(document)
    
    logger.info(f"Document '{title}' uploaded successfully with ID {document.id}")
    
    return {
        "id": document.id,
        "title": document.title,
        "file_url": f"/static/knowledge_base/documents/{doc_id}/v1/{safe_filename}"
    }


@router.get("/api/knowledge/documents", response_model=List[dict])
async def list_documents(
    query: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None),
    file_type: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """List/search knowledge base documents."""
    # Determine access level filter based on user role
    access_level = None
    if current_user.role == models.UserRoleEnum.pilot:
        access_level = "pilot"  # Pilots see pilot and public
    # Admins see everything (no filter)
    
    documents = await kb_service.search_documents(
        session=session,
        query=query,
        category=category,
        file_type=file_type,
        access_level=access_level,
        limit=limit
    )
    
    return [
        {
            "id": doc.id,
            "title": doc.title,
            "description": doc.description,
            "file_type": doc.file_type,
            "category": doc.category,
            "tags": doc.tags.split(",") if doc.tags else [],
            "uploaded_by": doc.uploaded_by_username,
            "uploaded_at": doc.uploaded_at_utc.isoformat(),
            "file_url": f"/static/knowledge_base/documents/{doc.id}/v{doc.version}/{Path(doc.file_name).name}"
        }
        for doc in documents
    ]


@router.get("/api/knowledge/documents/{doc_id}/download")
async def download_document(
    doc_id: int,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Download a knowledge base document."""
    document = session.get(models.KnowledgeDocument, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check access
    if document.access_level == "admin" and current_user.role != models.UserRoleEnum.admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    file_path = Path(__file__).resolve().parent.parent.parent / document.file_path.lstrip("/")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        filename=document.file_name,
        media_type="application/octet-stream"
    )


@router.post("/api/knowledge/chatbot/query", response_model=dict)
async def chatbot_query(
    query: str = Query(..., description="User query"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """Process a chatbot query and return relevant results."""
    results = await kb_service.process_chatbot_query(session, query)
    
    # Format response
    response = {
        "query": query,
        "faqs": [
            {
                "id": faq.id,
                "question": faq.question,
                "answer": faq.answer,
                "category": faq.category
            }
            for faq in results["faqs"]
        ],
        "documents": [
            {
                "id": doc.id,
                "title": doc.title,
                "description": doc.description
            }
            for doc in results["documents"]
        ],
        "tips": [
            {
                "id": tip.id,
                "title": tip.title,
                "content": tip.content[:200] + "..." if len(tip.content) > 200 else tip.content
            }
            for tip in results["tips"]
        ]
    }
    
    return response


# Additional endpoints for user notes, shared tips, FAQ management...
# (Following same patterns as above)
```

## Integration in app.py

```python
# Add to app/app.py router includes

from app.routers import knowledge_base

app.include_router(knowledge_base.router)
```

## Alembic Migration Example

```python
"""Add knowledge base tables

Revision ID: add_knowledge_base_tables
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers
revision = 'add_knowledge_base_tables'
down_revision = 'previous_revision'  # Update with actual previous revision
branch_labels = None
depends_on = None

def upgrade():
    # Create knowledge_documents table
    op.create_table(
        'knowledge_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('file_name', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('access_level', sa.String(), nullable=False),
        sa.Column('searchable_content', sa.Text(), nullable=True),
        sa.Column('uploaded_by_username', sa.String(), nullable=False),
        sa.Column('uploaded_at_utc', sa.DateTime(), nullable=False),
        sa.Column('updated_at_utc', sa.DateTime(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_documents_title'), 'knowledge_documents', ['title'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_file_type'), 'knowledge_documents', ['file_type'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_category'), 'knowledge_documents', ['category'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_access_level'), 'knowledge_documents', ['access_level'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_uploaded_by_username'), 'knowledge_documents', ['uploaded_by_username'], unique=False)
    op.create_index(op.f('ix_knowledge_documents_is_active'), 'knowledge_documents', ['is_active'], unique=False)
    
    # Create other tables...
    # (Similar pattern for user_notes, shared_tips, faq_entries, etc.)

def downgrade():
    op.drop_table('knowledge_documents')
    # Drop other tables...
```

This implementation follows your existing patterns and standards!

