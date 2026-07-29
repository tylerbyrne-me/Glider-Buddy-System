# SQLite Database Analysis for Knowledge Base

## Current Setup

Your system uses:
- **Database**: SQLite (`sqlite:///./data_store/app_data.sqlite`)
- **File Storage Pattern**: Files stored on filesystem, metadata in database
  - Example: Mission plans stored in `web/static/mission_plans/`
  - Database stores file path/URL, not file content

## Answer: Yes, SQLite is Up to the Task (with the right approach)

### ✅ What SQLite CAN Handle

1. **Metadata Storage** - Excellent
   - Document metadata (title, description, tags, etc.)
   - File paths and references
   - User notes and shared tips
   - FAQ entries
   - All your existing data patterns

2. **Extracted Text Storage** - Excellent
   - Store extracted text from PDFs, Word, PowerPoint
   - SQLite TEXT columns can handle large text (up to ~1GB per column)
   - Perfect for searchable content

3. **Full-Text Search** - Excellent (with FTS5)
   - SQLite FTS5 extension provides powerful full-text search
   - Fast, efficient, built-in
   - Supports ranking, phrase matching, boolean operators
   - No external dependencies needed

4. **Database Size** - More than adequate
   - SQLite databases can be up to **281 TB** (theoretical)
   - Practical limit: **~100-200 GB** before performance degrades
   - For your use case (hundreds/thousands of documents): **Plenty of headroom**

### ❌ What SQLite Should NOT Handle

