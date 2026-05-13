# DF-CURRICULUM-ORCHESTRATOR Engine [CRUX-MK]
"""
5-Level Curriculum + Partner-Knowledge-Base (PKB) Orchestrator.

Architektur:
- CurriculumManager: Level-Progression State-Machine (L1..L5)
- PartnerKnowledgeBase: Mock-PKB mit Topic-Coverage pro Level
- ProgressTracker: Lerner-Fortschritt (Level + Coverage + Mastery)
- AdapterOrchestrator: Aggregat Manager + PKB + Tracker
- AuditLogger: JSONL append-only

Per SAE-v8: 5-Level Curriculum + Partner-Wissensbasis.
"""
from __future__ import annotations

import json
import logging
import os
import sys as _sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any

# W49-D K12+K13 Foundation
_DF_ROOT = Path(__file__).resolve().parent.parent.parent
_sys.path.insert(0, str(_DF_ROOT))
try:
    from _df_common.full_provenance_envelope import build_full_envelope  # type: ignore
    from _df_common.rfc3161_anchor import rfc3161_timestamp  # type: ignore
    W49D_FOUNDATION = True
except ImportError:
    W49D_FOUNDATION = False

_K12_HMAC_SECRET = os.environ.get(
    "DF_CURRICULUM_HMAC_SECRET", "df-curriculum-orchestrator-dev-hmac-secret-v1"
)
_K12_ENVELOPE_TTL_S = int(os.environ.get("DF_CURRICULUM_ENVELOPE_TTL_S", "86400"))

_logger = logging.getLogger(__name__)


# ============================================================
# CurriculumLevel
# ============================================================

class CurriculumLevel(IntEnum):
    L1_INDUCTION = 1
    L2_FOUNDATION = 2
    L3_PRACTITIONER = 3
    L4_EXPERT = 4
    L5_MASTER = 5

    @classmethod
    def next_level(cls, current: "CurriculumLevel") -> "CurriculumLevel | None":
        if current == cls.L5_MASTER:
            return None
        return cls(current.value + 1)


class Severity(str):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    VETO = "VETO"


# ============================================================
# K16-Mutex (Pattern-Reuse)
# ============================================================

class K16Mutex:
    def __init__(self, lock_dir: Path) -> None:
        self.lock_dir = Path(lock_dir)

    def acquire(self) -> bool:
        try:
            self.lock_dir.mkdir(parents=False, exist_ok=False)
            (self.lock_dir / "pid").write_text(str(os.getpid()))
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        try:
            for child in self.lock_dir.iterdir():
                child.unlink()
            self.lock_dir.rmdir()
        except FileNotFoundError:
            pass


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: dict[str, Any]) -> None:
        record_with_ts = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record_with_ts, ensure_ascii=False) + "\n")


# ============================================================
# Learner
# ============================================================

@dataclass
class Learner:
    """Lerner-Zustand."""

    learner_id: str
    current_level: CurriculumLevel = CurriculumLevel.L1_INDUCTION
    completed_topics: set[str] = field(default_factory=set)
    mastery_score: float = 0.0
    last_progression_ts: str | None = None


# ============================================================
# PartnerKnowledgeBase (Mock)
# ============================================================

class PartnerKnowledgeBase:
    """Mock-PKB mit Topic-Liste pro Level."""

    DEFAULT_TOPICS: dict[CurriculumLevel, tuple[str, ...]] = {
        CurriculumLevel.L1_INDUCTION: ("topic_intro_1", "topic_intro_2", "topic_intro_3"),
        CurriculumLevel.L2_FOUNDATION: ("topic_foundation_1", "topic_foundation_2", "topic_foundation_3"),
        CurriculumLevel.L3_PRACTITIONER: ("topic_practitioner_1", "topic_practitioner_2", "topic_practitioner_3"),
        CurriculumLevel.L4_EXPERT: ("topic_expert_1", "topic_expert_2", "topic_expert_3"),
        CurriculumLevel.L5_MASTER: ("topic_master_1", "topic_master_2"),
    }

    def __init__(self, topics: dict[CurriculumLevel, tuple[str, ...]] | None = None) -> None:
        self.topics = topics or dict(self.DEFAULT_TOPICS)

    def topics_for_level(self, level: CurriculumLevel) -> tuple[str, ...]:
        return self.topics.get(level, ())

    def total_topics(self) -> int:
        return sum(len(t) for t in self.topics.values())


