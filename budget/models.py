from .recurrence import RRule
from . import recurrence
from .algorithms import sum_by, merge, reroot, double_entrify_by, Debts
from collections import defaultdict
from typing import (Optional, Iterable, TypeVar, Type, Union, Generic,
                    Any, ClassVar, Literal, Collection)
import functools
from itertools import chain, islice
from datetime import date, timedelta
from dataclasses import dataclass
import heapq

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django import forms
from django.db.transaction import atomic
from django.db.models import (Q, F, Prefetch, Subquery, OuterRef, Value, Case, When,
                              Min, Max, Sum, Count, Exists, FilteredRelation, expressions,
                              prefetch_related_objects, aggregates)
from django.db.models.functions import Coalesce, NullIf
from django.urls import reverse
from django.contrib.auth.models import User, AnonymousUser, AbstractBaseUser

TYPE_CHECKING = False
if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager


class JsonArray(expressions.Func):
    output_field = models.JSONField()  # type: ignore

    def as_sqlite(self, *args, **kwargs):
        return super().as_sql(*args, function='JSON_ARRAY', **kwargs)

    def as_postgresql(self, *args, **kwargs):
        return super().as_sql(*args, function='JSONB_BUILD_ARRAY', **kwargs)


class JsonAgg(aggregates.Aggregate):
    # function = 'JSON_GROUP_ARRAY'
    allow_distinct = True
    output_field = models.JSONField()  # type: ignore

    def as_sqlite(self, *args, **kwargs):
        return super().as_sql(*args, function='JSON_GROUP_ARRAY', **kwargs)

    def as_postgresql(self, *args, **kwargs):
        return super().as_sql(*args, function='JSONB_AGG', **kwargs)


class Id(models.Model):
    """Distinct identity for budgets, accounts, and categories"""
    id: models.BigAutoField
    of_budget: 'models.OneToOneField[Budget]'
    of_account: 'models.OneToOneField[Account]'
    of_category: 'models.OneToOneField[Category]'
    def kind(self) -> str: ...  # pragma: no cover


