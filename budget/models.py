from typing import Optional, Iterable, TypeVar, Type, Union, Any, Self, Generic
from collections import defaultdict, deque
import functools
from itertools import chain
from datetime import date, timedelta
from dataclasses import dataclass

from django.db import models, IntegrityError
from django.db.models import Q, Sum, F, OuterRef, Exists
from django.db.models.functions import Trunc
from django.urls import reverse
from django.contrib.auth.models import User, AnonymousUser, AbstractBaseUser

T = TypeVar('T')


class Id(models.Model):
    """Distinct identity for budgets, accounts, and categories"""
    id: models.BigAutoField
    of_budget: 'models.OneToOneField[Budget]'
    of_account: 'models.OneToOneField[Account]'
    of_category: 'models.OneToOneField[Category]'


class Budget(Id):
    class Meta:  # type: ignore
        constraints = [models.CheckConstraint(
            check=Q(budget_of__isnull=True) | Q(payee_of__isnull=True),
            name="cant_be_payee_and_budget")]

    id_ptr = models.OneToOneField(
        Id, related_name='of_budget',
        on_delete=models.CASCADE, parent_link=True)
    name = models.CharField(max_length=100)

    account_set: 'models.Manager[Account]'
    category_set: 'models.Manager[Category]'

    # This can easily be relaxed into a ForeignKey if we want to allow multiple
    # budgets
    budget_of_id: int
    budget_of = models.OneToOneField(
        User, blank=True, null=True, on_delete=models.SET_NULL)
    payee_of_id: int
    payee_of = models.ForeignKey(
        User, blank=True, null=True, on_delete=models.SET_NULL,
        related_name="payee_set")

    # Ignored for payees
    friends: 'models.ManyToManyField[Budget, Any]'
    friends = models.ManyToManyField('self', blank=True)

    def __str__(self):
        return self.name

    @functools.cache
    def get_absolute_url(self):
        return reverse('overview', kwargs={'budget_id': self.id})

    def get_inbox(self, cls: 'Type[AccountT]', currency: str
                  ) -> 'AccountT':
        return self.get_inbox_(cls, currency)

    @functools.cache
    def get_inbox_(self, cls: 'Type[AccountT]', currency: str) -> 'Any':
        return cls.objects.get_or_create(name="", budget=self,
                                         currency=currency)[0]

    def owner(self):
        return self.budget_of_id or self.payee_of_id

    def main_budget(self):
        if self.budget_of or not self.payee_of:
            return self
        return Budget.objects.get(budget_of_id=self.payee_of_id)

    def view_permission(self, user: Union[AbstractBaseUser, AnonymousUser]):
        return user.is_authenticated and user.pk == self.owner()

    def isvisible(self, other: 'Budget'):
        return ((self.owner() and self.owner() == other.owner())
                or other in self.friends.all())

    def visible_budgets(self):
        filter = Q(friends=self)
        if self.owner():
            filter |= (Q(friends__budget_of=self.owner()) |
                       Q(payee_of=self.owner()))
        return Budget.objects.filter(filter).distinct()


class Permissions:
    budget: Budget
    budgets: 'set[Budget]'

    def __init__(self, budget: Budget, budgets: 'Iterable[Budget]'):
        if not budget:
            raise ValueError('Budget is required')
        self.budget, self.budgets = budget, set(budgets)

    @functools.cached_property
    def connectivity(self):
        first = min(self.budgets, key=lambda budget: budget.id)
        rest = set(self.budgets) - {first}
        stack = [first]
        result: 'dict[Budget, Budget]' = {}
        while stack:
            budget = stack.pop()
            children = Permissions.visibility(budget, rest)
            rest -= set(children)
            stack.extend(children)
            result.update({other: budget for other in children})
        if rest:
            raise ValueError('Budgets are disconnected')
        reroot(result, self.budget)
        return result

    @functools.cached_property
    def visible(self):
        return set(Permissions.visibility(self.budget, self.budgets))

    def display_in(self, account: 'AccountT') -> 'AccountT':
        if self.budget.owner() == account.budget.owner():
            return account
        elif account.budget in self.visible:
            return account.to_inbox()
        else:
            return (self.connection(account.budget)
                    .get_inbox(type(account), account.currency))

    @staticmethod
    def visibility(budget: Budget, budgets: 'Iterable[Budget]'):
        return [other for other in budgets if other.isvisible(budget)]

    def connection(self, there: Budget):
        while there in self.connectivity:
            if self.connectivity[there] == self.budget:
                return there
            there = self.connectivity[there]
        raise ValueError('No connection')


