# Knowledge Base - Quick Start Guide

## Setup Steps

### 1. Install Dependencies

```bash
pip install PyPDF2 python-docx python-pptx
```

Or if using conda:
```bash
conda install -c conda-forge pypdf2 python-docx python-pptx
```

### 2. Run Database Migration

```bash
alembic upgrade head
```

This will create the `knowledge_documents` and `knowledge_document_versions` tables.

### 3. Start the Server

```bash
uvicorn app.app:app --reload
```

## Testing the API

### Upload a Document

**Using curl:**
```bash
curl -X POST "http://localhost:8000/api/knowledge/documents/upload?title=Test%20Document&description=Test%20description&category=training" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/your/document.pdf"
```

**Using Python requests:**
```python
import requests

url = "http://localhost:8000/api/knowledge/documents/upload"
headers = {"Authorization": "Bearer YOUR_TOKEN"}
params = {
    "title": "Test Document",
    "description": "Test description",
    "category": "training",
    "tags": "test,training",
    "access_level": "pilot"
}

with open("test_document.pdf", "rb") as f:
    files = {"file": f}
    response = requests.post(url, headers=headers, params=params, files=files)
    print(response.json())
```

### Search Documents

**Using curl:**
```bash
curl "http://localhost:8000/api/knowledge/documents?query=test&limit=10" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Using Python:**
```python
import requests

url = "http://localhost:8000/api/knowledge/documents"
headers = {"Authorization": "Bearer YOUR_TOKEN"}
params = {
    "query": "test",
    "category": "training",
    "limit": 10
}

response = requests.get(url, headers=headers, params=params)
print(response.json())
```

### Get a Single Document

```bash
curl "http://localhost:8000/api/knowledge/documents/1" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Download a Document

```bash
curl "http://localhost:8000/api/knowledge/documents/1/download" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -o downloaded_file.pdf
```

## API Endpoints

### POST `/api/knowledge/documents/upload`
Upload a new document.

**Query Parameters:**
- `title` (required): Document title
- `description` (optional): Document description
- `category` (optional): Document category
- `tags` (optional): Comma-separated tags
- `access_level` (optional, default: "pilot"): Access level (public, pilot, admin)

**Body:**
- `file`: The document file (PDF, DOC, DOCX, or PPTX)

**Response:**
```json
{
  "id": 1,
  "title": "Test Document",
  "file_url": "/static/knowledge_base/documents/1/v1/1_v1.pdf",
  "message": "Document uploaded successfully"
}
```

### GET `/api/knowledge/documents`
List/search documents.

**Query Parameters:**
- `query` (optional): Search query
- `category` (optional): Filter by category
- `file_type` (optional): Filter by file type (pdf, docx, pptx)
- `limit` (optional, default: 50): Maximum results

**Response:**
```json
[
  {
    "id": 1,
    "title": "Test Document",
    "description": "Test description",
    "file_name": "test.pdf",
    "file_type": "pdf",
    "file_size": 12345,
    "category": "training",
    "tags": "test,training",
    "access_level": "pilot",
    "file_url": "/static/knowledge_base/documents/1/v1/1_v1.pdf",
    "uploaded_by_username": "user1",
    "uploaded_at_utc": "2025-12-15T12:00:00Z",
    "updated_at_utc": "2025-12-15T12:00:00Z",
    "version": 1
  }
]
```

### GET `/api/knowledge/documents/{doc_id}`
Get a single document by ID.

### GET `/api/knowledge/documents/{doc_id}/download`
Download a document file.

## File Storage

Documents are stored in:
```
web/static/knowledge_base/documents/
  {document_id}/
    v{version}/
      {filename}
```

## Search Features

The search currently uses SQL LIKE queries on:
- Document title
- Description
- Extracted text content (from PDF/Word/PowerPoint)
- Tags

Future enhancement: Can upgrade to SQLite FTS5 for better performance and ranking.

## Access Control

- **public**: All authenticated users can access
- **pilot**: Pilots and admins can access
- **admin**: Only admins can access

## Notes

- Maximum file size: 50MB
- Supported formats: PDF, DOC, DOCX, PPTX
- Text extraction happens automatically on upload
- Documents are versioned (currently v1, versioning system ready for future use)

