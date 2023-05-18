from typing import Optional, Iterable, TypeVar, Type, Union, Any, Self, Generic
from collections import defaultdict, deque
import functools
from itertools import chain
from datetime import date, timedelta
from dataclasses import dataclass
import heapq

from django.db import models, IntegrityError, transaction
from django.db.models import (Q, Sum, F, OuterRef, Prefetch, Exists,
                              prefetch_related_objects)
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
    budgetfriends_set: 'models.Manager[BudgetFriends]'
    friends: 'models.ManyToManyField[Budget, BudgetFriends]'
    friends = models.ManyToManyField(
        'self', through='BudgetFriends', blank=True)

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


class BudgetFriends(models.Model):
    class Meta:  # type: ignore
        constraints = [
            models.UniqueConstraint(fields=["from_budget", "to_budget"],
                                    name="m2m_%(class)s")]
    id: int
    from_budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    to_budget = models.ForeignKey(Budget, on_delete=models.CASCADE,
                                  related_name="+")

    def __str__(self):
        return f"{self.from_budget} -> {self.to_budget}"


class BaseAccount(Id):
    """BaseAccounts describe a generic place money can be"""
    class Meta:  # type: ignore
        abstract = True
    id_ptr: models.OneToOneField[Id]
    name = models.CharField(max_length=100, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    budget_id: int  # Sigh
    balance: int
    source_entries: 'models.Manager[TransactionPart[Self]]'
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

    def __lt__(self, other: Self):
        """Not actually important"""
        return self.id < other.id


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


# @dataclass
# class Balance:
#     """A fake account representing the balance between two budgets."""
#     budget: Budget
#     other: Budget
#     currency: str


def sum_by(input: 'Iterable[tuple[T, int]]') -> 'dict[T, int]':
    result: defaultdict[T, int] = defaultdict(int)
    for key, value in input:
        result[key] += value
    return {key: value for key, value in result.items() if value}


def double_entrify_auto(amounts: dict[AccountT, int]
                        ) -> dict[tuple[AccountT, AccountT], int]:
    currencies = {amount.currency for amount in amounts}
    return combine_debts({account: amount
                          for account, amount in amounts.items()
                          if account.currency == currency}
                         for currency in currencies)


def combine_debts(owed: Iterable[dict[T, int]]) -> dict[tuple[T, T], int]:
    result: dict[tuple[T, T], int] = {}
    for debts in owed:
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


def connectivity(budgets: list[Budget]) -> dict[Budget, Budget]:
    first = min(budgets, key=lambda budget: budget.id)
    rest = set(budgets) - {first}
    result: 'dict[Budget, Budget]' = {}
    prefetch_related_objects(budgets, 'budgetfriends_set')
    queue: list[tuple[int, Budget, Budget]] = []
    for friend in first.budgetfriends_set.all():
        heapq.heappush(
            queue, (friend.id, friend.from_budget, friend.to_budget))
    while queue:
        _, from_budget, to_budget = heapq.heappop(queue)
        if to_budget in rest:
            rest.remove(to_budget)
            result[to_budget] = from_budget
            for friend in to_budget.budgetfriends_set.all():
                heapq.heappush(queue, (friend.id,
                                       friend.from_budget, friend.to_budget))
    if rest:
        raise ValueError('Budgets are disconnected')
    return result


def reroot(tree: 'dict[T, T]', node: T):
    if node in tree:
        parent = tree[node]
        del tree[node]
        while parent:
            parent2 = tree.get(parent)
            tree[parent] = node
            parent, node = parent2, parent


def double_entrify_by(amounts: dict[AccountT, int],
                      budget_tree: dict[Budget, Budget]):
    result: dict[tuple[AccountT, AccountT], int] = {}
    budget_account = {(account.currency, account.budget): account
                      for account in amounts
                      if account.is_inbox()}
    tree = {account: budget_account[currency, budget_tree[budget]]
            for ((currency, budget), account) in budget_account.items()
            if budget in budget_tree}
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


def double_entrify(in_budget: Budget,
                   accounts: dict[Account, int], categories: dict[Category, int]):
    budgets = {account.budget for account in chain(accounts, categories)
               if account.budget in in_budget.friends.all()} | {in_budget}
    tree = connectivity(list(budgets))
    reroot(tree, in_budget)
    for currency in {account.currency for account in chain(accounts, categories)}:
        accounts.setdefault(in_budget.get_inbox(Account, currency), 0)
        categories.setdefault(in_budget.get_inbox(Category, currency), 0)
    account_entries = double_entrify_by(accounts, tree)
    account_entries |= double_entrify_auto(accounts)
    category_entries = double_entrify_by(categories, tree)
    category_entries |= double_entrify_auto(categories)
    return account_entries, category_entries


class TransactionManager(models.Manager['Transaction']):
    def filter_for(self, budget: Budget):
        """Adjust and prefetch the parts of this transaction to ones visible to
        'budget'."""
        source_visible = Q(source__budget=budget) | (
            Q(source__name="") & (
                Q(source__budget__budget_of_id=budget.owner())
                | Q(source__budget__payee_of_id=budget.owner())
                | Q(source__budget__friends=budget)))
        sink_visible = Q(sink__budget=budget) | (
            Q(sink__name="") & (
                Q(sink__budget__budget_of_id=budget.owner())
                | Q(sink__budget__payee_of_id=budget.owner())
                | Q(sink__budget__friends=budget)))

        accountparts = (AccountPart.objects
                        .filter(source_visible, sink_visible)
                        .select_related('sink__budget'))
        categoryparts = (CategoryPart.objects
                         .filter(source_visible, sink_visible)
                         .select_related('sink__budget'))
        accountnotes = AccountNote.objects.filter(user=budget.owner())
        categorynotes = CategoryNote.objects.filter(user=budget.owner())
        return self.prefetch_related(
            Prefetch('accountparts', queryset=accountparts),
            Prefetch('categoryparts', queryset=categoryparts),
            Prefetch('accountnotes', queryset=accountnotes),
            Prefetch('categorynotes', queryset=categorynotes),
        )

    def get_for(self, budget: Budget, id: int):
        try:
            value = self.filter_for(budget).get(id=id)
        except self.model.DoesNotExist:
            return None
        if not value.accountparts and not value.categoryparts:
            return None
        return value


class Transaction(models.Model):
    """A logical event involving moving money between accounts and categories"""
    id: models.BigAutoField
    date = models.DateField()

    accounts: 'models.ManyToManyField[Account, AccountPart]'
    accounts = models.ManyToManyField(Account, through='AccountPart',
                                      through_fields=('transaction', 'sink'))
    categories: 'models.ManyToManyField[Category, CategoryPart]'
    categories = models.ManyToManyField(Category, through='CategoryPart',
                                        through_fields=('transaction', 'sink'))
    accountparts: 'PartManager[Account]'
    categoryparts: 'PartManager[Category]'
    accountnotes: 'models.Manager[AccountNote]'
    categorynotes: 'models.Manager[CategoryNote]'

    objects = TransactionManager()

    class Kind(models.TextChoices):
        TRANSACTION = 'T', 'Transaction'
        BUDGETING = 'B', 'Budgeting'
    kind = models.CharField(max_length=1, choices=Kind.choices,
                            default=Kind.TRANSACTION)

    running_sum: int  # TODO this is gross, put in view logic

    def __str__(self):
        return str(self.date)

    @property
    def month(self) -> 'Optional[date]':
        return self.date and self.date.replace(day=1)

    @month.setter
    def month(self, value: 'Optional[date]'):
        self.date = value and value.replace(day=1)

    # @property
    # def budgets(self):
    #     return {account.budget for part
    #             in chain(self.accountparts.all(), self.categoryparts.all())
    #             for account in part.accounts}

    # def debts(self):
    #     owed = sum_by(chain(
    #         (((part.to.budget_id, part.to.currency), part.amount)
    #          for part in self.account_parts.all()),
    #         (((part.to.budget_id, part.to.currency), -part.amount)
    #          for part in self.category_parts.all())))
    #     owed = {currency: {debt[0][0]: debt[1] for debt in owed.items()
    #                        if debt[0][1] == currency}
    #             for currency in {to[1] for to in owed}}
    #     return combine_debts(owed)

    # def visible_from(self, budget: Budget):
    #     return budget in self.budgets

    # def parts(self, in_budget: Budget):
    #     return (self.account_parts.parts_in(in_budget),
    #             self.category_parts.parts_in(in_budget))

    def set_parts(self, in_budget: Budget,
                  accounts: dict[Account, int], categories: dict[Category, int]):
        """Set the contents of this transaction from the perspective of one budget. 'accounts' and 'categories' both must to sum to zero."""
        self.set_parts_raw(*double_entrify(in_budget, accounts, categories))

    @transaction.atomic
    def set_parts_raw(self,
                      accounts: dict[tuple[Account, Account], int],
                      categories: dict[tuple[Category, Category], int]):
        self.accountparts.set_parts(accounts)
        self.categoryparts.set_parts(categories)
        if (not AccountPart.objects.filter(transaction=self).exists() and
                not CategoryPart.objects.filter(transaction=self).exists()):
            self.delete()

    def tabular(self):
        def pop_by_(parts: 'dict[AccountT, int]',
                    currency: str, amount: int):
            try:
                result = next(part for (part, value) in parts.items()
                              if value == amount and part.currency == currency)
                del parts[result]
                return result
            except StopIteration:
                return None

        accounts = self.accountparts.entries()
        categories = self.categoryparts.entries()
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
        accounts = self.accountparts.entries()
        categories = self.categoryparts.entries()
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


class PartManager(Generic[AccountT],
                  models.Manager['TransactionPart[AccountT]']):
    instance: Transaction  # When used as a relatedmanager

    def entries(self) -> dict[AccountT, int]:
        return sum_by((part.sink, part.amount) for part in self.distinct())

    def set_parts(self, parts: dict[tuple[AccountT, AccountT], int]):
        self.all().delete()
        updates = chain.from_iterable(
            (self.model(source=source, sink=sink, amount=amount,
                        transaction=self.instance),
             self.model(source=sink, sink=source, amount=-amount,
                        transaction=self.instance))
            for (source, sink), amount in parts.items() if amount)
        if updates:
            self.bulk_create(
                updates, update_conflicts=True,
                update_fields=['amount'],
                unique_fields=[  # type: ignore (???)
                    'source_id', 'sink_id', 'transaction_id'])


class TransactionPart(Generic[AccountT], models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(
            fields=["transaction", "source", "sink"], name="m2m_%(class)s")]
    objects: PartManager[AccountT] = PartManager()
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="%(class)ss")
    source: models.ForeignKey[AccountT]
    source_id: int
    sink: models.ForeignKey[AccountT]
    sink_id: int

    amount = models.BigIntegerField()

    @property
    def accounts(self):
        return (self.source, self.sink)

    def __str__(self):
        return f"{self.source} -> {self.sink}: {self.amount}"


