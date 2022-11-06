from django.db import models
from django.db.models import Q, Manager
from django.urls import reverse
import copy

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

    def __str__(self):
        if self.name:
            return self.budget.name + " - " + str(self.name)
        else:
            return self.budget.name

class Account(BaseAccount):
    """Accounts describe the physical ownership of money."""
    def kind(self):
        return 'account'
    def get_absolute_url(self):
        return reverse('account', kwargs={'account_id': self.id})

class Category(BaseAccount):
    """Categories describe the conceptual ownership of money."""
    def kind(self):
        return 'category'
    def get_absolute_url(self):
        return "/404/"

class Transaction(models.Model):
    id: models.BigAutoField
    date = models.DateField()
    description = models.CharField(max_length=1000)
    transactionpart_set: Manager['TransactionPart']

    def __str__(self):
        return self.description[0:100]

class TransactionPart(models.Model):
    id: models.BigAutoField
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    amount = models.BigIntegerField()

    from_account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                     related_name='transaction_from')
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                   related_name='transaction_to')
    from_category = models.ForeignKey(Category, on_delete=models.PROTECT,
                                      related_name='transaction_from')
    to_category = models.ForeignKey(Category, on_delete=models.PROTECT,
                                    related_name='transaction_to')
    
    def flipped(self):
        new = copy.copy(self)
        new.from_account=self.to_account
        new.from_category=self.to_category
        new.to_account=self.from_account
        new.to_category=self.from_category
        new.amount=-self.amount
        return new

    def make_to_account(self, account_id: int):
        if (self.to_category.id == account_id
            or self.to_account.id == account_id):
            return self
        if (self.from_category.id == account_id
            or self.from_account.id == account_id):
            return self.flipped()
        return self

    def make_positive(self):
        if self.amount < 0:
            return self.flipped()
        return self

def transactions_for_budget(budget_id: int):
    filter = (Q(transactionpart__from_account__budget__id=budget_id) |
              Q(transactionpart__to_account__budget__id=budget_id) |
              Q(transactionpart__from_category__budget__id=budget_id) |
              Q(transactionpart__to_category__budget__id=budget_id))
    related = ['transactionpart_set__from_account__budget',
               'transactionpart_set__to_account__budget',
               'transactionpart_set__from_category__budget',
               'transactionpart_set__to_category__budget']
    qs = (Transaction.objects
        .filter(filter)
        .distinct()
        .order_by('date')
        .prefetch_related(*related))
    total = 0
    for transaction in qs:
        for part in transaction.transactionpart_set.all():
            if part.from_category.budget.id == budget_id:
                total -= part.amount
            if part.to_category.budget.id == budget_id:
                total += part.amount
            setattr(part, 'running_sum', total)
    return qs

def transactions_for_account(account_id: int):
    filter = (Q(transactionpart__from_account__id=account_id) |
              Q(transactionpart__to_account__id=account_id))
    related = ['transactionpart_set__from_account__budget',
               'transactionpart_set__to_account__budget',
               'transactionpart_set__from_category__budget',
               'transactionpart_set__to_category__budget']
    qs = (Transaction.objects
        .filter(filter)
        .distinct()
        .order_by('date')
        .prefetch_related(*related))
    total = 0
    for transaction in qs:
        for part in transaction.transactionpart_set.all():
            if part.from_account.id == account_id:
                total -= part.amount
            if part.to_account.id == account_id:
                total += part.amount
            setattr(part, 'running_sum', total)
    return qs
