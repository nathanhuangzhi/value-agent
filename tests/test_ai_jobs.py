"""The reply job keeps generating (and buffering) after its first follower
leaves, and a later follower can replay from any index."""
import json
import time

from app.ai import jobs


def _frames(it):
    return [json.loads(f.split("data: ", 1)[1]) for f in it if f.startswith("id:")]


def test_follow_survives_disconnect_and_replays(monkeypatch):
    def fake_stream_reply(conv, text, model):
        for i in range(5):
            time.sleep(0.02)
            yield {"type": "delta", "text": str(i)}
        yield {"type": "done", "message": {"content": "01234"}}

    monkeypatch.setattr(jobs, "stream_reply", fake_stream_reply)
    jobs._jobs.clear()
    job = jobs.start({"id": "c1"}, "hi", "m")

    first = jobs.follow(job, 0)
    next(first)
    next(first)                             # read two frames, then "drop the socket"
    first.close()
    assert jobs.is_pending("c1")

    later = _frames(jobs.follow(job, 2))    # reconnect from where we left off
    assert [e["text"] for e in later if e["type"] == "delta"] == ["2", "3", "4"]
    assert later[-1]["type"] == "done"
    assert not jobs.is_pending("c1")
    assert jobs.get("c1") is job            # kept for a while after completion
    assert len(_frames(jobs.follow(job, 0))) == 6


def test_second_start_while_busy_is_rejected(monkeypatch):
    def slow(conv, text, model):
        time.sleep(0.2)
        yield {"type": "done", "message": {}}

    monkeypatch.setattr(jobs, "stream_reply", slow)
    jobs._jobs.clear()
    jobs.start({"id": "c2"}, "a", "m")
    try:
        jobs.start({"id": "c2"}, "b", "m")
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