# ============================================================
# CurriculumManager
# ============================================================

@dataclass(frozen=True)
class ProgressionResult:
    learner_id: str
    old_level: CurriculumLevel
    new_level: CurriculumLevel
    promoted: bool
    reason: str


class CurriculumManager:
    """5-Level-State-Machine fuer Lerner-Progression."""

    # Promotion-Schwelle: alle Topics des aktuellen Levels abgeschlossen
    def __init__(self, pkb: PartnerKnowledgeBase | None = None) -> None:
        self.pkb = pkb or PartnerKnowledgeBase()

    def can_progress(self, learner: Learner) -> bool:
        required = set(self.pkb.topics_for_level(learner.current_level))
        return required.issubset(learner.completed_topics)

    def progress(self, learner: Learner) -> ProgressionResult:
        """Promote learner zu naechstem Level wenn alle Topics done.

        Pre: learner ist valid Instance
        Post: learner.current_level evtl erhoeht, mit Timestamp
        """
        old_level = learner.current_level
        if not self.can_progress(learner):
            return ProgressionResult(
                learner_id=learner.learner_id,
                old_level=old_level,
                new_level=old_level,
                promoted=False,
                reason="missing_topics",
            )
        next_level = CurriculumLevel.next_level(old_level)
        if next_level is None:
            # Bereits L5
            return ProgressionResult(
                learner_id=learner.learner_id,
                old_level=old_level,
                new_level=old_level,
                promoted=False,
                reason="already_at_master",
            )
        learner.current_level = next_level
        learner.last_progression_ts = datetime.now(timezone.utc).isoformat()
        return ProgressionResult(
            learner_id=learner.learner_id,
            old_level=old_level,
            new_level=next_level,
            promoted=True,
            reason="all_topics_completed",
        )


# ============================================================
# ProgressTracker
# ============================================================

@dataclass(frozen=True)
class ProgressSnapshot:
    total_learners: int
    learners_per_level: dict[int, int]
    average_mastery: float
    masters_count: int


class ProgressTracker:
    """Aggregiert Lerner-Statistik."""

    def snapshot(self, learners: list[Learner]) -> ProgressSnapshot:
        per_level: dict[int, int] = defaultdict(int)
        total_mastery = 0.0
        masters = 0
        for l in learners:
            per_level[l.current_level.value] += 1
            total_mastery += l.mastery_score
            if l.current_level == CurriculumLevel.L5_MASTER:
                masters += 1
        avg = total_mastery / len(learners) if learners else 0.0
        return ProgressSnapshot(
            total_learners=len(learners),
            learners_per_level=dict(per_level),
            average_mastery=avg,
            masters_count=masters,
        )


# ============================================================
# AdapterOrchestrator
# ============================================================

@dataclass(frozen=True)
class CurriculumAuditResult:
    learners_total: int
    progressions_attempted: int
    progressions_succeeded: int
    masters_count: int
    average_level: float
    skipped_due_to_stop_flag: bool = False