1. **Storing Binary Files (BLOBs)**
   - **Don't store PDF/Word/PowerPoint files as BLOBs in database**
   - Files should stay on filesystem (your current pattern is correct)
   - Reasons:
     - Database bloat (makes DB huge, slow backups)
     - Poor performance (reading large BLOBs is slow)
     - Harder to manage (can't easily access files outside app)
     - Backup complexity (DB backups become massive)

## Recommended Architecture

### ✅ CORRECT Approach (What You Should Do)

```
┌─────────────────────────────────────────┐
│         SQLite Database                 │
│  ┌───────────────────────────────────┐   │
│  │ knowledge_documents table        │   │
│  │ - id, title, description          │   │
│  │ - file_path (path to file)      │   │
│  │ - searchable_content (TEXT)      │   │ ← Extracted text
│  │ - tags, category, etc.           │   │
│  └───────────────────────────────────┘   │
│  ┌───────────────────────────────────┐   │
│  │ FTS5 Virtual Table               │   │ ← Full-text search index
│  │ - Indexes searchable_content     │   │
│  └───────────────────────────────────┘   │
└─────────────────────────────────────────┘
              │
              │ references
              ▼
┌─────────────────────────────────────────┐
│      Filesystem Storage                 │
│  web/static/knowledge_base/             │
│    documents/                           │
│      1/v1/document.pdf                  │ ← Actual file
│      2/v1/training.docx                 │
│      3/v1/presentation.pptx              │
└─────────────────────────────────────────┘
```

**This matches your current pattern with mission plans!**

## SQLite FTS5 Full-Text Search

### Capabilities

SQLite FTS5 provides:
- **Fast text search** across large text content
- **Ranking** - Results sorted by relevance
- **Phrase matching** - Find exact phrases
- **Boolean operators** - AND, OR, NOT
- **Prefix matching** - "wave*" finds "wave", "waves", "waveform"
- **Multi-column search** - Search across title, content, tags simultaneously

### Example FTS5 Implementation

```python
# Create FTS5 virtual table (in migration)
CREATE VIRTUAL TABLE knowledge_documents_fts USING fts5(
    title,
    description,
    searchable_content,
    tags,
    content='knowledge_documents',
    content_rowid='id'
);

# Search query
SELECT 
    d.*,
    rank
FROM knowledge_documents d
JOIN (
    SELECT 
        rowid,
        rank
    FROM knowledge_documents_fts
    WHERE knowledge_documents_fts MATCH 'wave glider troubleshooting'
    ORDER BY rank
    LIMIT 20
) fts ON d.id = fts.rowid
ORDER BY fts.rank;
```

### Performance

- **Small to medium document sets** (< 10,000 documents): Excellent
- **Large document sets** (10,000-100,000): Good (may need optimization)
- **Very large** (> 100,000): Consider external search engine (Meilisearch, Elasticsearch)

**For your use case** (training materials, reference docs): SQLite FTS5 is perfect.

## Storage Requirements Estimate

### Per Document

- **Metadata**: ~1-5 KB (title, description, tags, etc.)
- **Extracted Text**: ~10-500 KB (depends on document size)
  - 10-page PDF: ~50-100 KB extracted text
  - 50-page manual: ~200-500 KB extracted text
  - PowerPoint: ~20-100 KB extracted text

### Total Estimate

For **1,000 documents**:
- Metadata: ~5 MB
- Extracted text: ~100-500 MB
- **Total database growth**: ~100-500 MB
- **Files on filesystem**: ~1-10 GB (depending on file sizes)

**SQLite can easily handle this** - your database would still be very manageable.

## Practical Limits & Considerations

### SQLite Limits (You Won't Hit These)

| Limit | Value | Your Use Case |
|-------|-------|---------------|
| Max database size | 281 TB | You'll need ~1-10 GB |
| Max text column | ~1 GB | Extracted text ~500 KB max |
| Max rows per table | Unlimited | Thousands of documents |
| Concurrent writes | Limited | Fine for your traffic |

### Performance Considerations

1. **Indexes**
   - Index `title`, `category`, `tags` for fast filtering
   - FTS5 handles text search indexing automatically

2. **Query Optimization**
   - Use LIMIT for search results (don't return thousands)
   - Cache frequently accessed documents
   - Paginate results

3. **Database Maintenance**
   - SQLite handles this automatically
   - Consider `VACUUM` if database grows large
   - Regular backups (your DB will still be small)

## Comparison: SQLite vs Alternatives

### SQLite (Your Current Choice) ✅

**Pros:**
- ✅ No additional setup (already using it)
- ✅ FTS5 built-in, powerful search
- ✅ Zero configuration
- ✅ Perfect for your scale
- ✅ Matches your existing architecture

**Cons:**
- ⚠️ Limited concurrent writes (fine for your use case)
- ⚠️ No built-in replication (not needed)

**Verdict**: **Perfect for your needs**

### PostgreSQL (Alternative)

**Pros:**
- Better for high concurrency
- More advanced features

**Cons:**
- ❌ Requires separate database server
- ❌ More complex setup
- ❌ Overkill for your use case

**Verdict**: **Not needed** - SQLite is sufficient

### External Search Engine (Meilisearch, Elasticsearch)

**Pros:**
- Best search performance at very large scale
- Advanced ranking algorithms

**Cons:**
- ❌ Additional infrastructure
- ❌ More complex to maintain
- ❌ Overkill for hundreds/thousands of documents

**Verdict**: **Not needed now** - can add later if you scale to 10,000+ documents

## Implementation Strategy

### Phase 1: Basic Search (Start Here)

Use SQL LIKE/ILIKE for simple search:
```python
# Simple but effective for moderate document sets
WHERE title ILIKE '%query%' 
   OR searchable_content ILIKE '%query%'
```

**Pros**: Simple, works immediately, no setup
**Cons**: Slower on very large datasets

### Phase 2: FTS5 (Recommended)

Add FTS5 virtual table for advanced search:
```python
# Fast, ranked, full-text search
WHERE knowledge_documents_fts MATCH 'query'
```

**Pros**: Fast, ranked results, powerful features
**Cons**: Slightly more complex setup

### Phase 3: External Search (Future, if needed)

Only if you grow to 10,000+ documents and need:
- Sub-second search across massive datasets
- Advanced ML-based ranking
- Multi-language support

## File Storage Best Practices

### ✅ DO (Your Current Pattern)

1. **Store files on filesystem**
   - `web/static/knowledge_base/documents/{id}/v{version}/file.pdf`
   - Fast access, easy to manage
   - Can be served directly by web server

2. **Store file path in database**
   - `file_path` column stores relative path
   - Easy to reference, update, version

3. **Store extracted text in database**
   - `searchable_content` TEXT column
   - Enables full-text search
   - Small compared to binary files

### ❌ DON'T

1. **Don't store binary files as BLOBs**
   - Makes database huge
   - Slow to read/write
   - Harder to backup

2. **Don't store files outside project directory**
   - Harder to deploy
   - Backup complexity
   - Path management issues

## Migration Path

### Step 1: Add Tables (No FTS5 yet)
- Create `knowledge_documents` table
- Store metadata and extracted text
- Use simple LIKE search initially

### Step 2: Add FTS5 (When ready)
- Create FTS5 virtual table
- Populate from existing documents
- Update search queries to use FTS5

### Step 3: Optimize (If needed)
- Add indexes
- Query optimization
- Caching layer

## Conclusion

### ✅ SQLite is Perfect for Your Knowledge Base

**Reasons:**
1. ✅ Already using SQLite - no new infrastructure
2. ✅ FTS5 provides excellent search capabilities
3. ✅ Scale is appropriate (hundreds/thousands of documents)
4. ✅ Matches your existing file storage pattern
5. ✅ Simple to implement and maintain

**What to Store:**
- ✅ Metadata (title, description, tags, etc.)
- ✅ Extracted text for search
- ✅ File paths (not file content)

**What NOT to Store:**
- ❌ Binary file content (keep on filesystem)

**Your current architecture pattern (files on filesystem, metadata in DB) is exactly right!**

## Next Steps

1. **Proceed with SQLite** - It's perfect for your needs
2. **Start with simple LIKE search** - Can upgrade to FTS5 later
3. **Follow your existing pattern** - Files on filesystem, metadata in DB
4. **Monitor performance** - If you grow to 10,000+ documents, consider FTS5 or external search

**Bottom Line**: Your SQLite database is absolutely up to the task. No changes needed to your database choice.

