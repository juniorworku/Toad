"""Full-duplex fragments and fresh user wording for client delegation."""

from typing import Any


class Transcript:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []
        self.pending = ""

    def add(self, role: str, delta: str, start_ms: int = 0) -> None:
        if self.turns and self.turns[-1]["role"] == role:
            self.turns[-1]["text"] += delta
        else:
            self.turns.append({"role": role, "text": delta, "startMs": start_ms})
        self.turns = self.turns[-200:]
        if role == "user":
            self.pending += delta

    def note(self, role: str, text: str) -> None:
        pending = self.pending
        self.add(role, text)
        self.pending = pending

    def take_user_request(self) -> str:
        pending, self.pending = self.pending.strip(), ""
        return pending

    def previous_assistant(self) -> str | None:
        words = [t["text"].strip() for t in self.turns if t["role"] == "assistant"][-2:]
        return " ".join(words) if words else None

    def recent_user(self, count: int = 4) -> str:
        """The user's last turns joined: a request often spans several ("call my friend" … "yes")."""
        said = [t["text"].strip() for t in self.turns if t["role"] == "user"]
        return " ".join(said[-count:])

    def recent(self, limit: int = 20) -> str:
        return "\n".join(
            f"{'User' if t['role'] == 'user' else 'Toad'}: {t['text'].strip()}"
            for t in self.turns[-limit:]
        )
