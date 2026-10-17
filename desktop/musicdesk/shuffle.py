"""A shuffled round visits every distinct song once; Back follows history."""
import random


class ShuffleOrder:
    def __init__(self):
        self.reset()

    def reset(self):
        self.scope, self.pending, self.history = (), [], []
        self.visited = set()
        self.cursor = -1

    def sync(self, paths, current):
        scope = tuple(dict.fromkeys(paths))
        if not scope: return scope
        if self.cursor < 0 or self.history[self.cursor] != current:
            self.scope = scope
            self.pending = [path for path in scope if path != current]
            random.shuffle(self.pending)
            self.history = [current] if current in scope else []
            self.cursor = len(self.history) - 1
            self.visited = set(self.history)
        elif scope != self.scope:
            # Removing a queued song must not put already-played songs back.
            self.pending = [path for path in self.pending if path in scope]
            self.pending += [path for path in scope if path not in self.scope and path not in self.visited]
            prefix = [path for path in self.history[:self.cursor + 1] if path in scope]
            self.history = prefix + [path for path in self.history[self.cursor + 1:] if path in scope]
            self.cursor = len(prefix) - 1
            self.scope = scope
        return scope

    def upcoming(self, paths, current):
        if not self.sync(paths, current): return []
        return self.history[self.cursor + 1:] + list(reversed(self.pending))

    def step(self, paths, current, direction=1):
        scope = self.sync(paths, current)
        if not scope: return None
        if direction < 0:
            self.cursor = max(0, self.cursor - 1)
            return self.history[self.cursor] if self.history else scope[0]
        if self.cursor + 1 < len(self.history):
            self.cursor += 1
            return self.history[self.cursor]
        if not self.pending:
            self.pending = list(scope)
            random.shuffle(self.pending)
            self.visited.clear()
            if len(scope) > 1 and self.pending[-1] == current:
                self.pending[0], self.pending[-1] = self.pending[-1], self.pending[0]
        result = self.pending.pop()
        self.visited.add(result)
        self.history.append(result)
        # Only a bounded previous-song history is needed across rounds.
        self.history = self.history[-max(100, len(scope) * 2):]
        self.cursor = len(self.history) - 1
        return result
