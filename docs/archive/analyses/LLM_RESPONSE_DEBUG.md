# LLM Response Header Update - Debug Guide

## Changes Made

### 1. Backend (`app/routers/chatbot.py`)
- ✅ Added `llm_model = None` initialization
- ✅ Set `llm_model = settings.llm_model` when LLM response is generated
- ✅ Included `llm_model=llm_model` in `ChatbotResponse`

### 2. Schema (`app/core/models/schemas.py`)
- ✅ Added `llm_model: Optional[str] = None` to `ChatbotResponse`

### 3. Frontend (`web/static/js/chatbot.js`)
- ✅ Updated `addSynthesizedMessage()` to accept `llmModel` parameter
- ✅ Changed header from "AI-Generated Response" to "LLM (mistral:7b) Generated Response"
- ✅ Added fallback to "LLM Generated Response" if model name not provided

### 4. Template (`web/templates/chatbot.html`)
- ✅ Added cache-busting query parameter `?v=2.0` to force JavaScript reload

## Debugging Steps

### Step 1: Verify Backend Response
Open browser DevTools → Network tab → Send a chatbot query → Check the response:

```json
{
  "synthesized_response": "...",
  "llm_used": true,
  "llm_model": "mistral:7b",  // ← Should be present
  "sources_used": [...]
}
```

**If `llm_model` is missing or `null`:**
- Check if LLM service is actually being used
- Verify `llm_service.is_available()` returns `True`
- Check server logs for LLM errors

### Step 2: Check Browser Console
Open DevTools → Console tab → Look for debug logs:

```
LLM Response received: { hasSynthesized: true, llm_model: "mistral:7b", llm_used: true }
addSynthesizedMessage called with: { llmModel: "mistral:7b", ... }
```

**If `llmModel` is `undefined` or `null`:**
- The backend isn't sending it
- Check Step 1

### Step 3: Verify JavaScript is Loaded
In browser DevTools → Console, run:
```javascript
// Check if the function exists
typeof addSynthesizedMessage
// Should return "function"
```

### Step 4: Hard Refresh Browser
- **Chrome/Edge**: `Ctrl+Shift+R` or `Ctrl+F5`
- **Firefox**: `Ctrl+Shift+R` or `Ctrl+F5`
- **Safari**: `Cmd+Shift+R`

The cache-busting parameter `?v=2.0` should force a reload, but hard refresh ensures it.

### Step 5: Check if LLM is Actually Being Used
The new header only appears when:
1. `synthesized_response` is present (not empty)
2. `llm_used` is `true`
3. `llm_model` is set

**If you're seeing FAQ responses instead:**
- LLM might not be available
- Check `llm_service.is_available()` in server logs
- Verify Ollama is running: `curl http://localhost:11434/api/tags`

## Common Issues

### Issue 1: Still seeing "AI-Generated Response"
**Cause**: Browser cached old JavaScript
**Fix**: 
- Hard refresh (Ctrl+Shift+R)
- Clear browser cache
- Check Network tab to verify `chatbot.js?v=2.0` is loaded

### Issue 2: Seeing "LLM Generated Response" (no model name)
**Cause**: `llm_model` is `null` in response
**Possible reasons**:
- LLM service not available
- `synthesized_response` is empty
- Backend error setting `llm_model`

**Fix**: Check server logs for:
```
LLM (mistral:7b) synthesized response from X sources
```

### Issue 3: Not seeing LLM responses at all
**Cause**: LLM not being used, falling back to FAQs
**Check**:
1. Is Ollama running? `ollama list`
2. Is model installed? `ollama list | grep mistral`
3. Check `llm_enabled` in config
4. Check server logs for LLM errors

## Verification Checklist

- [ ] Backend response includes `llm_model` field
- [ ] Browser console shows debug logs with `llm_model`
- [ ] JavaScript file loads with `?v=2.0` parameter
- [ ] Hard refresh performed (Ctrl+Shift+R)
- [ ] LLM service is available (`llm_service.is_available()`)
- [ ] Ollama is running and model is installed
- [ ] Server logs show LLM synthesis happening

## Test Query

Try asking the chatbot:
```
"How do I share a tip?"
```

This should:
1. Use LLM to synthesize a response
2. Show header: "🤖 LLM (mistral:7b) Generated Response"
3. Display the model name in a green badge

## Expected Output

```
┌─────────────────────────────────────────┐
│ 🤖 LLM (mistral:7b) Generated Response  │
│                                         │
│ [Response content here...]             │
│                                         │
│ Sources: document: How to Share Tips    │
│                                         │
│ [👍 Helpful] [👎 Not Helpful]          │
└─────────────────────────────────────────┘
```

The model name `mistral:7b` should appear in a green badge.
