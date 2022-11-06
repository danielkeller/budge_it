from django.db import models
from django.db.models import Q
from django.urls import reverse

class Budget(models.Model):
    id: models.BigAutoField
    name = models.CharField(max_length=100)
    # May be marked as external
    #TODO: owner, currency

    def __str__(self):
        return self.name
    def get_absolute_url(self):
        return reverse('budget', kwargs={'budget_id': self.id})

class BaseAccount(models.Model):
    class Meta: # type: ignore
        abstract = True
    id: models.BigAutoField
    name = models.CharField(max_length=100, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    budget_id: int # Sigh
    #TODO: read/write access

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

class Category(BaseAccount):
    """Categories describe the conceptual ownership of money."""
    class Meta: # type: ignore
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
        return self.description[0:100]

class TransactionPart(models.Model):
    class Meta: # type: ignore
        abstract = True
        constraints = [models.UniqueConstraint(fields=["transaction", "to"],
                                               name="m2m_%(class)s")]
    transaction: models.ForeignKey['Transaction']
    amount = models.BigIntegerField()
    to: models.ForeignKey[BaseAccount]
    to_id: int

class TransactionAccountPart(TransactionPart):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="account_parts")
    to = models.ForeignKey(Account, on_delete=models.PROTECT,
                           related_name="entries") # type: ignore

class TransactionCategoryPart(TransactionPart):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE,
                                    related_name="category_parts")
    to = models.ForeignKey(Category, on_delete=models.PROTECT,
                           related_name="entries") # type: ignore

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
