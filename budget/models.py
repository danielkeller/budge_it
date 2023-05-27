from typing import Optional, Iterable, TypeVar, Type, Union, Any, Self, Generic
import functools
from itertools import chain
from datetime import date, timedelta
from dataclasses import dataclass
import heapq

from django.db import models,  transaction
from django.db.models import (Q, Prefetch, Subquery, OuterRef, Value,
                              Min, Max, Sum,
                              prefetch_related_objects)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.contrib.auth.models import User, AnonymousUser, AbstractBaseUser

from .algorithms import sum_by,  reroot, double_entrify_by, Debts


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


@dataclass
class Balance:
    """A fake account representing the balance between two budgets."""
    budget: Budget
    other: Budget
    currency: str

    def get_absolute_url(self):
        return reverse('balance', kwargs={'currency': self.currency,
                                          'budget_id_1': self.budget.id,
                                          'budget_id_2': self.other.id})

    @property
    def name(self):
        return f"Owed by {self.other}"


def group_by_currency(amounts: dict[AccountT, int]):
    result: dict[str, dict[AccountT, int]] = {}
    for account, amount in amounts.items():
        result.setdefault(account.currency, {})[account] = amount
    return result.items()


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


def double_entrify(in_budget: Budget, type: Type[AccountT],
                   all_amounts: dict[AccountT, int]):
    entries: dict[tuple[AccountT, AccountT], int] = {}
    for currency, amounts in group_by_currency(all_amounts):
        amounts.setdefault(in_budget.get_inbox(type, currency), 0)
        payees = dict(item for item in amounts.items()
                      if item[0].budget.payee_of_id)
        people = dict(item for item in amounts.items()
                      if not item[0].budget.payee_of_id)

        budgets = {account.budget: account for account in people
                   if account.is_inbox()}
        tree = connectivity(list(budgets))
        reroot(tree, in_budget)
        account_tree = {budgets[child]: budgets[parent]
                        for child, parent in tree.items()}
        entries |= double_entrify_by(people, account_tree)
        debts = Debts(people.items())
        for payee, amount in payees.items():
            entries |= debts.combine_one(amount, payee)
        entries |= debts.combine()
    return entries


