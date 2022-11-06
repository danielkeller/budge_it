from django import template
from budget import models

register = template.Library()

@register.inclusion_tag('budget/account_in_budget.html')
def account_in_budget(account: models.BaseAccount, budget_id: int):
    return {'account': account, 'budget_id': budget_id}