class AdapterOrchestrator:
    """Orchestriert CurriculumManager + PKB + Tracker."""

    def __init__(
        self,
        manager: CurriculumManager | None = None,
        tracker: ProgressTracker | None = None,
    ) -> None:
        self.manager = manager or CurriculumManager()
        self.tracker = tracker or ProgressTracker()
        self.progression_history: list[ProgressionResult] = []

    def attempt_progress(self, learner: Learner) -> ProgressionResult:
        result = self.manager.progress(learner)
        self.progression_history.append(result)
        return result

    def audit(self, learners: list[Learner]) -> CurriculumAuditResult:
        snap = self.tracker.snapshot(learners)
        succeeded = sum(1 for r in self.progression_history if r.promoted)
        avg_level = (
            sum(l.current_level.value for l in learners) / len(learners)
            if learners else 0.0
        )
        return CurriculumAuditResult(
            learners_total=snap.total_learners,
            progressions_attempted=len(self.progression_history),
            progressions_succeeded=succeeded,
            masters_count=snap.masters_count,
            average_level=avg_level,
        )


# ============================================================
# run_curriculum_audit
# ============================================================

def run_curriculum_audit(
    repo_root: Path,
    config: dict[str, Any],
    stop_flag: Path | None = None,
    learners: list[Learner] | None = None,
) -> CurriculumAuditResult:
    if stop_flag is not None and stop_flag.exists():
        return CurriculumAuditResult(0, 0, 0, 0, 0.0, skipped_due_to_stop_flag=True)

    lock_dir = Path(
        config.get("k16_concurrent_spawn_mutex", {}).get("lock_dir", "/tmp/df-curriculum-orchestrator.lock")
    )
    mutex = K16Mutex(lock_dir)
    if not mutex.acquire():
        return CurriculumAuditResult(0, 0, 0, 0, 0.0)

    try:
        audit_log_path = Path(repo_root) / config.get("paths", {}).get("audit_log", "audit.jsonl")
        logger = AuditLogger(audit_log_path)
        orchestrator = AdapterOrchestrator()
        learners = learners or []
        for learner in learners:
            orchestrator.attempt_progress(learner)
        result = orchestrator.audit(learners)
        run_id = f"curriculum-{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        logger.log({"event": "curriculum-audit-complete", "run_id": run_id, "result": asdict(result)})

        # W49-D K12: FullProvenanceEnvelope
        chain_hash_for_anchor: str | None = None
        if W49D_FOUNDATION:
            try:
                provenance_full_dir = audit_log_path.parent / "provenance-full"
                provenance_full_dir.mkdir(parents=True, exist_ok=True)
                predecessor_hash: str | None = None
                files = sorted(provenance_full_dir.glob("*.envelope.json"), key=lambda p: p.stat().st_mtime)
                if files:
                    try:
                        with files[-1].open("r", encoding="utf-8") as f:
                            predecessor_hash = json.load(f).get("payload_hash")
                    except (OSError, json.JSONDecodeError) as e:
                        _logger.warning(f"K12 predecessor read failed: {e}")
                envelope = build_full_envelope(
                    operation_id=run_id,
                    operation_type="df-curriculum-orchestrator-audit",
                    issuer="df-curriculum-orchestrator",
                    payload_dict=asdict(result),
                    secret=_K12_HMAC_SECRET,
                    predecessor_hash=predecessor_hash,
                    tenant_id="curriculum-aggregate",
                    ttl_seconds=_K12_ENVELOPE_TTL_S,
                )
                env_out = provenance_full_dir / f"{run_id}.envelope.json"
                with env_out.open("w", encoding="utf-8") as f:
                    json.dump(asdict(envelope), f, indent=2, default=str, ensure_ascii=False)
                chain_hash_for_anchor = envelope.payload_hash
            except Exception as e:
                _logger.warning(f"K12 envelope build failed (non-fatal): {e}")

        # W49-D K13: RFC3161 External-Anchor
        if W49D_FOUNDATION and chain_hash_for_anchor:
            try:
                rfc_anchor = rfc3161_timestamp(chain_hash_for_anchor, provider="freetsa")
                anchors_dir = audit_log_path.parent / "anchors"
                anchors_dir.mkdir(parents=True, exist_ok=True)
                with (anchors_dir / "rfc3161-anchors.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(rfc_anchor)) + "\n")
            except Exception as e:
                _logger.warning(f"K13 RFC3161 anchor failed (non-fatal): {e}")

        return result
    finally:
        mutex.release()
