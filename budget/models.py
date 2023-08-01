from typing import Optional, Iterable, TypeVar, Type, Union, Self, Generic, Any
import functools
from itertools import chain, islice
from datetime import date, timedelta
from dataclasses import dataclass
import heapq

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django import forms
from django.db.transaction import atomic
from django.db.models import (Q, F, Prefetch, Subquery, OuterRef, Value,
                              Min, Max, Sum, Exists,
                              prefetch_related_objects)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.contrib.auth.models import User, AnonymousUser, AbstractBaseUser

from .algorithms import sum_by, reroot, double_entrify_by, Debts
from . import recurrence
from .recurrence import RRule


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

    initial_currency = models.CharField(max_length=5, blank=True)
    initial_split = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.name

    @functools.cache
    def get_absolute_url(self):
        return reverse('overview', kwargs={'budget_id': self.id})

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
                .filter(name='', closed=False)
                .values_list('currency', flat=True)
                .distinct())

    def get_initial_currency(self):
        if self.initial_currency:
            return self.initial_currency
        else:
            category = self.category_set.first()
            if category:
                return category.currency
            else:
                return 'CHF'


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
    source_entries: 'models.Manager[Entry[Self]]'
    entries: 'models.Manager[Entry[Self]]'
    currency = models.CharField(max_length=5)

    group = models.CharField(max_length=100, blank=True)
    order = models.IntegerField(default=0)
    closed = models.BooleanField(default=False)

    def kind(self) -> str: ...  # pragma: no cover
    def kind_name(self) -> str: ...  # pragma: no cover

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
        return reverse('account', kwargs={'account_id': self.id})

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
        """Adjust and prefetch the entries of this transaction to ones visible to
        'budget'."""
        accountentry_set = AccountEntry.objects.filter_for(budget)
        categoryentry_set = CategoryEntry.objects.filter_for(budget)
        # We have to do this stupid ordering thing because otherwise django's
        # form stuff adds an ordering later and breaks the prefetch logic.
        # TODO: This is ugly. Should we just do the filtering in python?
        parts = (TransactionPart.objects
                 .filter(Exists(accountentry_set.filter(part=OuterRef('id')))
                         | Exists(categoryentry_set.filter(part=OuterRef('id'))))
                 .order_by('id'))
        return self.prefetch_related(
            Prefetch('parts', queryset=parts),
            Prefetch('parts__accountentry_set', queryset=accountentry_set),
            Prefetch('parts__categoryentry_set', queryset=categoryentry_set),
        )

    def get_for(self, budget: Budget, id: int):
        try:
            value = self.filter_for(budget).get(id=id)
        except self.model.DoesNotExist:
            return None
        if all(part.empty() for part in value.parts.all()):
            return None
        return value