class AccountPart(TransactionPart[Account]):
    source = models.ForeignKey(Account, on_delete=models.PROTECT,
                               related_name="source_entries")  # make nameless?
    sink = models.ForeignKey(Account, on_delete=models.PROTECT,
                             related_name="entries")


class CategoryPart(TransactionPart[Category]):
    source = models.ForeignKey(Category, on_delete=models.PROTECT,
                               related_name="source_entries")
    sink = models.ForeignKey(Category, on_delete=models.PROTECT,
                             related_name="entries")


class TransactionNote(Generic[AccountT], models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(
            fields=["transaction", "account", "user"], name="m2m_%(class)s")]
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="%(class)ss")
    account: models.ForeignKey[AccountT]
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    note = models.CharField(max_length=100)


class AccountNote(TransactionNote[Account]):
    account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                related_name="notes")


class CategoryNote(TransactionNote[Category]):
    account = models.ForeignKey(Category, on_delete=models.PROTECT,
                                related_name="notes")


@dataclass
class TransactionDebtPart:
    """Fake transaction part representing money owed"""
    transaction: Transaction
    # to: Balance ??
    amount: int
    running_sum: int


# def creates_debt():
#     account_sum = (Transaction.objects.filter(id=OuterRef('id'))
#                    .annotate(b=F('accounts__budget_id'),
#                              value=Sum('account_parts__amount'))
#                    .exclude(value=0))
#     category_sum = (Transaction.objects.filter(id=OuterRef('id'))
#                     .annotate(b=F('categories__budget_id'),
#                               value=Sum('category_parts__amount'))
#                     .exclude(value=0))
#     return Exists(account_sum.difference(category_sum).union(
#         category_sum.difference(account_sum)))

