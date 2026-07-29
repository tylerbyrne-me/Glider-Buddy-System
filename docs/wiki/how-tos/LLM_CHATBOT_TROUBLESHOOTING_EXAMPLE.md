# Chatbot Troubleshooting Search - Example Flow

## Scenario: User asks troubleshooting question

**User Query**: "My sensor is showing error code 1234, how do I fix it?"

## Search Flow with Vector Search + LLM

### Step 1: Intent Detection
- Query contains "error", "fix" → Identified as troubleshooting query

### Step 2: Targeted Vector Search

#### 2a. Search Troubleshooting Documents
```python
# Search documents with category="troubleshooting" or tag="troubleshooting"
doc_results = vector_service.search_documents(
    query="sensor error code 1234 fix",
    category_filter="troubleshooting",  # Only search troubleshooting docs
    limit=3
)
```

**Result**: Finds relevant sections from troubleshooting manuals that mention error 1234

#### 2b. Search Troubleshooting Tips
```python
# Search tips with troubleshooting category or tags
tip_results = vector_service.search_tips(
    query="sensor error code 1234 fix",
    category_filter="troubleshooting",  # Or tag_filter="troubleshooting"
    limit=3
)
```

**Result**: Finds shared tips from pilots who solved similar issues

### Step 3: LLM Synthesis

**Context Built**:
```
Document 1 (similarity: 0.89):
Title: "Sensor Troubleshooting Guide"
Content: "Error code 1234 indicates a communication failure. 
Check the sensor cable connections at port A. If connections 
are secure, power cycle the sensor..."

Document 2 (similarity: 0.76):
Title: "Common Sensor Issues"
Content: "For error 1234, first verify the sensor is receiving 
power. Check the LED indicator..."

Tip 1 (similarity: 0.82):
Title: "Quick Fix for Error 1234"
Content: "I had this issue last week. The problem was a loose 
connector. Tightening it resolved the issue immediately..."
```

**LLM Prompt**:
```
User Question: "My sensor is showing error code 1234, how do I fix it?"

Relevant Troubleshooting Information:
[Document 1 content]
[Document 2 content]
[Tip 1 content]

Provide a clear, step-by-step answer based on this information.
Prioritize the most relevant solution (highest similarity).
Include links to the full documents if helpful.
```

**LLM Response**:
```
Based on the troubleshooting guides and tips, here's how to fix error code 1234:

1. **Check cable connections** - Error 1234 typically indicates a communication failure. 
   First, verify all sensor cable connections at port A are secure.

2. **Verify power** - Check that the sensor is receiving power by looking at the LED indicator.

3. **Power cycle** - If connections are secure, try power cycling the sensor.

**Quick Tip**: One pilot reported that tightening loose connectors immediately resolved this issue.

For more details, see:
- 📄 Sensor Troubleshooting Guide (full manual)
- 💡 Quick Fix for Error 1234 (shared tip)
```

### Step 4: Response with Sources

The chatbot returns:
- **Answer**: Synthesized from multiple troubleshooting sources
- **Sources**: Links to the specific documents and tips used
- **Confidence**: High (0.89 similarity to primary source)

---

## Key Features

### ✅ Category/Tag Filtering
- Documents tagged "troubleshooting" are searched first
- Tips with troubleshooting category are prioritized
- Can filter by multiple tags (e.g., "troubleshooting" + "sensor")

### ✅ Semantic Search
- Finds relevant content even if exact words don't match
- "fix error" matches "troubleshooting steps"
- "sensor problem" matches "sensor issues"

### ✅ Multi-Source Synthesis
- Combines information from:
  - Official troubleshooting manuals
  - Community tips and tricks
  - Previous FAQ answers
- LLM creates coherent answer from all sources

### ✅ Intelligent Prioritization
- Higher similarity = more relevant
- Troubleshooting docs ranked higher for troubleshooting queries
- Tips from community provide real-world solutions

---

## Example Use Cases

### Use Case 1: Specific Error Code
**Query**: "What does error 5678 mean?"
- Searches troubleshooting documents
- Finds error code reference section
- Returns explanation + solution steps

### Use Case 2: General Problem
**Query**: "My wave glider won't respond to commands"
- Searches troubleshooting docs (general)
- Searches tips (community solutions)
- LLM synthesizes common causes and fixes

### Use Case 3: Procedure Question
**Query**: "How do I calibrate the CTD sensor?"
- Searches documentation (procedures)
- Searches tips (pilot experiences)
- Returns step-by-step guide

### Use Case 4: Equipment-Specific
**Query**: "Troubleshooting GPS issues"
- Filters by tag: "gps" + category: "troubleshooting"
- Finds GPS-specific troubleshooting sections
- Returns targeted solution

---

## Implementation Benefits

1. **Precise Targeting**: Category/tag filtering ensures relevant sources
2. **Better Matching**: Semantic search finds content even with different wording
3. **Comprehensive Answers**: Combines official docs + community knowledge
4. **Context-Aware**: LLM understands which sources are most relevant
5. **Source Attribution**: Users can verify and read full documents

---

## Configuration Example

```python
# In chatbot query processing
if "troubleshooting" in query.lower() or "error" in query.lower() or "fix" in query.lower():
    # Prioritize troubleshooting sources
    doc_results = vector_service.search_documents(
        query=query,
        category_filter="troubleshooting",  # Only troubleshooting docs
        limit=5
    )
    
    tip_results = vector_service.search_tips(
        query=query,
        category_filter="troubleshooting",  # Only troubleshooting tips
        limit=5
    )
else:
    # General search across all categories
    doc_results = vector_service.search_documents(query=query, limit=5)
    tip_results = vector_service.search_tips(query=query, limit=5)
```

This ensures troubleshooting queries get the most relevant, targeted results!
