# DF-CURRICULUM-ORCHESTRATOR [CRUX-MK]
"""5-Level Curriculum + Partner-Knowledge-Base (PKB)."""

# LAZY-IMPORT-PATTERN (Dual-Import-Bug-Vermeidung per coding.md §1)
__all__ = [
    "CurriculumManager",
    "CurriculumLevel",
    "PartnerKnowledgeBase",
    "ProgressTracker",
    "AdapterOrchestrator",
    "AuditLogger",
    "K16Mutex",
    "Learner",
    "run_curriculum_audit",
]

def __getattr__(name: str):
    if name in __all__:
        from . import engine
        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