def months_between(start: date, end: date):
    start = start.replace(day=1)
    while start <= end:
        yield start
        start = (start + timedelta(days=31)).replace(day=1)

# def transactions_with_debt(budget_id: int) -> Iterable[Transaction]:
#     filter = (Q(accounts__budget_id=budget_id) |
#               Q(categories__budget_id=budget_id))
#     qs = (Transaction.objects
#           .filter(filter, creates_debt())
#           .distinct()
#           .order_by('date', '-kind')
#           .prefetch_related('account_parts__to__budget',
#                             'category_parts__to__budget'))
#     total = 0
#     for transaction in qs:
#         for part in transaction.category_parts.all():
#             if part.to.budget_id == budget_id:
#                 total += part.amount
#         setattr(transaction, 'running_sum', total)
#     return reversed(qs)


def entries_for(account: BaseAccount) -> Iterable[Transaction]:
    if isinstance(account, Account):  # gross
        filter, amount = 'accounts', 'accountparts__amount'
    else:
        filter, amount = 'categories', 'categoryparts__amount'

    qs = (Transaction.objects
          .filter_for(account.budget).filter(**{filter: account})
          .annotate(change=Sum(amount)).exclude(change=0)
          .order_by('date', '-kind'))
    total = 0
    for transaction in qs:
        total += getattr(transaction, 'change')
        setattr(transaction, 'running_sum', total)
    return reversed(qs)


