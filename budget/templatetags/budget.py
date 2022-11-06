from django import template
from budget import models
import typing

register = template.Library()

@register.inclusion_tag('budget/account_in_budget.html')
def account_in_budget(account: models.BaseAccount, budget_id: int):
    return {'account': account, 'budget_id': budget_id}

# @register.filter
# def make_to_account(value: models.TransactionPart, account_id: int):
#     return value.make_to_account(account_id)

T = typing.TypeVar('T', bound=models.TransactionPart)
def pop_by_amount_(parts: 'set[T]', amount: int) -> typing.Optional[T]:
    try:
        result = next((part for part in parts if part.amount == amount))
        parts.discard(result)
        return result
    except StopIteration:
        return None

@register.filter
def transaction_display(value: models.Transaction):
    accounts = set(value.account_parts.all())
    categories = set(value.category_parts.all())
    amounts = sorted(list(abs(account.amount) for account in accounts))
    parts: list[dict[str, typing.Any]]
    parts = []
    for amount in amounts:
        from_account = pop_by_amount_(accounts, -amount)
        to_account = pop_by_amount_(accounts, amount)
        from_category = pop_by_amount_(categories, -amount)
        to_category = pop_by_amount_(categories, amount)
        if from_category is None or from_category.to.ishidden():
            category = to_category
        elif to_category is None or to_category.to.ishidden():
            category = from_category
        else:
            category = None
            categories.update((from_category, to_category))
        if from_account is None and to_account is None and category is None:
            continue
        parts.append({'from': from_account, 'to': to_account,
              'category': category, 'amount': amount})
    for category in categories:
        parts.append({'from': None, 'to': None,
            'category': category, 'amount': category.amount})

    return parts
