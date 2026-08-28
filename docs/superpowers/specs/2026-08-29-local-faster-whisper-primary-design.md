# Design: Local faster-whisper Primary + Groq Fallback

**Date:** 2026-08-29  
**Status:** Approved for implementation

## Goal

Make free open-source **faster-whisper** (`large-v3`) the primary STT on the local machine/Docker. Use paid **Groq `whisper-large-v3-turbo`** only as fallback when local STT fails or returns empty text.

## Pipeline

```
WhatsApp OGG bytes
  → primary: faster-whisper large-v3 (local, language=hi)
  → if fail/empty and GROQ_API_KEY set: Groq whisper-large-v3-turbo
  → else None (existing Hindi failure reply)
```

## Config

| Env | Default | Purpose |
|-----|---------|---------|
| `FASTER_WHISPER_MODEL` | `large-v3` | Local model id |
| `FASTER_WHISPER_DEVICE` | `cpu` | `cpu` / `cuda` / `auto` |
| `FASTER_WHISPER_COMPUTE_TYPE` | `int8` | CPU-friendly quantization |
| `FASTER_WHISPER_ENABLED` | `true` | Allow disabling local STT |
| `GROQ_API_KEY` | empty | Fallback cloud STT |
| `GROQ_STT_MODEL` | `whisper-large-v3-turbo` | Fallback model |

## Non-goals

- Dual-pass / confidence routing beyond fail→fallback
- n8n changes
- DB migration
