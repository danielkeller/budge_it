from typing import Optional, Union
from datetime import date
from collections import defaultdict

from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.db import transaction


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


class BaseAccount(models.Model):
    class Meta:  # type: ignore
        abstract = True
    id: models.BigAutoField
    name = models.CharField(max_length=100, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    budget_id: int  # Sigh
    # TODO: read/write access

    def ishidden(self):
        return self.name == ""

    def __str__(self):
        if self.ishidden():
            return self.budget.name
        else:
            return self.budget.name + " - " + str(self.name)


class Account(BaseAccount):
    """Accounts describe the physical ownership of money."""

    def kind(self):
        return 'account'

    def get_absolute_url(self):
        return reverse('account', kwargs={'account_id': self.id})

    def get_hidden_category(self) -> 'Category':
        return Category.objects.get_or_create(
            budget_id=self.budget_id, name="")[0]


class Category(BaseAccount):
    """Categories describe the conceptual ownership of money."""
    class Meta:  # type: ignore
        verbose_name_plural = "categories"

    def kind(self):
        return 'category'

    def get_absolute_url(self):
        return reverse('category', kwargs={'category_id': self.id})


class Transaction(models.Model):
    id: models.BigAutoField
    date = models.DateField()
    description = models.CharField(max_length=1000)
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
    running_sum: int

    def __str__(self):
        return str(self.date) + " " + self.description[0:100]

    # TODO: Maybe put this in the non-database wrapper thingy (proxy model?)
    def debts(self):
        owed: defaultdict[int, int] = defaultdict(int)
        for part in self.category_parts.all():
            owed[part.to.budget_id] -= part.amount
        for part in self.account_parts.all():
            owed[part.to.budget_id] += part.amount
        return combine_debts(owed)


def combine_debts(owed: 'dict[int, int]'):
    amounts = sorted((amount, budget) for (budget, amount) in owed.items()
                     if amount != 0)
    result: dict[tuple[int], int] = {}
    amount, from_budget = 0, 0
    while amounts:
        amount, from_budget = amounts.pop(0)
        if not amount:
            amount, from_budget = amounts.pop(0)
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


class TransactionPart(models.Model):
    class Meta:  # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(fields=["transaction", "to"],
                                               name="m2m_%(class)s")]
    transaction: models.ForeignKey['Transaction']
    amount = models.BigIntegerField()
    to_id: int


class TransactionAccountPart(TransactionPart):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="account_parts")
    to = models.ForeignKey(Account, on_delete=models.PROTECT,
                           related_name="entries")  # type: ignore


class TransactionCategoryPart(TransactionPart):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="category_parts")
    to = models.ForeignKey(Category, on_delete=models.PROTECT,
                           related_name="entries")  # type: ignore

# Simple transaction types


class SimpleTransaction:
    id: Optional[int]
    date: date
    description: str

    def __init__(self):
        self.id = None

    @transaction.atomic
    def save(self) -> Transaction:
        result = Transaction(id=self.id, date=self.date,
                             description=self.description)
        self.save_(result)
        return result

    def save_(self, result: Transaction):
        result.save()
        result.accounts.clear()
        result.categories.clear()


class Transfer(SimpleTransaction):
    from_account: Account
    to_account: Account
    amount: int

    def save_(self, result: Transaction):
        super().save_(result)
        TransactionAccountPart.objects.create(
            transaction=result, to=self.from_account, amount=-self.amount)
        TransactionAccountPart.objects.create(
            transaction=result, to=self.to_account, amount=self.amount)


class Purchase(Transfer):
    from_category: Category

    def save_(self, result: Transaction):
        super().save_(result)
        to_category = self.to_account.get_hidden_category()
        TransactionCategoryPart.objects.create(
            transaction=result, to=self.from_category, amount=-self.amount)
        TransactionCategoryPart.objects.create(
            transaction=result, to=to_category, amount=self.amount)


class Inflow(Transfer):
    to_category: Category

    def save_(self, result: Transaction):
        super().save_(result)
        from_category = self.from_account.get_hidden_category()
        TransactionCategoryPart.objects.create(
            transaction=result, to=from_category, amount=-self.amount)
        TransactionCategoryPart.objects.create(
            transaction=result, to=self.to_category, amount=self.amount)


def to_simple_transaction(transaction: Transaction) -> \
        Union[Transaction, Purchase, Inflow, Transfer]:
    """Convert the transaction to a simple transaction if possible."""
    accounts = list(transaction.account_parts.all())
    categories = list(transaction.category_parts.all())
    if len(accounts) == 2:
        if len(categories) == 2:
            if abs(categories[0].amount) != abs(accounts[0].amount):
                return transaction
            payer, payee = sorted(categories, key=lambda c: c.amount)
            if payee.to.ishidden():
                result = Purchase()
                result.from_category = payer.to
            elif payer.to.ishidden():
                result = Inflow()
                result.to_category = payee.to
            else:
                return transaction
        elif transaction.categories.count() == 0:
            result = Transfer()
        else:
            return transaction
        payer, payee = sorted(accounts, key=lambda c: c.amount)
        result.from_account = payer.to
        result.to_account = payee.to
        result.amount = payee.amount
    else:
        return transaction
    result.id = transaction.id
    result.date = transaction.date
    return result

# Transaction.objects
# .annotate(value_change=Sum('category_parts__amount',
#                             filter=Q(categories__budget_id=budget_id)))
# .exclude(value_change=0)


def transactions_for_budget(budget_id: int):
    filter = (Q(accounts__budget_id=budget_id) |
              Q(categories__budget_id=budget_id))
    qs = (Transaction.objects
          .filter(filter)
          .distinct()
          .order_by('date')
          .prefetch_related('account_parts', 'category_parts',
                            'accounts__budget', 'categories__budget'))
    total = 0
    for transaction in qs:
        for part in transaction.category_parts.all():
            if part.to.budget_id == budget_id:
                total += part.amount
        setattr(transaction, 'running_sum', total)
    return qs


def transactions_for_account(account_id: int):
    qs = (Transaction.objects
          .filter(accounts__id=account_id)
          .distinct()
          .order_by('date')
          .prefetch_related('account_parts', 'category_parts',
                            'accounts__budget', 'categories__budget'))
    total = 0
    for transaction in qs:
        for part in transaction.account_parts.all():
            if part.to_id == account_id:
                total += part.amount
        setattr(transaction, 'running_sum', total)
    return qs


def transactions_for_category(category_id: int):
    qs = (Transaction.objects
          .filter(categories__id=category_id)
          .distinct()
          .order_by('date')
          .prefetch_related('account_parts', 'category_parts',
                            'accounts__budget', 'categories__budget'))
    total = 0
    for transaction in qs:
        for part in transaction.category_parts.all():
            if part.to_id == category_id:
                total += part.amount
        setattr(transaction, 'running_sum', total)
    return qs


def transactions_for_balance(budget_id_1: int, budget_id_2: int):
    filter = (Q(accounts__budget_id=budget_id_1) &
              Q(categories__budget_id=budget_id_2) |
              Q(accounts__budget_id=budget_id_2) &
              Q(categories__budget_id=budget_id_1))
    qs = (Transaction.objects
          .filter(filter)
          .distinct()
          .order_by('date')
          .prefetch_related('account_parts', 'category_parts',
                            'accounts__budget', 'categories__budget'))
    total = 0
    for transaction in qs:
        debts = transaction.debts()
        out = debts.get((budget_id_1, budget_id_2))
        if out:
            total -= out
        into = debts.get((budget_id_2, budget_id_1))
        if into:
            total += into
        setattr(transaction,
                'running_sum', total)
    return qs