class Budget(Id):
    class Meta:  # type: ignore
        constraints = [models.CheckConstraint(
            check=Q(budget_of__isnull=True) | Q(payee_of__isnull=True),
            name="cant_be_payee_and_budget")]
        # Payees have distinct names?

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

    # Remove?
    initial_currency = models.CharField(max_length=16, blank=True)
    initial_split = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.name

    def kind(self):
        return 'budget'

    @functools.cache
    def get_absolute_url(self):
        return reverse('all', args=(self.id,))

    def get_inbox(self, cls: 'Type[AccountT]', currency: str) -> 'AccountT':
        # Caching this doesn't work well with rollbacks
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

    @functools.cached_property
    def currencies(self) -> Iterable[str]:
        return (self.category_set
                .filter(name='')
                .values_list('currency', flat=True)
                .order_by('order'))

    def get_initial_currency(self):
        for currency in self.currencies:
            return currency
        else:
            return 'CHF'

    @property
    def budget(self):
        """Quack like an account if needed"""
        return self


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
        constraints = [models.UniqueConstraint(
            fields=["budget", "name", "currency"], name="m2m_%(class)s")]
    id_ptr: models.OneToOneField[Id]
    name = models.CharField(max_length=100, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    budget_id: int  # Sigh
    balance: int
    source_entries: 'models.Manager[Entry[BaseAccount]]'
    transactionpart_set: 'models.Manager[TransactionPart]'
    entries: 'models.Manager[Entry[BaseAccount]]'
    currency = models.CharField(max_length=16)

    group = models.CharField(max_length=100, blank=True)
    order = models.IntegerField(default=0)
    closed = models.BooleanField(default=False)

    def kind_name(self) -> str: ...  # pragma: no cover
    @property
    def clearable(self) -> bool: return False

    class DoesNotExist(ObjectDoesNotExist):
        pass

    @staticmethod
    def get(id: int):
        try:
            return Account.objects.get(id=id)
        except Account.DoesNotExist:
            try:
                return Category.objects.get(id=id)
            except Category.DoesNotExist:
                raise BaseAccount.DoesNotExist()

    @functools.cache
    def get_absolute_url(self):
        return reverse('all', args=(self.budget_id, self.id))

    def is_inbox(self):
        return self.name == ""

    def __str__(self):
        if self.is_inbox():
            return f"{self.budget.name} ({self.currency})"
        else:
            return f"{self.budget.name} - {str(self.name)}  ({self.currency})"

    def description(self, in_budget: Budget):
        if self.name:
            return self.name
        if self.budget == in_budget:
            return 'Inbox'
        return self.budget.name

    def __lt__(self, other: 'BaseAccount'):
        """Not actually important"""
        return self.id < other.id

    def transactions(self) -> tuple[list['Transaction'], int, int]:
        if isinstance(self, Account):  # gross
            field, amount = 'parts__accounts', 'parts__accountentry_set__amount'
        else:
            field, amount = 'parts__categories', 'parts__categoryentry_set__amount'

        if not self.is_inbox():
            inbox = self.budget.get_inbox(type(self), self.currency).id
        else:
            inbox = None

        qs = (Transaction.objects
              .filter(Q(**{field: self}) |
                      (Q(**{field: inbox}) & ~Q(kind=Transaction.Kind.BUDGETING)))
              .annotate(account=F(field), change=Sum(amount)).exclude(change=0)
              .annotate(cleared_self=FilteredRelation('cleared',
                                                      condition=Q(cleared__account_id=self.id)),
                        reconciled=F('cleared_self__reconciled'))
              .fetch_contents()
              .order_by('date', '-kind', 'id'))
        fetch_accounts(qs, self.budget)

        if sum(transaction.do_recurrence() for transaction in set(qs)):
            return self.transactions()  # Retry

        balance, cleared = 0, 0
        for transaction in qs:
            if transaction.account == inbox:
                transaction.is_inbox = True
            elif self.clearable and transaction.reconciled is None:
                transaction.uncleared = True
                transaction.running_sum = ''
            else:
                cleared += transaction.change
                transaction.running_sum = cleared
            if transaction.date and transaction.date > date.today():
                transaction.is_future = True
            elif not hasattr(transaction, 'is_inbox'):
                balance += transaction.change
        return list(reversed(qs)), balance, cleared


AccountT = TypeVar('AccountT', bound=BaseAccount)


class Account(BaseAccount):
    """Accounts describe the physical ownership of money."""
    id_ptr = models.OneToOneField(
        Id, related_name='of_account',
        on_delete=models.CASCADE, parent_link=True)

    clearable = models.BooleanField(default=False)  # type: ignore
    cleared: 'RelatedManager[Cleared]'
    cleared_transaction: 'models.ManyToManyField[Transaction, Cleared]'

    def kind(self):
        return 'account'

    def kind_name(self):
        return 'Account'


class Category(BaseAccount):
    """Categories describe the conceptual ownership of money."""
    class Meta:  # type: ignore
        verbose_name_plural = "categories"
        constraints = BaseAccount.Meta.constraints

    id_ptr = models.OneToOneField(
        Id, related_name='of_category',
        on_delete=models.CASCADE, parent_link=True)

    change: int

    def kind(self):
        return 'category'

    def kind_name(self):
        return 'Category'


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

    @property
    def id(self):
        # Templates/urls refer to it this way
        return f'owed-{self.currency}-{self.other.id}'

    def transactions(self) -> tuple[list['Transaction'], int, int]:
        has = dict(AccountEntry.objects
                   .filter(sink__budget=self.budget.id, source__budget_id=self.other.id,
                           sink__currency=self.currency)
                   .values('part__transaction')
                   .values_list('part__transaction', Sum('amount')))
        gets = dict(CategoryEntry.objects
                    .filter(sink__budget=self.budget.id, source__budget_id=self.other.id,
                            sink__currency=self.currency)
                    .values('part__transaction')
                    .values_list('part__transaction', Sum('amount')))
        qs = (Transaction.objects
              .filter(id__in=gets.keys() | has.keys())
              .fetch_contents()
              .order_by('date', '-kind', 'id'))
        fetch_accounts(qs, self.budget)

        if sum(transaction.do_recurrence() for transaction in set(qs)):
            return self.transactions()  # Retry

        total, balance = 0, 0
        for transaction in qs:
            change = gets.get(transaction.id, 0) - has.get(transaction.id, 0)
            total += change
            transaction.change = change
            transaction.running_sum = total
            if transaction.date and transaction.date > date.today():
                transaction.is_future = True
            else:
                balance += transaction.change
        return list(reversed(qs)), balance, 0


@dataclass
class Total:
    """A fake account representing everything in a currency."""
    budget: Budget
    currency: str
    balance: int | None = None

    @property
    def name(self):
        return self.budget.name

    @property
    def id(self):
        # Templates/urls refer to it this way
        return 'all-' + self.currency

    def transactions(self) -> tuple[Iterable['Transaction'], int, int]:
        # TODO: Do we want to include budgets and transfers here?
        qs = (Transaction.objects
              .filter(parts__categories__currency=self.currency,
                      parts__categories__budget=self.budget)
              .annotate(change=Sum('parts__categoryentry_set__amount'))
              .exclude(change=0)
              .fetch_contents()
              .order_by('date', '-kind', 'id'))
        fetch_accounts(qs, self.budget)

        if sum(transaction.do_recurrence() for transaction in set(qs)):
            return self.transactions()  # Retry

        total, balance = 0, 0
        for transaction in qs:
            total += transaction.change
            transaction.running_sum = total
            if transaction.date and transaction.date > date.today():
                transaction.is_future = True
            else:
                balance += transaction.change
        return list(reversed(qs)), balance, 0


AccountLike = BaseAccount | Account | Category | Total | Balance


def group_by_currency(amounts: dict[AccountT, int]):
    result: dict[str, dict[AccountT, int]] = {}
    for account, amount in amounts.items():
        result.setdefault(account.currency, {})[account] = amount
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


def double_entrify(in_budget: Budget, type: Type[AccountT],
                   all_amounts: dict[AccountT, int]):
    entries: dict[tuple[AccountT, AccountT], int] = {}
    for currency, amounts in group_by_currency(all_amounts).items():
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
    # This is kind of silly, maybe rethink.
    return list(chain(*(
        ((source, sink, amount), (sink, source, -amount))
        for (source, sink), amount in entries.items()
    )))


class TransactionQuerySet(models.QuerySet['Transaction']):
    def fetch_contents(self):
        """Annotate with notes and account ids using a subquery."""
        def accounts(type: Type[BaseAccount]):
            return Subquery(
                type.objects
                .filter(entries__part=OuterRef('pk'))
                .values('entries__part')
                .annotate(json=JsonAgg(JsonArray(
                    'entries__source_id', 'id', 'entries__amount')))
                .values('json'))
        # TODO: Cleared
        contents = (
            TransactionPart.objects
            .filter(transaction=OuterRef('pk'))
            .values('transaction')
            .annotate(json=JsonAgg(JsonArray('id', 'note', accounts(Account), accounts(Category))))
            .values('json'))
        return self.annotate(contents=contents)

    def get_for(self, budget: Budget, id: int):
        try:
            value = self.fetch_contents().get(id=id)
            fetch_accounts([value], budget)
        except self.model.DoesNotExist:
            return None
        if not value.visible():
            return None
        return value

    def get_for_multi(self, budget: Budget, ids: Iterable[int]):
        values = list(self.filter(id__in=ids).fetch_contents())
        fetch_accounts(values, budget)
        values = [value for value in values if value.visible()]
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        return MultiTransaction(contents=values)


def account_dict(accounts: Iterable[AccountT]):
    return {account.id: account for account in accounts}

# Can I reuse this logic to populate the accounts in the other direction,
# when we save something?


def fetch_accounts(transactions: Iterable['Transaction'], budget: Budget):
    """To be called after fetch_contents on the queryset."""
    local_accounts = account_dict(budget.account_set.all())
    local_categories = account_dict(budget.category_set.all())
    other_accounts = account_dict(
        Account.objects
        .filter(Q(budget__payee_of=budget.budget_of_id)
                | Q(budget__friends=budget), name='')
        .select_related('budget'))
    other_categories = account_dict(
        Category.objects
        .filter(Q(budget__payee_of=budget.budget_of_id)
                | Q(budget__friends=budget), name='')
        .select_related('budget'))

    def to_flows(json: list[tuple[int, int, int]],
                 accounts: dict[int, AccountT],
                 type: Type[AccountT]):
        # Flow visibility: Can see both source and sink
        visible = [(accounts[source], accounts[sink], amount)
                   for source, sink, amount in json
                   if source in accounts and sink in accounts]
        invisible = [(type(pk=source), type(pk=sink), amount)
                     for source, sink, amount in json
                     if source not in accounts or sink not in accounts]
        return (visible, invisible)

    def to_part(
            transaction: Transaction,
            json: tuple[int, str,
                        list[tuple[int, int, int]],
                        list[tuple[int, int, int]]]):
        part = TransactionPart(
            id=json[0], note=json[1], transaction=transaction)
        part.visible_accounts, part.invisible_accounts = to_flows(
            json[2] or [], local_accounts | other_accounts, Account)
        part.visible_categories, part.invisible_categories = to_flows(
            json[3] or [], local_categories | other_categories, Category)
        return part

    def is_visible(part: TransactionPart):
        # Part visibility: At least one own account
        return (any(sink.id in local_accounts
                    for _, sink, _ in part.visible_accounts)
                or any(sink.id in local_categories
                       for _, sink, _ in part.visible_categories))

    for transaction in transactions:
        parts = [to_part(transaction, json) for json in transaction.contents]
        parts.sort(key=lambda part: part.id)
        transaction.visible_parts = [
            part for part in parts if is_visible(part)]
        transaction.invisible_parts = [
            part for part in parts if not is_visible(part)]


if TYPE_CHECKING:  # stupid thing
    RRFBase = models.Field[RRule | str | None, RRule | None]
else:
    RRFBase = models.Field


class RecurrenceRuleField(RRFBase):
    description = "RFC 5545 recurrence rule"

    def get_internal_type(self):
        return "CharField"

    def __init__(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("max_length", 255)  # Should be enough for anyone
        super().__init__(*args, **kwargs)

    def from_db_value(self, value: Optional[str], expression: Any, connection: Any):
        try:
            return recurrence.parse(value) if value else None
        except (ValueError, KeyError):
            return None

    def get_prep_value(self, value: Optional[RRule]) -> Optional[str]:
        return value and str(value)

    def to_python(self, value: RRule | str | None):
        if isinstance(value, str):
            try:
                return recurrence.parse(value)
            except ValueError:
                raise ValidationError(
                    "“%(value)s” is not a valid recurrence rule.",
                    params={"value": value})
        return value

    def value_to_string(self, obj: models.Model):
        value = self.value_from_object(obj)
        return self.get_prep_value(value)

    def formfield(self, **kwargs: Any):
        return super().formfield(widget=forms.Textarea(attrs={'rows': 2}),
                                 **kwargs)


class Transaction(models.Model):
    """A logical event involving moving money between accounts and categories"""
    id: models.BigAutoField
    date = models.DateField()
    recurrence = RecurrenceRuleField(null=True, blank=True)
    cleared_account: 'models.ManyToManyField[Account, Cleared]'
    cleared_account = models.ManyToManyField(
        Account, through='Cleared', related_name='cleared_transaction')

    class Kind(models.TextChoices):
        TRANSACTION = 'T', 'Transaction'
        BUDGETING = 'B', 'Budgeting'
    kind = models.CharField(max_length=1, choices=Kind.choices,
                            default=Kind.TRANSACTION)

    parts: 'RelatedManager[TransactionPart]'
    cleared: 'models.Manager[Cleared]'

    objects: ClassVar[TransactionQuerySet]
    objects = models.manager.BaseManager.from_queryset(
        TransactionQuerySet)()  # type: ignore

    account: BaseAccount
    is_inbox: bool
    is_future: bool
    reconciled: bool | None
    uncleared: bool
    change: int
    running_sum: int | Literal['']
    contents: list[tuple[int, str, list[tuple[int, int, int]],
                         list[tuple[int, int, int]]]]
    # Would it be nicer to just update these members and save_contents()?
    invisible_parts: list['TransactionPart'] = []
    visible_parts: list['TransactionPart'] = []

    def __str__(self):
        return str(self.date)

    def description(self, in_account: AccountLike):
        if self.kind == Transaction.Kind.BUDGETING:
            return 'Budget'
        return '; '.join(part.description(in_account)
                         for part in self.visible_parts)

    @property
    def month(self) -> 'Optional[date]':
        return self.date and self.date.replace(day=1)

    @month.setter
    def month(self, value: 'Optional[date]'):
        self.date = value and value.replace(day=1)

    def visible(self):
        return any(part.visible() for part in self.visible_parts)

    def clean(self):
        if isinstance(self.date, date) and isinstance(self.recurrence, RRule):
            if self.recurrence.freq in ("HOURLY", "MINUTELY", "SECONDLY"):
                raise ValidationError({'recurrence':
                                       'Transaction repeats more than once a day'})
            # DOS protection
            repeats = self.recurrence.iterate(self.date)
            twentieth = next(islice(repeats, 20, None), None)
            if twentieth and twentieth < date.today():
                raise ValidationError(
                    {'recurrence': 'Transaction repeats more than 20 times'})

    def first_currency(self):
        part = self.visible_parts[0]
        return next(chain(*part.entries())).currency

    @atomic
    def change_inbox_to(self, account: Account | Category):
        for part in self.visible_parts:
            part.change_inbox_to(account)

    @atomic
    def copy_to(self, to: 'date'):
        transaction = Transaction(date=to, kind=self.kind)
        transaction.save()
        for from_part in chain(self.visible_parts, self.invisible_parts):
            part = TransactionPart(
                transaction=transaction, note=from_part.note)
            part.save()
            part.set_flows(*from_part.flows())
        return transaction

    def do_recurrence(self):
        today = date.today()
        if not self.recurrence or not self.date or self.date > today:
            return False
        with atomic():
            for copy in self.recurrence.iterate(self.date):
                if copy <= today:
                    self.copy_to(copy)
                else:
                    self.date = copy
                    self.save()
                    return True
        raise RuntimeError("unreachable")


@dataclass
class MultiTransaction:
    """Fake transaction representing multiple transactions."""
    contents: list[Transaction]
    kind: Literal['M'] = 'M'

    def parts(self):
        accounts: list[dict[Account, int]] = []
        categories: list[dict[Category, int]] = []
        for transaction in self.contents:
            for part in transaction.visible_parts:
                part_accounts, part_categories = part.entries()
                accounts.append(part_accounts)
                categories.append(part_categories)
        cleared = ()  # TODO
        accounts_grouped = group_by_currency(merge(accounts))
        categories_grouped = group_by_currency(merge(categories))
        return [
            Row.from_entries(accounts_grouped.get(currency, {}),
                             categories_grouped.get(currency, {}),
                             cleared)
            for currency in accounts_grouped | categories_grouped]


class Cleared(models.Model):
    class Meta:  # type: ignore
        db_table = 'budget_transaction_cleared'
        unique_together = ["transaction", "account"]

    transaction: models.ForeignKey[Transaction]
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name='cleared')
    account = models.ForeignKey(Account, on_delete=models.CASCADE,
                                related_name='cleared')
    reconciled = models.BooleanField(default=False)


class TransactionPart(models.Model):
    id: models.BigAutoField
    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="parts")
    note = models.TextField(max_length=1000, blank=True)

    # Note that these are not filtered by `filter_for()`.
    accounts: 'models.ManyToManyField[Account, AccountEntry]'
    accounts = models.ManyToManyField(Account, through='AccountEntry',
                                      through_fields=('part', 'sink'))
    categories: 'models.ManyToManyField[Category, CategoryEntry]'
    categories = models.ManyToManyField(Category, through='CategoryEntry',
                                        through_fields=('part', 'sink'))
    accountentry_set: 'RelatedManager[Account]'
    categoryentry_set: 'RelatedManager[Category]'

    # Make a type alias?
    # Really these should be dicts but we need to fix the integrity constraints
    # on entries first.
    visible_accounts: list[tuple[Account, Account, int]] = []
    invisible_accounts: list[tuple[Account, Account, int]] = []
    visible_categories: list[tuple[Category, Category, int]] = []
    invisible_categories: list[tuple[Category, Category, int]] = []

    def visible(self) -> bool:
        return bool(self.visible_accounts or self.visible_categories)

    # Maybe we need a re-double-entrify function...

    def description(self, in_account: AccountLike):
        if self.note:
            return self.note
        accounts, categories = self.entries()
        accounts = set(chain(accounts, categories))
        if isinstance(in_account, Account) or isinstance(in_account, Category):
            accounts.discard(in_account)
        names = {account.description(in_account.budget)
                 for account in accounts}
        return ', '.join(sorted(names))

    def entries(self):
        return (sum_by((sink, amount)
                       for _, sink, amount in self.visible_accounts),
                sum_by((sink, amount)
                       for _, sink, amount in self.visible_categories))

    def flows(self):
        return (self.visible_accounts + self.invisible_accounts,
                self.visible_categories + self.invisible_categories)

    def set_entries(self, in_budget: Budget,
                    accounts: dict[Account, int], categories: dict[Category, int]):
        """Set the contents of this transaction from the perspective of one budget.
        'accounts' and 'categories' both must to sum to zero."""
        return self.set_flows(double_entrify(in_budget, Account, accounts)
                              + self.invisible_accounts,
                              double_entrify(in_budget, Category, categories)
                              + self.invisible_categories)

    @atomic
    def set_flows(self,
                  accounts: list[tuple[Account, Account, int]],
                  categories: list[tuple[Category, Category, int]]):
        has_accounts = self.set_flows_of(self.accountentry_set, accounts)
        has_categories = self.set_flows_of(self.categoryentry_set, categories)
        if has_accounts or has_categories:
            return self
        self.delete()
        return None

    def set_flows_of(self, manager: Any, flows: list[tuple[AccountT, AccountT, int]]):
        manager.all().delete()
        updates = [manager.model(source=source, sink=sink, amount=amount,
                                 part=self)
                   for source, sink, amount in flows if amount]
        if not updates:
            return False
        manager.bulk_create(updates)
        return True

    def change_inbox_to(self, account: Account | Category):
        accounts, categories = self.entries()
        if isinstance(account, Account):
            inbox = account.budget.get_inbox(Account, account.currency)
            account_value = accounts.pop(inbox, 0) + accounts.pop(account, 0)
            accounts[account] = account_value
        else:
            inbox = account.budget.get_inbox(Category, account.currency)
            account_value = (categories.pop(inbox, 0)
                             + categories.pop(account, 0))
            categories[account] = account_value
        self.set_entries(account.budget, accounts, categories)

    def tabular(self):
        # Can this be cached?
        reconciled = (self.transaction.cleared
                      .filter(reconciled=True)
                      .values_list('account', flat=True))
        return Row.from_entries(*self.entries(), reconciled)