def reroot(tree: 'dict[T, T]', node: T):
    if node in tree:
        parent = tree[node]
        del tree[node]
        while parent:
            parent2 = tree.get(parent)
            tree[parent] = node
            parent, node = parent2, parent


class BaseAccount(Id):
    """BaseAccounts describe a generic place money can be"""
    class Meta:  # type: ignore
        abstract = True
    id_ptr: models.OneToOneField[Id]
    name = models.CharField(max_length=100, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    budget_id: int  # Sigh
    balance: int
    entries: 'models.Manager[TransactionPart[Self]]'
    currency = models.CharField(max_length=5, blank=True)

    group = models.CharField(max_length=100, blank=True)
    order = models.IntegerField(default=0)
    closed = models.BooleanField(default=False)

    def kind(self) -> str:
        return ''

    @functools.cache
    def get_absolute_url(self):
        return reverse(self.kind(), kwargs={self.kind() + '_id': self.id})

    def is_inbox(self):
        return self.name == ""

    def __str__(self):
        if self.is_inbox():
            return f"{self.budget.name} ({self.currency})"
        else:
            return f"{self.budget.name} - {str(self.name)}  ({self.currency})"

    def name_for(self, user: Optional[User]):
        # This logic is duplicated in account_in_budget.html
        if self.budget.budget_of == user:
            return self.name or "Inbox"
        if isinstance(self, Category):
            return f"[{self.budget.name}]"
        return self.budget.name

    def to_inbox(self):
        if self.is_inbox():
            return self
        return self.budget.get_inbox(type(self), self.currency)


AccountT = TypeVar('AccountT', bound=BaseAccount)


class Account(BaseAccount):
    """Accounts describe the physical ownership of money."""
    id_ptr = models.OneToOneField(
        Id, related_name='of_account',
        on_delete=models.CASCADE, parent_link=True)

    def kind(self):
        return 'account'


class Category(BaseAccount):
    """Categories describe the conceptual ownership of money."""
    class Meta:  # type: ignore
        verbose_name_plural = "categories"

    id_ptr = models.OneToOneField(
        Id, related_name='of_category',
        on_delete=models.CASCADE, parent_link=True)

    def kind(self):
        return 'category'


@dataclass
class Balance:
    """A fake account representing the balance between two budgets."""
    budget: Budget
    other: Budget
    currency: str


def sum_by(input: 'Iterable[tuple[T, int]]') -> 'dict[T, int]':
    result: defaultdict[T, int] = defaultdict(int)
    for key, value in input:
        result[key] += value
    return {key: value for key, value in result.items() if value}


def valid_parts(parts: 'dict[AccountT, int]') -> bool:
    sums = sum_by((account.currency, parts[account]) for account in parts)
    return not any(sums.values())

# TODO: Consider creating a wrapper for a transaction from the perspective of
# one budget


class Transaction(models.Model):
    """A logical event involving moving money between accounts and categories"""
    id: models.BigAutoField
    date = models.DateField()
    description = models.CharField(blank=True, max_length=1000)
    accounts: 'models.ManyToManyField[Account, TransactionAccountPart]'
    account_parts: 'PartManager[Account]'
    accounts = models.ManyToManyField(
        Account, through='TransactionAccountPart',
        through_fields=('transaction', 'to'))
    categories: 'models.ManyToManyField[Category, TransactionCategoryPart]'
    category_parts: 'PartManager[Category]'
    categories = models.ManyToManyField(
        Category, through='TransactionCategoryPart',
        through_fields=('transaction', 'to'))

    class Kind(models.TextChoices):
        TRANSACTION = 'T', 'Transaction'
        BUDGETING = 'B', 'Budgeting'
    kind = models.CharField(max_length=1, choices=Kind.choices,
                            default=Kind.TRANSACTION)

    running_sum: int  # TODO this is gross, put in view logic

    def __str__(self):
        return str(self.date) + " " + self.description[0:100]

    @property
    def month(self) -> 'Optional[date]':
        return self.date and self.date.replace(day=1)

    @month.setter
    def month(self, value: 'Optional[date]'):
        self.date = value and value.replace(day=1)

    @property
    def budgets(self):
        return {part.to.budget for part
                in chain(self.account_parts.all(), self.category_parts.all())}

    def debts(self):
        owed = sum_by(chain(
            (((part.to.budget_id, part.to.currency), part.amount)
             for part in self.account_parts.all()),
            (((part.to.budget_id, part.to.currency), -part.amount)
             for part in self.category_parts.all())))
        owed = {currency: {debt[0][0]: debt[1] for debt in owed.items()
                           if debt[0][1] == currency}
                for currency in {to[1] for to in owed}}
        return combine_debts(owed)

    def visible_from(self, budget: Budget):
        return budget in self.budgets

    def parts(self, in_budget: Budget):
        permissions = Permissions(in_budget, self.budgets)
        return (self.account_parts.parts_in(permissions),
                self.category_parts.parts_in(permissions))

    def residual_parts_(self, in_budget: Budget):
        permissions = Permissions(in_budget, self.budgets)
        return (self.account_parts.residual_in(permissions),
                self.category_parts.residual_in(permissions))

    def set_parts(self, in_budget: Budget,
                  accounts: dict[Account, int], categories: dict[Category, int]):
        """Set the contents of this transaction from the perspective of one budget. 'accounts' and 'categories' both must to sum to zero."""
        if not valid_parts(accounts) or not valid_parts(categories):
            raise IntegrityError("Parts do not sum to zero")
        res_accounts, res_categories = self.residual_parts_(in_budget)
        accounts = {
            account: accounts.get(account, 0) + res_accounts.get(account, 0)
            for account in res_accounts.keys() | accounts.keys()}
        categories = {
            account: categories.get(account, 0) +
            res_categories.get(account, 0)
            for account in res_categories.keys() | categories.keys()}
        self.set_parts_raw(accounts, categories)

    def set_parts_raw(self,
                      accounts: dict[Account, int],
                      categories: dict[Category, int]):
        if not (self.account_parts.set_parts_raw(accounts) |
                self.category_parts.set_parts_raw(categories)):
            self.delete()

    def tabular(self, in_budget: Budget):
        def pop_by_(parts: 'dict[AccountT, int]',
                    currency: str, amount: int):
            try:
                result = next(part for (part, value) in parts.items()
                              if value == amount and part.currency == currency)
                del parts[result]
                return result
            except StopIteration:
                return None

        accounts, categories = self.parts(in_budget)
        amounts = sorted((account.currency, amount)
                         for account, amount
                         in chain(accounts.items(), categories.items()))
        rows: list[dict[str, Any]]
        rows = []
        for currency, amount in amounts:
            account = pop_by_(accounts, currency, amount)
            category = pop_by_(categories, currency, amount)
            if account or category:
                rows.append({'account': account, 'category': category,
                             'amount': amount})
        return rows

    def auto_description(self, in_account: BaseAccount):
        if self.kind == self.Kind.BUDGETING:
            return "Budget"
        if self.description:
            return self.description
        accounts, categories = self.parts(in_account.budget)
        names = (
            [account.name or "Inbox"
             for account in chain(accounts, categories)
             if account.budget.budget_of_id == in_account.budget.owner()
             and account != in_account] +
            list({account.budget.name
                  for account in chain(accounts, categories)
                  if account.budget.budget_of_id != in_account.budget.owner()
                  and account.budget != in_account.budget})
        )
        if len(names) > 2:
            names = names[:2] + ['...']
        return ", ".join(names)


def combine_debts(owed: 'dict[str, dict[int, int]]'):
    result: 'dict[tuple[str, int, int], int]' = {}
    for currency, debts in owed.items():
        amounts = deque(sorted((amount, budget)
                               for (budget, amount) in debts.items()
                               if amount != 0))
        amount, from_budget = 0, 0
        while amounts or amount:
            if not amount:
                amount, from_budget = amounts.popleft()
            if not amounts:
                raise ValueError("Debts do not sum to zero")
            other, to_budget = amounts.pop()
            result_amount = min(-amount, other)
            result[(currency, from_budget, to_budget)] = result_amount
            amount += other
            if amount > 0:
                amounts.append((amount, to_budget))
                amount = 0
    return result


def sum_debts(debts_1: 'dict[tuple[str, int, int], int]',
              debts_2: 'dict[tuple[str, int, int], int]'):
    keys = debts_1.keys() | debts_2.keys()
    return {key: debts_1.get(key, 0) + debts_2.get(key, 0) for key in keys}


class PartManager(Generic[AccountT],
                  models.Manager['TransactionPart[AccountT]']):
    instance: Transaction  # When used as a relatedmanager

    def parts_in(self, permissions: Permissions):
        return sum_by((permissions.display_in(part.to), part.amount)
                      for part in self.all())

    def residual_in(self, permissions: Permissions):
        """Returns a set of parts such that parts(b) + residual_parts(b) == self
        """
        result: defaultdict['AccountT', int] = defaultdict(int)
        for part in self.all():
            displayed = permissions.display_in(part.to)
            if displayed == part.to:
                result[part.to] = 0
            else:
                result[displayed] -= part.amount
                result[part.to] += part.amount
        return result

    def set_parts_raw(self, parts: dict[AccountT, int]):
        deletes = [to for to, amount in parts.items() if not amount]
        if deletes:
            self.filter(to__in=deletes).delete()
        updates = [self.model(to=to, amount=amount, transaction=self.instance)
                   for to, amount in parts.items() if amount]
        if updates:
            self.bulk_create(
                updates, update_conflicts=True,
                update_fields=['amount'],
                unique_fields=['to_id', 'transaction_id'])  # type: ignore (???)
        return bool(updates)


class TransactionPart(Generic[AccountT], models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(fields=["transaction", "to"],
                                               name="m2m_%(class)s")]
    objects: PartManager[AccountT] = PartManager()
    transaction: models.ForeignKey[Transaction]
    amount = models.BigIntegerField()
    to: models.ForeignKey[AccountT]
    to_id: int

    @classmethod
    def update_(cls, transaction: Transaction, to: BaseAccount, amount: int):
        if amount == 0:
            cls.objects.filter(transaction=transaction, to=to).delete()
        else:
            cls.objects.update_or_create(
                transaction=transaction, to=to, defaults={'amount': amount})

    def __str__(self):
        return f"{self.to} + {self.amount}"


class TransactionAccountPart(TransactionPart[Account]):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="account_parts")
    to = models.ForeignKey(Account, on_delete=models.PROTECT,
                           related_name="entries")


