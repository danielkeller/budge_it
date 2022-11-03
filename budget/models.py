from django.db import models

class Budget(models.Model):
    name = models.CharField(max_length=100)
    #TODO: owner, currency

class Account(models.Model):
    name = models.CharField(max_length=100)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    #TODO: read/write access

class Category(models.Model):
    name = models.CharField(max_length=100)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE)
    #TODO: read/write access

class Transaction(models.Model):
    date = models.DateField()
    description = models.CharField(max_length=1000)

    # used if the transaction has no parts
    amount = models.BigIntegerField()

    # 'external' is used if 'account' is null
    from_account = models.ForeignKey(Account, null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name='transaction_from')
    from_external = models.CharField(max_length=100, blank=True)
    to_account = models.ForeignKey(Account, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name='transaction_to')
    to_external = models.CharField(max_length=100, blank=True)

class TransactionPart(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    amount = models.BigIntegerField()

# Denormalized running sums to avoid recomputing them all the time

class AccountValue(models.Model):
    of = models.ForeignKey(Account, on_delete=models.CASCADE)
    after = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    value = models.BigIntegerField()

class CategoryValue(models.Model):
    of = models.ForeignKey(Category, on_delete=models.CASCADE)
    after = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    value = models.BigIntegerField()

class OwedValue(models.Model):
    from_budget = models.ForeignKey(Budget, on_delete=models.CASCADE,
                                    related_name='owed_from')
    to_budget = models.ForeignKey(Budget, on_delete=models.CASCADE,
                                  related_name='owed_to')
    after = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    value = models.BigIntegerField()
