from typing import Optional, Iterable, TypeVar, Type
from collections import defaultdict, deque
import functools
from itertools import chain
import typing
from datetime import date

from django.db import models
from django.db.models import Q, Sum, F
from django.db.models.functions import Trunc
from django.urls import reverse

BaseAccountT = TypeVar('BaseAccountT', bound='BaseAccount')


class Budget(models.Model):
    id: models.BigAutoField
    name = models.CharField(max_length=100)
    account_set: 'models.Manager[Account]'
    category_set: 'models.Manager[Category]'
    # May be marked as external
    # TODO: owner, currency

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('budget', kwargs={'budget_id': self.id})

    def get_hidden(self, cls: Type[BaseAccountT]) -> BaseAccountT:
        return cls.objects.get_or_create(name="", budget=self)[0]


class BaseAccount(models.Model):
    """BaseAccounts describe a generic place money can be"""
    class Meta:  # type: ignore
        abstract = True
    id: models.BigAutoField
    name = models.CharField(max_length=100, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    budget_id: int  # Sigh
    balance: int
    entries: 'models.Manager[TransactionPart]'
    # TODO: read/write access

    def kind(self) -> str:
        return ''

    def get_absolute_url(self):
        return reverse(self.kind(), kwargs={self.kind() + '_id': self.id})

    def ishidden(self):
        return self.name == ""

    def __str__(self):
        if self.ishidden():
            return self.budget.name
        else:
            return f"{self.budget.name} - {str(self.name)}"

    def name_in_budget(self, budget_id: int):
        if self.budget_id == budget_id:
            return self.name or "Inbox"
        if isinstance(self, Category):
            return f"[{self.budget.name}]"
        return self.budget.name

    def to_hidden(self):
        if self.ishidden():
            return self
        return self.budget.get_hidden(self.__class__)

    def display_in(self, budget_id: int):
        if self.budget_id != budget_id:
            return self.to_hidden()
        else:
            return self


class Account(BaseAccount):
    """Accounts describe the physical ownership of money."""

    def kind(self):
        return 'account'


class Category(BaseAccount):
    """Categories describe the conceptual ownership of money."""
    class Meta:  # type: ignore
        verbose_name_plural = "categories"

    def kind(self):
        return 'category'


T = TypeVar('T')


def sum_by(input: 'Iterable[tuple[T, int]]') -> 'dict[T, int]':
    result: defaultdict[T, int] = defaultdict(int)
    for key, value in input:
        result[key] += value
    return result


class Transaction(models.Model):
    """A logical event involving moving money between accounts and categories"""
    id: models.BigAutoField
    date = models.DateField()
    description = models.CharField(blank=True, max_length=1000)
    accounts: 'models.ManyToManyField[Account, TransactionAccountPart]'
    account_parts: 'models.Manager[TransactionAccountPart]'
    accounts = models.ManyToManyField(
        Account, through='TransactionAccountPart',
        through_fields=('transaction', 'to'))
    categories: 'models.ManyToManyField[Category, TransactionCategoryPart]'
    category_parts: 'models.Manager[TransactionCategoryPart]'
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

    # TODO: Maybe put this in the non-database wrapper thingy (proxy model?)
    def debts(self):
        owed = sum_by(chain(((part.to.budget_id, part.amount)
                            for part in self.account_parts.all()),
                            ((part.to.budget_id, -part.amount)
                             for part in self.category_parts.all())))
        return combine_debts(owed)

    def parts(self, in_budget_id: int):
        accounts = sum_by((part.to.display_in(in_budget_id), part.amount)
                          for part in self.account_parts.all())
        categories = sum_by((part.to.display_in(in_budget_id), part.amount)
                            for part in self.category_parts.all())
        return (accounts, categories)

    def residual_parts_(self, in_budget_id: int):
        accounts: defaultdict[Account, int] = defaultdict(int)
        categories: defaultdict[Category, int] = defaultdict(int)
        for part in self.account_parts.all():
            affected = part.to.display_in(in_budget_id)
            accounts[affected] += 0 if affected == part.to else part.amount
        for part in self.category_parts.all():
            affected = part.to.display_in(in_budget_id)
            categories[affected] += 0 if affected == part.to else part.amount
        return (accounts, categories)

    # FIXME: With no parts, a transaction become inaccessible
    def set_parts(self, in_budget_id: int,
                  accounts: 'dict[Account, int]', categories: 'dict[Category, int]'):
        res_accounts, res_categories = self.residual_parts_(in_budget_id)
        for account in res_accounts.keys() | accounts.keys():
            amount = accounts.get(account, 0) - res_accounts.get(account, 0)
            TransactionAccountPart.update(self, account, amount)
        for category in res_categories.keys() | categories.keys():
            amount = (categories.get(category, 0) -
                      res_categories.get(category, 0))
            TransactionCategoryPart.update(self, category, amount)

    def tabular(self, in_budget_id: int):
        def pop_by_amount_(parts: 'dict[BaseAccountT, int]', amount: int
                           ) -> Optional[BaseAccountT]:
            try:
                result = next(part for (part, value) in parts.items()
                              if value == amount)
                del parts[result]
                return result
            except StopIteration:
                return None

        accounts, categories = self.parts(in_budget_id)
        rows: list[dict[str, typing.Any]]
        rows = []
        for amount in sorted(chain(accounts.values(), categories.values())):
            account = pop_by_amount_(accounts, amount)
            category = pop_by_amount_(categories, amount)
            if account or category:
                rows.append({'account': account, 'category': category,
                             'amount': amount})
        return rows

    def auto_description(self, in_account: BaseAccount):
        if self.description:
            return self.description
        categories = [category.name_in_budget(in_account.budget_id)
                      for category in self.categories.all()
                      if not category.ishidden() and category != in_account]
        accounts = [account.name_in_budget(in_account.budget_id)
                    for account in self.accounts.all()
                    if account != in_account]
        names = accounts + categories
        if len(names) > 2:
            names = names[:2] + ['...']
        return ", ".join(names)


def combine_debts(owed: 'dict[int, int]'):
    amounts = deque(sorted((amount, budget) for (budget, amount) in owed.items()
                           if amount != 0))
    result: 'dict[tuple[int, int], int]' = {}
    amount, from_budget = 0, 0
    while amounts or amount:
        if not amount:
            amount, from_budget = amounts.popleft()
        if not amounts:
            raise ValueError("Debts do not sum to zero")
        other, to_budget = amounts.pop()
        result_amount = min(-amount, other)
        result[(from_budget, to_budget)] = result_amount
        amount += other
        if amount > 0:
            amounts.append((amount, to_budget))
            amount = 0
    return result


def sum_debts(debts_1: 'dict[tuple[int, int], int]',
              debts_2: 'dict[tuple[int, int], int]'):
    keys = debts_1.keys() | debts_2.keys()
    return {key: debts_1.get(key, 0) + debts_2.get(key, 0) for key in keys}


class TransactionPart(models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(fields=["transaction", "to"],
                                               name="m2m_%(class)s")]
    transaction: models.ForeignKey[Transaction]
    amount = models.BigIntegerField()
    to: BaseAccount
    to_id: int

    @classmethod
    def update(cls, transaction: Transaction, to: BaseAccount, amount: int):
        if amount == 0:
            cls.objects.filter(transaction=transaction, to=to).delete()
        else:
            cls.objects.update_or_create(
                transaction=transaction, to=to, defaults={'amount': amount})

    def __str__(self):
        return f"{self.to} + {self.amount}"


class TransactionAccountPart(TransactionPart):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="account_parts")
    to: Account
    to = models.ForeignKey(Account, on_delete=models.PROTECT,
                           related_name="entries")  # type: ignore


