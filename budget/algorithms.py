from typing import TypeVar, Iterable
from collections import defaultdict, deque

T = TypeVar('T')


def sum_by(input: Iterable[tuple[T, int]]) -> dict[T, int]:
    result: defaultdict[T, int] = defaultdict(int)
    for key, value in input:
        result[key] += value
    return {key: value for key, value in result.items() if value}


def combine_debts(debts: dict[T, int]) -> dict[tuple[T, T], int]:
    result: dict[tuple[T, T], int] = {}
    amounts = deque(sorted((amount, t)
                           for (t, amount) in debts.items()
                           if amount != 0))
    amount, source = 0, None
    while amounts or amount:
        if not amount or not source:
            amount, source = amounts.popleft()
        if not amounts:
            raise ValueError("Amounts do not sum to zero")
        other, sink = amounts.pop()
        result[(source, sink)] = min(-amount, other)
        amount += other
        if amount > 0:
            amounts.append((amount, sink))
            amount = 0
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


def to_tree(edges: Iterable[tuple[T, T]]) -> dict[T, T]:
    pass