class TransactionCategoryPart(TransactionPart[Category]):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="category_parts")
    to = models.ForeignKey(Category, on_delete=models.PROTECT,
                           related_name="entries")


@dataclass
class TransactionDebtPart:
    """Fake transaction part representing money owed"""
    transaction: Transaction
    # to: Balance ??
    amount: int
    running_sum: int


def creates_debt():
    account_sum = (Transaction.objects.filter(id=OuterRef('id'))
                   .annotate(b=F('accounts__budget_id'),
                             value=Sum('account_parts__amount'))
                   .exclude(value=0))
    category_sum = (Transaction.objects.filter(id=OuterRef('id'))
                    .annotate(b=F('categories__budget_id'),
                              value=Sum('category_parts__amount'))
                    .exclude(value=0))
    return Exists(account_sum.difference(category_sum).union(
        category_sum.difference(account_sum)))

def months_between(start: date, end: date):
    start = start.replace(day=1)
    while start <= end:
        yield start
        start = (start + timedelta(days=31)).replace(day=1)

def transactions_with_debt(budget_id: int) -> Iterable[Transaction]:
    filter = (Q(accounts__budget_id=budget_id) |
              Q(categories__budget_id=budget_id))
    qs = (Transaction.objects
          .filter(filter, creates_debt())
          .distinct()
          .order_by('date', '-kind')
          .prefetch_related('account_parts__to__budget',
                            'category_parts__to__budget'))
    total = 0
    for transaction in qs:
        for part in transaction.category_parts.all():
            if part.to.budget_id == budget_id:
                total += part.amount
        setattr(transaction, 'running_sum', total)
    return reversed(qs)


