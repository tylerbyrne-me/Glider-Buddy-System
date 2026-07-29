# Document Template for Wave Glider Buddy RAG System

This template defines the optimal structure for knowledge base documents to maximize
retrieval accuracy and LLM response quality.

---

## Why Structure Matters

Our RAG system:
1. **Chunks** large documents into ~1000 character segments
2. **Embeds** each chunk for semantic search
3. **Retrieves** the most relevant chunks for a query
4. **Generates** answers using Mistral 7B with retrieved context

**Well-structured documents** ensure that:
- Each chunk is self-contained and meaningful
- Section headers provide context even when chunk is isolated
- Keywords and error codes are easily searchable
- The LLM can cite specific procedures accurately

---

## Document Categories

Use these categories consistently:

| Category | Use For |
|----------|---------|
| `troubleshooting` | Error codes, fixes, diagnostic procedures |
| `procedures` | Step-by-step operational guides |
| `sensors` | Sensor specs, calibration, maintenance |
| `piloting` | Navigation, mission planning, controls |
| `maintenance` | Hardware upkeep, replacements |
| `reference` | Quick reference, specs, tables |

---

## Template Structure

```markdown
# [Document Title]

**Category:** [troubleshooting|procedures|sensors|piloting|maintenance|reference]
**Tags:** [comma-separated keywords]
**Last Updated:** [YYYY-MM-DD]
**Applies To:** [Wave Glider model/version if relevant]

## Overview

[1-2 sentence summary of what this document covers. This helps the LLM understand
the document's scope when only partial chunks are retrieved.]

---

## Section 1: [Clear Descriptive Title]

### Subsection 1.1: [Specific Topic]

[Content here. Keep paragraphs focused on ONE concept.]

[For procedures, use numbered steps:]

1. Step one description
2. Step two description
3. Step three description

### Subsection 1.2: [Another Topic]

[More content...]

---

## Section 2: [Another Major Section]

[Continue pattern...]

---

## Quick Reference

[Optional: Include a summary table or quick-reference list that captures
the key points. This creates a high-value chunk for common queries.]

| Item | Value/Action |
|------|--------------|
| Key point 1 | Details |
| Key point 2 | Details |

---

## Related Resources

- [Link or reference to related document]
- [Link or reference to related FAQ]
```

---

## Template: Troubleshooting Document

```markdown
# [Component/System Name] Troubleshooting Guide

**Category:** troubleshooting
**Tags:** [component], error, fix, diagnostic
**Last Updated:** YYYY-MM-DD
**Applies To:** [Models/versions]

## Overview

This guide covers common issues with [component/system] including error codes,
symptoms, and step-by-step resolution procedures.

---

## Error Code Reference

| Error Code | Meaning | Severity | Quick Fix |
|------------|---------|----------|-----------|
| E001 | [Description] | High | [Brief action] |
| E002 | [Description] | Medium | [Brief action] |
| E003 | [Description] | Low | [Brief action] |

---

## Issue: [Error Code or Symptom Name]

### Symptoms
- [Observable symptom 1]
- [Observable symptom 2]
- [Observable symptom 3]

### Likely Causes
1. [Most common cause]
2. [Second most common cause]
3. [Less common cause]

### Resolution Steps

**Prerequisites:** [Any required tools, access, or conditions]

1. **[Action verb] [what to do]**
   - Detail or sub-step if needed
   - Expected result: [what you should see]

2. **[Next action]**
   - Detail or sub-step
   - Expected result: [what you should see]

3. **[Verification step]**
   - How to confirm the issue is resolved

### If Issue Persists

[Escalation path or alternative approaches]

---

## Issue: [Next Error/Symptom]

[Repeat pattern above...]

---

## Diagnostic Commands

| Command | Purpose | Expected Output |
|---------|---------|-----------------|
| `command1` | [What it checks] | [Normal output] |
| `command2` | [What it checks] | [Normal output] |

---

## Prevention Tips

- [Preventive measure 1]
- [Preventive measure 2]
- [Regular maintenance task]
```

---

## Template: Procedure Document

```markdown
# How to [Task Name]

**Category:** procedures
**Tags:** [task-type], setup, guide, [specific-keywords]
**Last Updated:** YYYY-MM-DD
**Applies To:** [Models/versions]

## Overview

This procedure describes how to [brief description of the task and outcome].
Estimated time: [X minutes/hours]

---

## Prerequisites

Before starting, ensure you have:

- [ ] [Required item/access/condition 1]
- [ ] [Required item/access/condition 2]
- [ ] [Required software/tool]

## Safety Warnings

> ⚠️ **WARNING:** [Critical safety information]

---

## Procedure Steps

### Step 1: [Descriptive Phase Name]

[Brief description of this phase's goal]

1. [Specific action]
   - Expected result: [what happens]

2. [Next action]
   - Expected result: [what happens]

### Step 2: [Next Phase]

[Continue with numbered steps...]

### Step 3: Verification

Confirm success by checking:

- [ ] [Verification item 1]
- [ ] [Verification item 2]

---

## Troubleshooting This Procedure

| Problem During Procedure | Solution |
|--------------------------|----------|
| [Common issue 1] | [Quick fix] |
| [Common issue 2] | [Quick fix] |

---

## Notes

- [Any additional tips or considerations]
- [Version-specific notes if applicable]
```

