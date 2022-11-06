from django.db import models
from django.db.models import Q, Manager

class Budget(models.Model):
    id: models.BigAutoField
    name = models.CharField(max_length=100)
    # May be marked as external
    #TODO: owner, currency

    def __str__(self):
        return self.name

class BaseAccount(models.Model):
    class Meta: # type: ignore
        abstract = True
    id: models.BigAutoField
    name = models.CharField(max_length=100, blank=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    #TODO: read/write access

    def __str__(self):
        if self.name:
            return self.budget.name + " - " + str(self.name)
        else:
            return self.budget.name

class Account(BaseAccount):
    """Accounts describe the physical ownership of money."""

class Category(BaseAccount):
    """Categories describe the conceptual ownership of money."""

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