class TransactionManager(models.Manager['Transaction']):
    # This could possibly be done with a proxy model, which would allow eg
    # related managers to tell which budget we're looking through.
    def filter_for(self, budget: Budget):
        """Adjust and prefetch the parts of this transaction to ones visible to
        'budget'."""
        accountparts = AccountPart.objects.filter_for(budget)
        categoryparts = CategoryPart.objects.filter_for(budget)
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

    # Note that these are not filtered by `filter_for()`.
    accounts: 'models.ManyToManyField[Account, AccountPart]'
    accounts = models.ManyToManyField(Account, through='AccountPart',
                                      through_fields=('transaction', 'sink'))
    categories: 'models.ManyToManyField[Category, CategoryPart]'
    categories = models.ManyToManyField(Category, through='CategoryPart',
                                        through_fields=('transaction', 'sink'))
    accountparts: 'PartManager[Account]'
    categoryparts: 'PartManager[Category]'
    accountnotes: 'NoteManager[Account]'
    categorynotes: 'NoteManager[Category]'

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

    def set_parts(self, in_budget: Budget,
                  accounts: dict[Account, int], categories: dict[Category, int]):
        """Set the contents of this transaction from the perspective of one budget. 'accounts' and 'categories' both must to sum to zero."""
        self.set_parts_raw(double_entrify(in_budget, Account, accounts),
                           double_entrify(in_budget, Category, categories))

    def parts(self):
        return (self.accountparts.parts(), self.categoryparts.parts())

    def entries(self):
        return (self.accountparts.entries(), self.categoryparts.entries())

    @transaction.atomic
    def set_parts_raw(self,
                      accounts: dict[tuple[Account, Account], int],
                      categories: dict[tuple[Category, Category], int]):
        self.accountparts.set_parts(accounts)
        self.categoryparts.set_parts(categories)
        if (not AccountPart.objects.filter(transaction=self).exists() and
                not CategoryPart.objects.filter(transaction=self).exists()):
            self.delete()

    @dataclass
    class Row:
        account: Optional[Account]
        category: Optional[Category]
        amount: int
        note: str

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

        account_notes: dict[int | None, str]
        account_notes = {note.account_id: note.note
                         for note in self.accountnotes.all()}
        category_notes: dict[int | None, str]
        category_notes = {note.account_id: note.note
                          for note in self.categorynotes.all()}

        accounts = self.accountparts.entries()
        categories = self.categoryparts.entries()
        amounts = sorted((account.currency, amount)
                         for account, amount
                         in chain(accounts.items(), categories.items()))
        rows: list[Transaction.Row]
        rows = []
        for currency, amount in amounts:
            account = pop_by_(accounts, currency, amount)
            category = pop_by_(categories, currency, amount)
            note = category_notes.get(category and category.id,
                                      account_notes.get(account and account.id,
                                                        ''))
            if account or category:
                rows.append(Transaction.Row(account, category, amount, note))
        return rows

    def auto_description(self, in_account: BaseAccount | Balance):
        if self.kind == self.Kind.BUDGETING:
            return "Budget"
        accounts = self.accountparts.entries()
        categories = self.categoryparts.entries()
        if isinstance(in_account, BaseAccount):
            this_budget = in_account.budget
        else:
            this_budget = in_account.other
        names = (
            [account.name or "Inbox"
             for account in chain(accounts, categories)
             if account.budget.budget_of_id == in_account.budget.owner()
             and account != in_account] +
            list({account.budget.name
                  for account in chain(accounts, categories)
                  if account.budget.budget_of_id != in_account.budget.owner()
                  and account.budget != this_budget})
        )
        if len(names) > 2:
            names = names[:2] + ['...']
        return ", ".join(names)


class PartManager(Generic[AccountT],
                  models.Manager['TransactionPart[AccountT]']):
    # This could be a generic arg actually...
    instance: Transaction  # When used as a relatedmanager

    def filter_for(self, budget: Budget):
        """Filter parts to ones visible to 'budget'."""
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
        # no distinct?
        return (self.filter(source_visible, sink_visible)
                .select_related('sink__budget'))

    def entries(self) -> dict[AccountT, int]:
        return sum_by((part.sink, part.amount) for part in self.all())

    def parts(self):
        return {(part.source, part.sink): part.amount
                for part in self.all() if part.amount > 0}

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

    @ property
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


class NoteManager(Generic[AccountT],
                  models.Manager['TransactionNote[AccountT]']):
    instance: Transaction  # When used as a relatedmanager

    def set_notes(self, user_id: int, notes: dict[AccountT, str]):
        # 'self' is already filtered for a user, we just can't see which one
        # Does this call the database if the prefetch is empty?
        self.all().delete()
        updates = [self.model(account=account, note=note, user_id=user_id,
                              transaction=self.instance)
                   for account, note in notes.items()]
        if updates:
            self.bulk_create(
                updates, update_conflicts=True,
                update_fields=['note'],
                unique_fields=[  # type: ignore
                    'account_id', 'user_id', 'transaction_id'])


class TransactionNote(Generic[AccountT], models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(
            fields=["transaction", "account", "user"], name="m2m_%(class)s")]
    objects = NoteManager[AccountT]()
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="%(class)ss")
    account: models.ForeignKey[AccountT]
    account_id: int
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    note = models.CharField(max_length=100)


class AccountNote(TransactionNote[Account]):
    account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                related_name="notes")


class CategoryNote(TransactionNote[Category]):
    account = models.ForeignKey(Category, on_delete=models.PROTECT,
                                related_name="notes")