@dataclass
class Row:
    account: Optional[Account]
    category: Optional[Category]
    amount: int
    reconciled: bool

    @staticmethod
    def from_entries(accounts: dict[Account, int], categories: dict[Category, int],
                     reconciled: Collection[int]):
        def pop_by_(entries: dict[AccountT, int],
                    currency: str, amount: int):
            try:
                result = next(to for (to, value) in entries.items()
                              if value == amount and to.currency == currency)
                del entries[result]
                return result
            except StopIteration:
                return None

        amounts = sorted((account.currency, amount)
                         for account, amount
                         in chain(accounts.items(), categories.items()))
        rows: list[Row]
        rows = []
        for currency, amount in amounts:
            account = pop_by_(accounts, currency, amount)
            category = pop_by_(categories, currency, amount)
            if account or category:
                is_reconciled = (account and account.id) in reconciled
                rows.append(Row(account, category, amount, is_reconciled))
        return rows


class Entry(Generic[AccountT], models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(
            fields=["part", "source", "sink"], name="m2m_%(class)s")]
    part = models.ForeignKey(TransactionPart, on_delete=models.CASCADE,
                             related_name="%(class)s_set")
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


class AccountEntry(Entry[Account]):
    class Meta:  # type: ignore
        verbose_name_plural = 'accountentries'

    source = models.ForeignKey(Account, on_delete=models.PROTECT,
                               related_name="source_entries")  # make nameless?
    sink = models.ForeignKey(Account, on_delete=models.PROTECT,
                             related_name="entries")


