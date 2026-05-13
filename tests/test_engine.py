"""Tests fuer DF-CURRICULUM-ORCHESTRATOR Engine [CRUX-MK]."""
from pathlib import Path

import pytest

from engine import (
    AdapterOrchestrator,
    AuditLogger,
    CurriculumAuditResult,
    CurriculumLevel,
    CurriculumManager,
    K16Mutex,
    Learner,
    PartnerKnowledgeBase,
    ProgressionResult,
    ProgressTracker,
    run_curriculum_audit,
)


# ============================================================
# CurriculumLevel
# ============================================================

def test_curriculum_level_progression() -> None:
    """L1 -> L2 -> ... -> L5 -> None."""
    assert CurriculumLevel.next_level(CurriculumLevel.L1_INDUCTION) == CurriculumLevel.L2_FOUNDATION
    assert CurriculumLevel.next_level(CurriculumLevel.L4_EXPERT) == CurriculumLevel.L5_MASTER
    assert CurriculumLevel.next_level(CurriculumLevel.L5_MASTER) is None


def test_curriculum_level_int_values() -> None:
    """IntEnum 1..5."""
    assert CurriculumLevel.L1_INDUCTION.value == 1
    assert CurriculumLevel.L5_MASTER.value == 5


# ============================================================
# PartnerKnowledgeBase
# ============================================================

def test_pkb_default_topics() -> None:
    """Default-PKB hat Topics fuer alle Levels."""
    pkb = PartnerKnowledgeBase()
    for level in CurriculumLevel:
        topics = pkb.topics_for_level(level)
        assert len(topics) > 0


def test_pkb_total_topics() -> None:
    """Default-PKB hat Pflicht-Topic-Count."""
    pkb = PartnerKnowledgeBase()
    # 3+3+3+3+2 = 14
    assert pkb.total_topics() == 14


# ============================================================
# CurriculumManager
# ============================================================

def test_manager_can_progress_when_all_done() -> None:
    """Alle Topics done -> can_progress=True."""
    manager = CurriculumManager()
    learner = Learner(
        learner_id="L1",
        current_level=CurriculumLevel.L1_INDUCTION,
        completed_topics={"topic_intro_1", "topic_intro_2", "topic_intro_3"},
    )
    assert manager.can_progress(learner) is True


def test_manager_cannot_progress_with_missing_topics() -> None:
    """Topics fehlen -> can_progress=False."""
    manager = CurriculumManager()
    learner = Learner(
        learner_id="L1",
        current_level=CurriculumLevel.L1_INDUCTION,
        completed_topics={"topic_intro_1"},  # 2 fehlen
    )
    assert manager.can_progress(learner) is False


def test_manager_progress_promotes() -> None:
    """progress() befoerdert wenn alle Topics done."""
    manager = CurriculumManager()
    learner = Learner(
        learner_id="L1",
        current_level=CurriculumLevel.L1_INDUCTION,
        completed_topics={"topic_intro_1", "topic_intro_2", "topic_intro_3"},
    )
    result = manager.progress(learner)
    assert result.promoted is True
    assert result.new_level == CurriculumLevel.L2_FOUNDATION
    assert learner.current_level == CurriculumLevel.L2_FOUNDATION
    assert learner.last_progression_ts is not None


def test_manager_progress_blocked_at_master() -> None:
    """L5 -> kein weiterer Schritt."""
    manager = CurriculumManager()
    learner = Learner(
        learner_id="L1",
        current_level=CurriculumLevel.L5_MASTER,
        completed_topics={"topic_master_1", "topic_master_2"},
    )
    result = manager.progress(learner)
    assert result.promoted is False
    assert result.reason == "already_at_master"


def test_manager_progress_missing_topics_no_promote() -> None:
    """Missing topics -> kein Promote."""
    manager = CurriculumManager()
    learner = Learner(
        learner_id="L1",
        current_level=CurriculumLevel.L1_INDUCTION,
        completed_topics={"topic_intro_1"},
    )
    result = manager.progress(learner)
    assert result.promoted is False
    assert result.reason == "missing_topics"
    assert learner.current_level == CurriculumLevel.L1_INDUCTION


# ============================================================
# ProgressTracker
# ============================================================

def test_progress_tracker_empty() -> None:
    """Leerer Tracker."""
    tracker = ProgressTracker()
    snap = tracker.snapshot([])
    assert snap.total_learners == 0
    assert snap.average_mastery == 0.0


