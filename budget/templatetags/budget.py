from django import template
from budget import models

register = template.Library()


@register.inclusion_tag('budget/account_in_budget.html')
def account_in_budget(account: models.BaseAccount, budget: models.Budget):
    return {'account': account, 'budget': budget}


@register.filter
def tabular(value: models.Transaction, budget: models.Budget):
    return value.tabular(budget)


@register.filter
def transaction_description(value: models.Transaction,
                            account: models.BaseAccount):
    return value.auto_description(account)