# def entries_for_balance(account: Balance) -> Iterable[TransactionDebtPart]:
#     this, other = account.budget.id, account.other.id
#     filter = (Q(accounts__budget_id=this) |
#               Q(categories__budget_id=other) |
#               Q(accounts__budget_id=other) |
#               Q(categories__budget_id=this))
#     qs = (Transaction.objects
#           .filter(filter, creates_debt())
#           .distinct()
#           .order_by('date', '-kind')
#           .prefetch_related('account_parts', 'category_parts',
#                             'accounts__budget', 'categories__budget'))
#     result: 'list[TransactionDebtPart]' = []
#     total = 0
#     for transaction in qs:
#         debts = transaction.debts()
#         amount = (debts.get((account.currency, this, other), 0)
#                   - debts.get((account.currency, other, this), 0))
#         total += amount
#         result.append(TransactionDebtPart(transaction, amount, total))
#     return reversed(result)


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
    category = (Budget.objects
                .filter(category__entries__source__budget_id=budget_id)
                .annotate(currency=F('category__currency'),
                          balance=-Sum('category__entries__amount'))
                .exclude(balance=0))
    account = (Budget.objects
               .filter(account__entries__source__budget_id=budget_id)
               .annotate(currency=F('account__currency'),
                         balance=-Sum('account__entries__amount'))
               .exclude(balance=0))
    debts = account.difference(category).union(category.difference(account))
    return (accounts, categories, debts)


# def category_history(budget_id: int):
#     return (CategoryPart.objects
#             .filter(to__budget_id=budget_id,
#                     transaction__kind=Transaction.Kind.TRANSACTION)
#             .values('to', month=Trunc(F('transaction__date'), 'month'))
#             .annotate(total=Sum('amount')))


# def budgeting_transactions(budget_id: int):
#     return (Transaction.objects
#             .filter(kind=Transaction.Kind.BUDGETING,
#                     category_parts__to__budget_id=budget_id)
#             .distinct())