class TransactionCategoryPart(TransactionPart):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="category_parts")
    to: Category
    to = models.ForeignKey(Category, on_delete=models.PROTECT,
                           related_name="entries")  # type: ignore

# Transaction.objects
# .annotate(value_change=Sum('category_parts__amount',
#                             filter=Q(categories__budget_id=budget_id)))
# .exclude(value_change=0)


def transactions_for_budget(budget_id: int) -> Iterable[Transaction]:
    filter = (Q(accounts__budget_id=budget_id) |
              Q(categories__budget_id=budget_id))
    qs = (Transaction.objects
          .filter(filter)
          .distinct()
          .order_by('date', '-kind')
          .prefetch_related('account_parts', 'category_parts',
                            'accounts__budget', 'categories__budget'))
    total = 0
    for transaction in qs:
        for part in transaction.category_parts.all():
            if part.to.budget_id == budget_id:
                total += part.amount
        setattr(transaction, 'running_sum', total)
    return reversed(qs)


def entries_for(account: BaseAccount) -> Iterable[TransactionPart]:
    qs = (account.entries
          .order_by('transaction__date', '-transaction__kind')
          .prefetch_related('transaction__account_parts__to__budget',
                            'transaction__category_parts__to__budget'))
    total = 0
    for part in qs:
        total += part.amount
        setattr(part, 'running_sum', total)
    return reversed(qs)


