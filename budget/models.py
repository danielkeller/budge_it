from typing import Optional, Iterable, TypeVar, Type, Union, Any
from collections import defaultdict, deque
import functools
from itertools import chain
import typing
from datetime import date

from django.db import models
from django.db.models import Q, Sum, F
from django.db.models.functions import Trunc
from django.urls import reverse
from django.contrib.auth.models import User, AnonymousUser, AbstractBaseUser

BaseAccountT = TypeVar('BaseAccountT', bound='BaseAccount')
T = TypeVar('T')


class Budget(models.Model):
    class Meta:  # type: ignore
        constraints = [models.CheckConstraint(
            check=Q(budget_of__isnull=True) | Q(payee_of__isnull=True),
            name="cant_be_payee_and_budget")]

    id: models.BigAutoField
    name = models.CharField(max_length=100)
    account_set: 'models.Manager[Account]'
    category_set: 'models.Manager[Category]'

    # This can easily be relaxed into a ForeignKey if we want to allow multiple
    # budgets
    budget_of = models.OneToOneField(
        User, blank=True, null=True, on_delete=models.SET_NULL)
    payee_of = models.ForeignKey(
        User, blank=True, null=True, on_delete=models.SET_NULL,
        related_name="payee_set")

    # Ignored for payees
    friends: 'models.ManyToManyField[Budget, Any]'
    friends = models.ManyToManyField('self',  blank=True)

    # TODO: currency

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('budget', kwargs={'budget_id': self.id})

    def get_hidden(self, cls: Type[BaseAccountT]) -> BaseAccountT:
        return cls.objects.get_or_create(name="", budget=self)[0]

    def owner(self):
        return self.budget_of or self.payee_of

    def view_permission(self, user: Union[AbstractBaseUser, AnonymousUser]):
        return user.is_authenticated and user == self.owner()


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

    def display_in(self, account: BaseAccountT) -> BaseAccountT:
        if self.budget.owner() == account.budget.owner():
            return account
        elif account.budget in self.visible:
            return account.to_hidden()
        else:
            return self.connection(account.budget).get_hidden(type(account))

    @staticmethod
    def visibility(budget: Budget, budgets: 'Iterable[Budget]'):
        ids = (budget.id for budget in budgets)
        filter = Q(friends=budget)
        if budget.owner():
            filter |= (Q(friends__budget_of=budget.owner()) |
                       Q(payee_of=budget.owner()) | Q(budget_of=budget.owner()))
        return Budget.objects.filter(filter, id__in=ids).distinct().order_by('id')

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

    def name_in_budget(self, budget: Budget):
        # This logic is duplicated in account_in_budget.html
        if self.budget.budget_of == budget.owner():
            return self.name or "Inbox"
        if isinstance(self, Category):
            return f"[{self.budget.name}]"
        return self.budget.name

    def to_hidden(self):
        if self.ishidden():
            return self
        return self.budget.get_hidden(type(self))


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


def sum_by(input: 'Iterable[tuple[T, int]]') -> 'dict[T, int]':
    result: defaultdict[T, int] = defaultdict(int)
    for key, value in input:
        result[key] += value
    return {key: value for key, value in result.items() if value}


# TODO: Consider creating a wrapper for a transaction from the perspective of
# one budget

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

    @functools.cached_property
    def budgets(self):
        return set(Budget.objects.filter(Q(category__transaction=self)
                                         | Q(account__transaction=self))
                   .distinct())

    def debts(self):
        owed = sum_by(chain(((part.to.budget_id, part.amount)
                             for part in self.account_parts.all()),
                            ((part.to.budget_id, -part.amount)
                            for part in self.category_parts.all())))
        return combine_debts(owed)

    def visible_from(self, budget: Budget):
        return budget in self.budgets

    def parts(self, in_budget: Budget):
        permissions = Permissions(in_budget, self.budgets)
        accounts = sum_by((permissions.display_in(part.to), part.amount)
                          for part in self.account_parts.all())
        categories = sum_by((permissions.display_in(part.to), part.amount)
                            for part in self.category_parts.all())
        return (accounts, categories)

    def residual_parts_(self, in_budget: Budget):
        """Return the non-inbox transaction parts of all the other budgets,
        accounted to the inbox of that budget. These are subtracted in
        set_parts, so the remainder goes to the inbox."""
        permissions = Permissions(in_budget, self.budgets)
        accounts: defaultdict[Account, int] = defaultdict(int)
        categories: defaultdict[Category, int] = defaultdict(int)
        for part in self.account_parts.all():
            affected = permissions.display_in(part.to)
            accounts[affected] += 0 if affected == part.to else part.amount
        for part in self.category_parts.all():
            affected = permissions.display_in(part.to)
            categories[affected] += 0 if affected == part.to else part.amount
        return (accounts, categories)

    def set_parts(self, in_budget: Budget,
                  accounts: 'dict[Account, int]', categories: 'dict[Category, int]'):
        """Set the contents of this transaction from the perspective of one
        budget. 'accounts' and 'categories' are both expected to sum to zero."""
        res_accounts, res_categories = self.residual_parts_(in_budget)
        has_any_parts = False
        for account in res_accounts.keys() | accounts.keys():
            amount = accounts.get(account, 0) - res_accounts.get(account, 0)
            has_any_parts |= amount != 0
            TransactionAccountPart.update(self, account, amount)
        for category in res_categories.keys() | categories.keys():
            amount = (categories.get(category, 0) -
                      res_categories.get(category, 0))
            has_any_parts |= amount != 0
            TransactionCategoryPart.update(self, category, amount)
        if not has_any_parts:
            self.delete()

    def tabular(self, in_budget: Budget):
        def pop_by_amount_(parts: 'dict[BaseAccountT, int]', amount: int
                           ) -> Optional[BaseAccountT]:
            try:
                result = next(part for (part, value) in parts.items()
                              if value == amount)
                del parts[result]
                return result
            except StopIteration:
                return None

        accounts, categories = self.parts(in_budget)
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
        accounts, categories = self.parts(in_account.budget)
        names = (
            [account.name_in_budget(in_account.budget)
             for account in chain(accounts, categories)
             if account.budget.budget_of == in_account.budget.owner()
             and account != in_account] +
            list({account.budget.name
                  for account in chain(accounts, categories)
                  if account.budget.budget_of != in_account.budget.owner()
                  and account.budget != in_account.budget})
        )
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


def budgeting_transactions(budget_id: int):
    return (Transaction.objects
            .filter(kind=Transaction.Kind.BUDGETING,
                    category_parts__to__budget_id=budget_id)
            .distinct())
