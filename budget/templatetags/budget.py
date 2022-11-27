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
    account_amounts = list(account.amount for account in accounts)
    category_amounts = list(category.amount for category in categories)
    parts: list[dict[str, typing.Any]]
    parts = []
    for amount in sorted(account_amounts + category_amounts):
        account = pop_by_amount_(accounts, amount)
        category = pop_by_amount_(categories, amount)
        if account or category:
            parts.append({'from': None, 'to': account,
                          'category': category, 'amount': amount})
    return parts
