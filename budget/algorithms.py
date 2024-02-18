from typing import TypeVar, Iterable,  Generic
from collections import defaultdict, deque
from dataclasses import dataclass

T = TypeVar('T')


def sign(i: int) -> int:
    return (i > 0) - (i < 0)


@dataclass(init=False)
class Debts(Generic[T]):
    debts: dict[int, dict[int, list[T]]]

    def __init__(self, input: Iterable[tuple[T, int]]):
        self.debts = {-1: {}, 0: {}, 1: {}}
        for account, key in input:
            self.push(key, account)

    def __bool__(self):
        return any(self.debts.values())

    def push(self, key: int, account: T):
        self.debts[sign(key)].setdefault(key, []).append(account)

    def pop(self, key: int) -> T:
        result = self.debts[sign(key)][key].pop()
        if not self.debts[sign(key)][key]:
            del self.debts[sign(key)][key]
        return result

    def pop_by_sign(self, key: int) -> tuple[int, T]:
        if self.debts[sign(key)]:
            key = next(iter(self.debts[sign(key)].keys()))
            return key, self.pop(key)
        elif self.debts[-sign(key)]:
            key = next(iter(self.debts[-sign(key)].keys()))
            return key, self.pop(key)
        elif self.debts[0]:
            return 0, self.pop(0)
        else:
            raise KeyError(key)  # pragma: no cover

    def combine_one(self, amount: int, sink: T) -> dict[tuple[T, T], int]:
        result: dict[tuple[T, T], int] = defaultdict(int)
        while amount:
            if not self:
                raise ValueError("Amounts do not sum to zero")
            if -amount in self.debts[-sign(amount)]:
                source = self.pop(-amount)
                result[(source, sink)] = amount
                return result
            other, source = self.pop_by_sign(-amount)
            if other:
                edge = sign(amount) * min(abs(amount), abs(other))
            else:
                edge = amount
            result[(source, sink)] += edge
            self.push(other + edge, source)
            amount -= edge
        return result

    def combine(self) -> dict[tuple[T, T], int]:
        result: dict[tuple[T, T], int] = {}
        while self:
            amount, sink = self.pop_by_sign(1)
            result |= self.combine_one(amount, sink)
        return result


def sum_by(input: Iterable[tuple[T, int]]) -> defaultdict[T, int]:
    result: defaultdict[T, int] = defaultdict(int)
    for key, value in input:
        result[key] += value
    for key in list(result.keys()):
        if not result[key]:
            del result[key]
    return result


# 'tree' below are child->parent edges, and can also be a forest


def reroot(tree: dict[T, T], node: T):
    if node in tree:
        parent = tree[node]
        del tree[node]
        while parent:
            parent2 = tree.get(parent)
            tree[parent] = node
            parent, node = parent2, parent


def double_entrify_by(amounts: dict[T, int], tree: dict[T, T]):
    result: dict[tuple[T, T], int] = {}
    leaves = deque(tree.keys() - tree.values())
    while leaves:
        source = leaves.popleft()
        if source not in tree:
            continue
        sink = tree[source]
        leaves.append(sink)
        result[(source, sink)] = -amounts[source]
        amounts[sink] += amounts[source]
        amounts[source] = 0
    return result