@ dataclass
class TransactionDebtPart:
    """Fake transaction part representing money owed"""
    transaction: Transaction
    # to: Balance ??
    amount: int
    running_sum: int


def months_between(start: date, end: date):
    start = start.replace(day=1)
    while start <= end:
        yield start
        start = (start + timedelta(days=31)).replace(day=1)


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


def entries_for_balance(account: Balance) -> Iterable[Transaction]:
    gets = (CategoryPart.objects
            .filter(transaction=OuterRef('pk'),
                    source__currency=account.currency,
                    source__budget=account.other, sink__budget=account.budget)
            .values('transaction')
            .values(sum=Sum('amount')))
    has = (AccountPart.objects
           .filter(transaction=OuterRef('pk'),
                   source__currency=account.currency,
                   source__budget=account.other, sink__budget=account.budget)
           .values('transaction')
           .values(sum=Sum('amount')))
    qs = (Transaction.objects
          .filter_for(account.budget)
          .annotate(change=Coalesce(Subquery(gets), 0)
                    - Coalesce(Subquery(has), 0))
          .exclude(change=0)
          .order_by('date', '-kind'))
    total = 0
    for transaction in qs:
        total += getattr(transaction, 'change')
        setattr(transaction, 'running_sum', total)
    return reversed(qs)


def accounts_overview(budget: Budget):
    accounts = (Account.objects
                .filter(budget=budget)
                .exclude(closed=True)
                .annotate(balance=Sum('entries__amount', default=0))
                .order_by('order', 'group', 'name')
                .select_related('budget'))
    categories = (Category.objects
                  .filter(budget=budget)
                  .exclude(closed=True)
                  .annotate(balance=Sum('entries__amount', default=0))
                  .order_by('order', 'group', 'name')
                  .select_related('budget'))
    currencies = {*budget.account_set.values_list('currency').distinct(),
                  *budget.category_set.values_list('currency').distinct()}
    gets = (CategoryPart.objects
            .filter(source__currency=OuterRef('currency'),
                    source__budget=OuterRef('pk'),
                    sink__budget=budget)
            .values('source__budget')
            .values(sum=Sum('amount')))
    has = (AccountPart.objects
           .filter(source__currency=OuterRef('currency'),
                   source__budget=OuterRef('pk'),
                   sink__budget=budget)
           .values('source__budget')
           .values(sum=Sum('amount')))
    debts = chain.from_iterable(
        Budget.objects
        .annotate(currency=Value(currency),
                  balance=Coalesce(Subquery(gets), 0)
                  - Coalesce(Subquery(has), 0))
        .exclude(balance=0)
        for currency, in currencies)
    return (accounts, categories, debts)


def category_balance(budget: Budget, start: date):
    end = (start + timedelta(days=31)).replace(day=1)
    # TODO: Show closed categories if you look before they were closed
    before = (Category.objects
              .filter(budget=budget, closed=False)
              .annotate(balance=Sum('entries__amount',
                                    filter=Q(entries__transaction__date__lt=start), default=0))
              .order_by('order', 'group', 'name')
              .select_related('budget'))
    during = (Category.objects
              .filter(budget=budget, closed=False,
                      entries__transaction__kind=Transaction.Kind.TRANSACTION,
                      entries__transaction__date__gte=start,
                      entries__transaction__date__lt=end)
              .annotate(balance=Sum('entries__amount', default=0)))
    return (before, during)


def budgeting_transaction(budget: Budget, date: date):
    return (Transaction.objects
            .filter(kind=Transaction.Kind.BUDGETING, date=date,
                    categories__budget=budget)
            .first())


def date_range(budget: Budget) -> tuple[date, date]:
    range = (Transaction.objects
             .filter(categories__budget=budget)
             .aggregate(Max('date', default=date.today()),
                        Min('date', default=date.today())))
    return (min(range['date__min'], date.today()),
            max(range['date__max'], date.today()))