def entries_for(account: BaseAccount) -> Iterable[TransactionPart[BaseAccount]]:
    qs = (account.entries
          .order_by('transaction__date', '-transaction__kind')
          .prefetch_related('transaction__account_parts__to__budget__friends',
                            'transaction__category_parts__to__budget__friends'))
    total = 0
    for part in qs:
        total += part.amount
        setattr(part, 'running_sum', total)
    return reversed(qs)


def entries_for_balance(account: Balance) -> Iterable[TransactionDebtPart]:
    this, other = account.budget.id, account.other.id
    filter = (Q(accounts__budget_id=this) |
              Q(categories__budget_id=other) |
              Q(accounts__budget_id=other) |
              Q(categories__budget_id=this))
    qs = (Transaction.objects
          .filter(filter, creates_debt())
          .distinct()
          .order_by('date', '-kind')
          .prefetch_related('account_parts', 'category_parts',
                            'accounts__budget', 'categories__budget'))
    result: 'list[TransactionDebtPart]' = []
    total = 0
    for transaction in qs:
        debts = transaction.debts()
        amount = (debts.get((account.currency, this, other), 0)
                  - debts.get((account.currency, other, this), 0))
        total += amount
        result.append(TransactionDebtPart(transaction, amount, total))
    return reversed(result)


