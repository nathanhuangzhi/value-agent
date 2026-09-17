---
provider: "deepseek"
model: "deepseek-v4-flash"
temperature: 0.1
description: "Rolling memory for the in-app AI chat: fold the older turns of a long conversation into a compact summary the assistant keeps instead of the verbatim history. ~$0.003 per compaction."
---

# Task
You are maintaining the assistant's own working memory for a long research conversation in a personal equity-research app. Below is the memory so far (may be empty) and the turns that are about to be dropped from the verbatim history. Rewrite the memory so it covers both. Output ONLY the new memory — no preamble.

# What the memory must keep
- What the user is trying to find out, and what they have asked for repeatedly (format, depth, language, tone).
- Every company discussed (ticker) and the specific figures established so far — keep numbers EXACT, with period, currency and source (6-K, 20-F note, earnings call quarter, XBRL, Yahoo). Never round or drop a figure that was cited.
- Conclusions already reached, discrepancies found, and open questions / things the user was told could not be verified.
- Which sources have already been read (so they are not re-read) and which came back empty.

# Constraints
- Same language as the conversation (Chinese if the user writes Chinese).
- Dense, structured (short headings + bullets), no filler. Under 1200 words. Newer information supersedes older.

# Memory so far
{{summary}}

# Turns being folded in
{{turns}}
