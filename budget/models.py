from django.db import models

class Budget(models.Model):
    name = models.CharField(max_length=100)
    # May be marked as external
    #TODO: owner, currency

class Account(models.Model):
    """Accounts describe the physical ownership of money."""
    name = models.CharField(max_length=100)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    #TODO: read/write access

class Category(models.Model):
    """Categories describe the conceptual ownership of money."""
    name = models.CharField(max_length=100)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    #TODO: read/write access

class Transaction(models.Model):
    date = models.DateField()
    description = models.CharField(max_length=1000)

    from_account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                     related_name='transaction_from')
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT,
                                   related_name='transaction_to')

class TransactionPart(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    amount = models.BigIntegerField()

    from_category = models.ForeignKey(Category, on_delete=models.PROTECT,
                                      related_name='transaction_from')
    to_category = models.ForeignKey(Category, on_delete=models.PROTECT,
                                    related_name='transaction_to')
