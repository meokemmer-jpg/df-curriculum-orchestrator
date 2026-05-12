# DF-CURRICULUM-ORCHESTRATOR [CRUX-MK]

5-Level Curriculum + Partner-Knowledge-Base (PKB) Orchestrator.

## Architektur

- `src/engine.py` — CurriculumManager + PartnerKnowledgeBase + ProgressTracker + AdapterOrchestrator + AuditLogger
- `tests/test_engine.py` — 14 Tests
- `scripts/run-df-curriculum-orchestrator.sh` — K16-Mutex Wrapper

## 5 Levels

- L1_INDUCTION
- L2_FOUNDATION
- L3_PRACTITIONER
- L4_EXPERT
- L5_MASTER

## SAE-v8 Integration

LAZY-IMPORT-PATTERN: Kein `from sae_v8.xxx`.

## Test

```bash
python3 -m pytest tests/ -q
```

[CRUX-MK]