class CategoryEntry(Entry[Category]):
    class Meta:  # type: ignore
        verbose_name_plural = 'categoryentries'

    source = models.ForeignKey(Category, on_delete=models.PROTECT,
                               related_name="source_entries")
    sink = models.ForeignKey(Category, on_delete=models.PROTECT,
                             related_name="entries")


def months_between(start: date, end: date):
    start = start.replace(day=1)
    while start <= end:
        yield start
        start = (start + timedelta(days=31)).replace(day=1)

# Some of these could be methods


def groups_for(categories: Iterable[Category]) -> dict[Category, dict[str, list[int]]]:
    groups = {}
    prev_group = None
    for category in categories:
        if not prev_group or prev_group.group != category.group:
            groups[category] = defaultdict(list)
            groups[category][category.currency] = [category.balance]
            prev_group = category
        else:
            groups[prev_group][category.currency].append(category.balance)
    return groups


def accounts_overview(budget: Budget):
    # TODO: Return totals and debts using the corresponding objects
    past = Q(entries__part__transaction__date__lte=date.today())
    sum_entries = Sum('entries__amount', filter=past, default=0)
    accounts = (Account.objects
                .filter(budget=budget)
                .annotate(balance=sum_entries)
                .exclude(closed=True, balance=0)
                .exclude(name='', balance=0)
                .order_by('order', 'group', 'name')
                .select_related('budget'))
    categories = (Category.objects
                  .filter(budget=budget)
                  .annotate(balance=sum_entries)
                  .exclude(closed=True, balance=0)
                  .exclude(name='', balance=0)
                  .order_by('order', 'group', 'name')
                  .select_related('budget'))
    currencies = {*budget.account_set.values_list('currency').distinct(),
                  *budget.category_set.values_list('currency').distinct()}

    groups = groups_for(categories)

    past = Q(part__transaction__date__lte=date.today())
    sum_amount = Sum('amount', filter=past, default=0)
    gets = (CategoryEntry.objects
            .filter(source__currency=OuterRef('currency'),
                    source__budget=OuterRef('pk'),
                    sink__budget=budget)
            .values('source__budget')
            .values(sum=sum_amount))
    has = (AccountEntry.objects
           .filter(source__currency=OuterRef('currency'),
                   source__budget=OuterRef('pk'),
                   sink__budget=budget)
           .values('source__budget')
           .values(sum=sum_amount))
    debts = [Balance(budget, other, currency)
             for currency, in currencies
             for other in Budget.objects
             .annotate(currency=Value(currency),
                       balance=Coalesce(Subquery(gets), 0)
                       - Coalesce(Subquery(has), 0))
             .exclude(balance=0)]
    totals = [Total(budget, currency, total)
              for currency, total
              in sum_by((category.currency, category.balance)
                        for category in categories).items()]
    return (accounts, categories, groups, debts, totals)