def test_progress_tracker_mixed_levels() -> None:
    """Mix von Levels."""
    tracker = ProgressTracker()
    learners = [
        Learner("L1", CurriculumLevel.L1_INDUCTION, mastery_score=0.5),
        Learner("L2", CurriculumLevel.L5_MASTER, mastery_score=1.0),
    ]
    snap = tracker.snapshot(learners)
    assert snap.total_learners == 2
    assert snap.masters_count == 1
    assert snap.average_mastery == 0.75


# ============================================================
# AdapterOrchestrator
# ============================================================

def test_orchestrator_attempt_progress() -> None:
    """Orchestrator wickelt progression ab."""
    orch = AdapterOrchestrator()
    learner = Learner(
        learner_id="L1",
        current_level=CurriculumLevel.L1_INDUCTION,
        completed_topics={"topic_intro_1", "topic_intro_2", "topic_intro_3"},
    )
    result = orch.attempt_progress(learner)
    assert result.promoted is True
    assert len(orch.progression_history) == 1


def test_orchestrator_audit() -> None:
    """Audit aggregiert."""
    orch = AdapterOrchestrator()
    learners = [
        Learner("L1", CurriculumLevel.L1_INDUCTION,
                completed_topics={"topic_intro_1", "topic_intro_2", "topic_intro_3"}),
        Learner("L2", CurriculumLevel.L5_MASTER),
    ]
    orch.attempt_progress(learners[0])
    audit = orch.audit(learners)
    assert audit.learners_total == 2
    assert audit.progressions_attempted == 1
    assert audit.progressions_succeeded == 1


# ============================================================
# K16-Mutex
# ============================================================

def test_k16_mutex(tmp_path: Path) -> None:
    """K16-Mutex blockt zweite Instanz."""
    lock = tmp_path / ".lock"
    m1 = K16Mutex(lock)
    assert m1.acquire() is True
    m2 = K16Mutex(lock)
    assert m2.acquire() is False
    m1.release()


# ============================================================
# AuditLogger
# ============================================================

def test_audit_logger_appends(tmp_path: Path) -> None:
    logger = AuditLogger(tmp_path / "audit.jsonl")
    logger.log({"r": 1})
    logger.log({"r": 2})
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2


# ============================================================
# run_curriculum_audit Integration
# ============================================================

def test_run_curriculum_audit_full(tmp_path: Path) -> None:
    """Full Audit-Run mit 3 Lerner."""
    config = {
        "paths": {"audit_log": "audit.jsonl"},
        "k16_concurrent_spawn_mutex": {"lock_dir": str(tmp_path / ".lock")},
    }
    learners = [
        Learner("L1", CurriculumLevel.L1_INDUCTION,
                completed_topics={"topic_intro_1", "topic_intro_2", "topic_intro_3"}),
        Learner("L2", CurriculumLevel.L2_FOUNDATION,
                completed_topics={"topic_foundation_1"}),
        Learner("L3", CurriculumLevel.L5_MASTER),
    ]
    result = run_curriculum_audit(tmp_path, config, learners=learners)
    assert result.learners_total == 3
    assert result.progressions_attempted == 3
    # L1 wird promoted, L2 hat fehlende Topics, L3 ist schon Master
    assert result.progressions_succeeded == 1
    assert (tmp_path / "audit.jsonl").exists()


def test_run_curriculum_audit_stop_flag(tmp_path: Path) -> None:
    """STOP.flag blockt."""
    config = {
        "paths": {"audit_log": "audit.jsonl"},
        "k16_concurrent_spawn_mutex": {"lock_dir": str(tmp_path / ".lock")},
    }
    stop = tmp_path / "STOP.flag"
    stop.write_text("stop")
    result = run_curriculum_audit(tmp_path, config, stop_flag=stop)
    assert result.skipped_due_to_stop_flag is True


# ============================================================
# W49-D K12+K13 Migration Tests
# ============================================================

def test_w49d_k12_envelope_and_k13_anchor(tmp_path: Path) -> None:
    """K12 envelope + K13 RFC3161-anchor are produced by run_curriculum_audit."""
    config = {
        "paths": {"audit_log": "audit.jsonl"},
        "k16_concurrent_spawn_mutex": {"lock_dir": str(tmp_path / ".lock-w49d")},
    }
    learners = [Learner("L1", CurriculumLevel.L1_INDUCTION)]
    result = run_curriculum_audit(tmp_path, config, learners=learners)
    assert not result.skipped_due_to_stop_flag
    from engine import W49D_FOUNDATION
    if W49D_FOUNDATION:
        prov_dir = tmp_path / "provenance-full"
        assert prov_dir.exists()
        envs = list(prov_dir.glob("*.envelope.json"))
        assert len(envs) >= 1
        anchors = tmp_path / "anchors" / "rfc3161-anchors.jsonl"
        assert anchors.exists()
        assert anchors.read_text().strip()