---

## Template: Sensor Document

```markdown
# [Sensor Name] Reference Guide

**Category:** sensors
**Tags:** [sensor-type], calibration, specifications, [sensor-name]
**Last Updated:** YYYY-MM-DD
**Applies To:** [Models/versions]

## Overview

The [sensor name] is used for [purpose]. This guide covers specifications,
calibration procedures, and common issues.

---

## Specifications

| Parameter | Value | Units |
|-----------|-------|-------|
| Range | [min] - [max] | [unit] |
| Accuracy | ± [value] | [unit] |
| Resolution | [value] | [unit] |
| Update Rate | [value] | Hz |
| Operating Temp | [min] - [max] | °C |

---

## Normal Operating Values

| Condition | Expected Reading | Acceptable Range |
|-----------|------------------|------------------|
| [Condition 1] | [value] | [min - max] |
| [Condition 2] | [value] | [min - max] |

---

## Calibration Procedure

**Frequency:** [How often to calibrate]

### Prerequisites
- [Required equipment]
- [Environmental conditions]

### Steps

1. [Calibration step 1]
2. [Calibration step 2]
3. [Verification step]

---

## Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| [code] | [description] | [fix] |

---

## Maintenance Schedule

| Task | Frequency | Notes |
|------|-----------|-------|
| [Task 1] | [Daily/Weekly/etc] | [Details] |
| [Task 2] | [Frequency] | [Details] |
```

---

## Best Practices for RAG Optimization

### DO ✅

1. **Start each section with context**
   ```markdown
   ## GPS Antenna Troubleshooting
   
   This section covers issues specific to the GPS antenna module on Wave Glider SV3.
   ```

2. **Use consistent terminology**
   - Pick one term and use it everywhere (don't switch between "GPS module" and "navigation unit")

3. **Include error codes inline**
   ```markdown
   If you see error E1234 (GPS Signal Lost), first check the antenna connection.
   ```

4. **Keep paragraphs focused**
   - One concept per paragraph = better chunks

5. **Repeat key terms in different sections**
   - Helps retrieval find relevant content from multiple angles

6. **Use tables for structured data**
   - Tables chunk well and are easy for LLMs to parse

### DON'T ❌

1. **Don't use pronouns without context**
   ```markdown
   # Bad:
   Check it for damage. If it's broken, replace it.
   
   # Good:
   Check the antenna for damage. If the antenna is broken, replace the antenna.
   ```

2. **Don't bury error codes in prose**
   ```markdown
   # Bad:
   Sometimes the system shows various errors like 1234 or maybe 5678...
   
   # Good:
   ## Error 1234: GPS Signal Lost
   ## Error 5678: Antenna Disconnected
   ```

3. **Don't use long unbroken paragraphs**
   - Break at logical points every 2-3 sentences

4. **Don't assume context from previous sections**
   - Each section should be somewhat self-contained

---

## Example: Well-Structured Troubleshooting Entry

```markdown
## Error E1234: GPS Signal Lost

**Applies to:** Wave Glider SV3, SV2

### Symptoms

The Wave Glider displays error E1234 on the status panel. GPS coordinates stop
updating and navigation enters dead-reckoning mode.

### Likely Causes

1. **Antenna cable disconnection** (most common)
2. **Antenna damage from debris**
3. **GPS module firmware crash**

### Resolution: GPS Signal Lost (E1234)

1. **Check antenna cable connection**
   - Location: Top deck, port side junction box
   - Action: Verify cable is fully seated and locked
   - Expected: Click sound when properly connected

2. **Inspect antenna for physical damage**
   - Look for: cracks, corrosion, debris blocking receiver
   - Action: Clean with soft dry cloth if debris present

3. **Power cycle the GPS module**
   - Command: `gps_module restart`
   - Wait: 30 seconds for reinitialization
   - Verify: Status LED turns solid green

4. **Verify resolution**
   - Check: GPS coordinates updating on status display
   - Confirm: Error E1234 cleared from active alarms

### If Issue Persists

Contact support with:
- Screenshot of error display
- Output of `gps_module diagnostics`
- Recent mission log (last 1 hour)
```

---

## Converting Existing Documents

When converting existing documents to this format:

1. **Add metadata header** (category, tags, date)
2. **Add overview section** summarizing the document
3. **Break into logical sections** with clear headers
4. **Convert inline info to tables** where appropriate
5. **Add "Quick Reference" section** for common lookups
6. **Ensure error codes have their own subsections**

---

## File Naming Convention

```
[category]_[topic]_[specific].md

Examples:
- troubleshooting_gps_signal_errors.md
- procedure_sensor_calibration.md
- sensors_ctd_reference.md
- piloting_mission_planning_basics.md
```

This naming helps with organization and makes categories clear even before opening files.