def category_balance(budget: Budget, start: date):
    end = (start + timedelta(days=31)).replace(day=1)
    return (Category.objects
            .filter(budget=budget)
            .annotate(
                balance=Sum(
                    'entries__amount',
                    filter=Q(entries__part__transaction__date__lt=start),
                    default=0),
                change=Sum(
                    'entries__amount',
                    filter=Q(entries__part__transaction__kind=Transaction.Kind.TRANSACTION,
                             entries__part__transaction__date__gte=start,
                             entries__part__transaction__date__lt=end),
                    default=0))
            .order_by('order', 'group', 'name'))


def budgeting_transaction(budget: Budget, date: date):
    transaction = (Transaction.objects
                   .filter(kind=Transaction.Kind.BUDGETING, date=date,
                           parts__categories__budget=budget)
                   .fetch_contents()
                   .first())
    if transaction:
        fetch_accounts([transaction], budget)
        return transaction
    return Transaction(date=date)


def budgeting_categories(budget: Budget, transaction: Transaction) -> list[Category]:
    assert transaction.date

    # Make sure these exist first
    for currency, in budget.category_set.values_list('currency').distinct():
        budget.get_inbox(Category, currency)
    balances = category_balance(budget, transaction.date)

    if transaction.pk:
        entries = transaction.visible_parts[0].entries()[1]
    else:
        entries = {}

    shown = {category for category in balances
             if category.balance or category.change or category in entries
             or (not category.is_inbox() and not category.closed)}
    currencies = {category.currency for category in shown}
    inboxes = {category for category in balances
               if category.is_inbox() and category.currency in currencies}
    shown |= inboxes
    balances = [category for category in balances if category in shown]

    return balances


def prior_budgeting_transaction(budget: Budget, date: date):
    return (Transaction.objects
            .filter(kind=Transaction.Kind.BUDGETING, date__lt=date,
                    parts__categories__budget=budget)
            .order_by('-date')
            .first())


def date_range(budget: Budget) -> tuple[date, date]:
    range = (Transaction.objects
             .filter(parts__categories__budget=budget)
             .aggregate(Max('date', default=date.today()),
                        Min('date', default=date.today())))
    return (min(range['date__min'], date.today()),
            max(range['date__max'], date.today()))
