"""Reply generation decoupled from the HTTP connection.

A phone that goes to the background loses its socket within seconds. If the
DeepSeek loop ran inside the response generator (as it used to), that drop
killed the generation and the reply was never stored. Now `start()` runs
`stream_reply` on its own thread and buffers every event; any number of
clients can `follow()` the buffer — the one that sent the message, or a
later reconnect from `GET /conversations/{id}/stream?from=N` — and the
reply is persisted by `stream_reply` itself regardless of who is listening.

Finished jobs are kept for `_KEEP_S` so a reconnect after completion still
replays the tail (including the `done` event); older ones are evicted
lazily and the client falls back to reloading the conversation.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator

from app.ai.chat import stream_reply

_KEEP_S = 15 * 60
_PING_S = 15


class Job:
    def __init__(self, conv_id: str):
        self.conv_id = conv_id
        self.events: list[dict] = []
        self.done = False
        self.finished_at: float | None = None
        self.cond = threading.Condition()

    def _run(self, conv: dict, text: str, model: str) -> None:
        try:
            for ev in stream_reply(conv, text, model):
                with self.cond:
                    self.events.append(ev)
                    self.cond.notify_all()
        except Exception as e:  # stream_reply reports its own errors; this is a last resort
            with self.cond:
                self.events.append({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            with self.cond:
                self.done = True
                self.finished_at = time.time()
                self.cond.notify_all()


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _evict() -> None:
    cutoff = time.time() - _KEEP_S
    for cid, j in list(_jobs.items()):
        if j.done and j.finished_at and j.finished_at < cutoff:
            del _jobs[cid]


def get(conv_id: str) -> Job | None:
    with _lock:
        _evict()
        return _jobs.get(conv_id)


def is_pending(conv_id: str) -> bool:
    j = get(conv_id)
    return bool(j and not j.done)


def start(conv: dict, text: str, model: str) -> Job:
    """Begin generating; raises RuntimeError if this conversation is already busy."""
    with _lock:
        _evict()
        cur = _jobs.get(conv["id"])
        if cur and not cur.done:
            raise RuntimeError("a reply is already being generated for this conversation")
        job = Job(conv["id"])
        _jobs[conv["id"]] = job
    threading.Thread(target=job._run, args=(conv, text, model), daemon=True,
                     name=f"ai-reply-{conv['id']}").start()
    return job


def follow(job: Job, from_index: int = 0) -> Iterator[str]:
    """SSE frames from event `from_index` onward; ends once the job is done.
    Emits a comment ping while idle so proxies keep the connection open."""
    i = max(0, from_index)
    while True:
        with job.cond:
            if i >= len(job.events) and not job.done:
                job.cond.wait(timeout=_PING_S)
            batch = job.events[i:]
            finished = job.done
        if not batch:
            if finished:
                return
            yield ": ping\n\n"          # lock released — never yield while holding cond
            continue
        for ev in batch:
            yield f"id: {i}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            i += 1
