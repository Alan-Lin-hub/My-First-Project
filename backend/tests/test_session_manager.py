"""Tests for SessionManager: history trimming and LRU session eviction."""
from session_manager import SessionManager


def test_evicts_oldest_session_over_cap():
    sm = SessionManager(max_history=2, max_sessions=2)
    s1 = sm.create_session()
    s2 = sm.create_session()
    s3 = sm.create_session()          # exceeds cap -> oldest (s1) is evicted

    assert s1 not in sm.sessions
    assert s2 in sm.sessions and s3 in sm.sessions


def test_lru_keeps_recently_used_session():
    sm = SessionManager(max_history=2, max_sessions=2)
    s1 = sm.create_session()
    s2 = sm.create_session()
    sm.add_message(s1, "user", "hi")  # touch s1 -> now most-recently-used
    s3 = sm.create_session()          # should evict s2 (the LRU), not s1

    assert s2 not in sm.sessions
    assert s1 in sm.sessions and s3 in sm.sessions


def test_history_trimmed_to_max():
    sm = SessionManager(max_history=2, max_sessions=10)
    sid = sm.create_session()
    for i in range(10):
        sm.add_message(sid, "user", f"m{i}")

    # At most max_history exchanges (user+assistant) = max_history * 2 messages.
    assert len(sm.sessions[sid]) <= 2 * 2
    # And the most recent message is retained.
    assert sm.sessions[sid][-1].content == "m9"