def transactions_for_balance(budget_id_1: int, budget_id_2: int
                             ) -> Iterable[Transaction]:
    filter = (Q(accounts__budget_id=budget_id_1) &
              Q(categories__budget_id=budget_id_2) |
              Q(accounts__budget_id=budget_id_2) &
              Q(categories__budget_id=budget_id_1))
    qs = (Transaction.objects
          .filter(filter)
          .distinct()
          .order_by('date', '-kind')
          .prefetch_related('account_parts', 'category_parts',
                            'accounts__budget', 'categories__budget'))
    total = 0
    for transaction in qs:
        debts = transaction.debts()
        out = debts.get((budget_id_1, budget_id_2))
        if out:
            total += out
        into = debts.get((budget_id_2, budget_id_1))
        if into:
            total -= into
        setattr(transaction, 'running_sum', total)
    return reversed(qs)


def accounts_overview(budget_id: int):
    accounts = (Account.objects
                .filter(budget_id=budget_id)
                .annotate(balance=Sum('entries__amount', default=0)))
    categories = (Category.objects
                  .filter(budget_id=budget_id)
                  .annotate(balance=Sum('entries__amount', default=0)))
    transactions = transactions_for_budget(budget_id)
    debt_map = functools.reduce(
        sum_debts, (transaction.debts() for transaction in transactions))
    debts = ([(Budget.objects.get(id=from_budget), -amount)
              for ((from_budget, to_budget), amount) in debt_map.items()
              if to_budget == budget_id] +
             [(Budget.objects.get(id=to_budget), amount)
             for ((from_budget, to_budget), amount) in debt_map.items()
             if from_budget == budget_id])
    return (accounts, categories, debts)


def category_history(budget_id: int):
    return (TransactionCategoryPart.objects
            .filter(to__budget_id=budget_id,
                    transaction__kind=Transaction.Kind.TRANSACTION)
            .values('to', month=Trunc(F('transaction__date'), 'month'))
            .annotate(total=Sum('amount')))
    # return (TransactionCategoryPart.objects
    #         .filter(to__budget_id=budget_id)
    #         .values('to',
    #                 kind=F('transaction__kind'),
    #                 budgeting=Case(
    #                     When(transaction__kind=Transaction.Kind.BUDGETING, then='transaction_id')),
    #                 month=Trunc(F('transaction__date'), 'month'))
    #         .annotate(total=Sum('amount')))


def budgeting_transactions(budget_id: int):
    return (Transaction.objects
            .filter(kind=Transaction.Kind.BUDGETING,
                    category_parts__to__budget_id=budget_id)
            .distinct())