TYPE_CHECKING = False
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
        except ValueError:
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

    class Kind(models.TextChoices):
        TRANSACTION = 'T', 'Transaction'
        BUDGETING = 'B', 'Budgeting'
    kind = models.CharField(max_length=1, choices=Kind.choices,
                            default=Kind.TRANSACTION)

    parts: 'models.Manager[TransactionPart]'

    objects = TransactionManager()

    running_sum: int  # TODO this is gross, put in view logic

    def __str__(self):
        return str(self.date)

    @property
    def month(self) -> 'Optional[date]':
        return self.date and self.date.replace(day=1)

    @month.setter
    def month(self, value: 'Optional[date]'):
        self.date = value and value.replace(day=1)

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

    def auto_description(self, in_account: BaseAccount | Balance):
        if self.kind == self.Kind.BUDGETING:
            return "Budget"

        note = ', '.join(part.note for part in self.parts.all() if part.note)
        if note:
            return note

        accounts = {entry
                    for part in self.parts.all()
                    for entry in part.accountentry_set.entries()}
        categories = {entry
                      for part in self.parts.all()
                      for entry in part.categoryentry_set.entries()}
        if isinstance(in_account, BaseAccount):
            this_budget = in_account.budget
        else:
            this_budget = in_account.other
        names = (
            list({account.budget.name
                  for account in chain(accounts, categories)
                  if account.budget.budget_of_id != in_account.budget.owner()
                  and account.budget != this_budget})
            + [account.name or "Inbox"
               for account in chain(accounts, categories)
               if account.budget.budget_of_id == in_account.budget.owner()
               and account != in_account]
        )
        return ", ".join(names)

    @atomic
    def change_inbox_to(self, account: Account | Category):
        for part in self.parts.all():
            part.change_inbox_to(account)

    @atomic
    def copy_to(self, to: 'date'):
        transaction = Transaction(date=to, kind=self.kind)
        transaction.save()
        for from_part in self.parts.all():
            part = TransactionPart(transaction=transaction)
            part.save()
            part.set_flows(*from_part.flows())
        return transaction

    @atomic
    def do_recurrence(self):
        today = date.today()
        if not self.recurrence or not self.date or self.date > today:
            return False
        for copy in self.recurrence.iterate(self.date):
            if copy <= today:
                self.copy_to(copy)
            else:
                self.date = copy
                self.save()
                return True
        raise RuntimeError("unreachable")


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
    accountentry_set: 'EntryManager[Account]'
    categoryentry_set: 'EntryManager[Category]'

    def empty(self) -> bool:
        return (not self.accountentry_set.all() and
                not self.categoryentry_set.all())

    def entries(self):
        return (self.accountentry_set.entries(), self.categoryentry_set.entries())

    def flows(self):
        return (self.accountentry_set.flows(), self.categoryentry_set.flows())

    def set_entries(self, in_budget: Budget,
                    accounts: dict[Account, int], categories: dict[Category, int]):
        """Set the contents of this transaction from the perspective of one budget. 'accounts' and 'categories' both must to sum to zero."""
        # 'self' is already filtered for a user, we just can't see which one
        return self.set_flows(double_entrify(in_budget, Account, accounts),
                              double_entrify(in_budget, Category, categories))

    @atomic
    def set_flows(self,
                  accounts: dict[tuple[Account, Account], int],
                  categories: dict[tuple[Category, Category], int]):
        self.accountentry_set.set_flows(accounts)
        self.categoryentry_set.set_flows(categories)
        if (AccountEntry.objects.filter(part=self).exists() or
                CategoryEntry.objects.filter(part=self).exists()):
            return self
        self.delete()
        return None

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

    @dataclass
    class Row:
        account: Optional[Account]
        category: Optional[Category]
        amount: int

    def tabular(self):
        def pop_by_(entries: 'dict[AccountT, int]',
                    currency: str, amount: int):
            try:
                result = next(to for (to, value) in entries.items()
                              if value == amount and to.currency == currency)
                del entries[result]
                return result
            except StopIteration:
                return None

        accounts = self.accountentry_set.entries()
        categories = self.categoryentry_set.entries()
        amounts = sorted((account.currency, amount)
                         for account, amount
                         in chain(accounts.items(), categories.items()))
        rows: list[TransactionPart.Row]
        rows = []
        for currency, amount in amounts:
            account = pop_by_(accounts, currency, amount)
            category = pop_by_(categories, currency, amount)
            if account or category:
                rows.append(TransactionPart.Row(
                    account, category, amount))
        return rows