def accounts_overview(budget_id: int):
    accounts = (Account.objects
                .filter(budget_id=budget_id)
                .exclude(closed=True)
                .annotate(balance=Sum('entries__amount', default=0))
                .order_by('order', 'group', 'name')
                .select_related('budget'))
    categories = (Category.objects
                  .filter(budget_id=budget_id)
                  .exclude(closed=True)
                  .annotate(balance=Sum('entries__amount', default=0))
                  .order_by('order', 'group', 'name')
                  .select_related('budget'))
    transactions = transactions_with_debt(budget_id)
    debt_map = functools.reduce(
        sum_debts, (transaction.debts() for transaction in transactions), {})
    debts = ([(currency, Budget.objects.get(id=from_budget), -amount)
              for ((currency, from_budget, to_budget), amount)
              in debt_map.items()
              if to_budget == budget_id] +
             [(currency, Budget.objects.get(id=to_budget), amount)
             for ((currency, from_budget, to_budget), amount)
             in debt_map.items()
             if from_budget == budget_id])
    return (accounts, categories, debts)


def category_history(budget_id: int):
    return (TransactionCategoryPart.objects
            .filter(to__budget_id=budget_id,
                    transaction__kind=Transaction.Kind.TRANSACTION)
            .values('to', month=Trunc(F('transaction__date'), 'month'))
            .annotate(total=Sum('amount')))


def budgeting_transactions(budget_id: int):
    return (Transaction.objects
            .filter(kind=Transaction.Kind.BUDGETING,
                    category_parts__to__budget_id=budget_id)
            .distinct())