class EntryManager(Generic[AccountT], models.Manager['Entry[AccountT]']):
    # This could be a generic arg actually...
    instance: TransactionPart  # When used as a relatedmanager

    def filter_for(self, budget: Budget):
        """Filter entries to ones visible to 'budget'."""
        source_visible = (Q(source__budget__budget_of_id=budget.owner())
                          | Q(source__budget__payee_of_id=budget.owner())
                          | (Q(source__name="")
                             & Q(source__budget__in=budget.friends.all())))
        sink_visible = (Q(sink__budget__budget_of_id=budget.owner())
                        | Q(sink__budget__payee_of_id=budget.owner())
                        | (Q(sink__name="")
                           & Q(sink__budget__in=budget.friends.all())))
        return (self.filter(source_visible, sink_visible)
                .select_related('sink__budget'))

    def entries(self) -> dict[AccountT, int]:
        return sum_by((entry.sink, entry.amount) for entry in self.all())

    def flows(self) -> dict[tuple[AccountT, AccountT], int]:
        return {(entry.source, entry.sink): entry.amount
                for entry in self.all() if entry.amount > 0}

    def set_flows(self, flows: dict[tuple[AccountT, AccountT], int]):
        self.all().delete()
        updates = chain.from_iterable(
            (self.model(source=source, sink=sink, amount=amount,
                        part=self.instance),
             self.model(source=sink, sink=source, amount=-amount,
                        part=self.instance))
            for (source, sink), amount in flows.items() if amount)
        if updates:
            self.bulk_create(updates)


class Entry(Generic[AccountT], models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(
            fields=["part", "source", "sink"], name="m2m_%(class)s")]
    objects: EntryManager[AccountT] = EntryManager()
    part = models.ForeignKey(TransactionPart, on_delete=models.CASCADE,
                             related_name="%(class)s_set")
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


def entries_for(account: BaseAccount) -> list[Transaction]:
    if isinstance(account, Account):  # gross
        field, amount = 'parts__accounts', 'parts__accountentry_set__amount'
    else:
        field, amount = 'parts__categories', 'parts__categoryentry_set__amount'

    if not account.is_inbox():
        inbox = account.budget.get_inbox(type(account), account.currency).id
    else:
        inbox = None
    qs = (Transaction.objects
          .filter_for(account.budget)
          .filter(Q(**{field: account}) |
                  (Q(**{field: inbox}) & ~Q(kind=Transaction.Kind.BUDGETING)))
          .annotate(account=F(field), change=Sum(amount)).exclude(change=0)
          .order_by('date', '-kind', 'id'))
    if sum(transaction.do_recurrence() for transaction in qs):
        return entries_for(account)  # Retry
    total = 0
    for transaction in qs:
        if getattr(transaction, 'account') == inbox:
            setattr(transaction, 'is_inbox', True)
        else:
            total += getattr(transaction, 'change')
            setattr(transaction, 'running_sum', total)
    return list(reversed(qs))


def entries_for_balance(account: Balance) -> Iterable[Transaction]:
    gets = (CategoryEntry.objects
            .filter(part__transaction=OuterRef('pk'),
                    source__currency=account.currency,
                    source__budget=account.other, sink__budget=account.budget)
            .values('part__transaction')
            .values(sum=Sum('amount')))
    has = (AccountEntry.objects
           .filter(part__transaction=OuterRef('pk'),
                   source__currency=account.currency,
                   source__budget=account.other, sink__budget=account.budget)
           .values('part__transaction')
           .values(sum=Sum('amount')))
    # Does it make sense to exclude transactions that don't alter the balance?
    # In general transactions that do and don't will be on different payees.
    qs = (Transaction.objects
          .filter_for(account.budget)
          .annotate(change=Coalesce(Subquery(gets), 0)
                    - Coalesce(Subquery(has), 0))
          .exclude(change=0)
          .order_by('date', '-kind', 'id'))
    if sum(transaction.do_recurrence() for transaction in qs):
        return entries_for_balance(account)  # Retry
    total = 0
    for transaction in qs:
        total += getattr(transaction, 'change')
        setattr(transaction, 'running_sum', total)
    return list(reversed(qs))


def accounts_overview(budget: Budget):
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
            .order_by('order', 'group', 'name')
            )


def budgeting_transaction(budget: Budget, date: date):
    return (Transaction.objects
            .filter(kind=Transaction.Kind.BUDGETING, date=date,
                    parts__categories__budget=budget)
            .first())


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
