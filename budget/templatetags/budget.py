from budget import models

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def account_in_budget(account: models.BaseAccount, budget: models.Budget):
    if not account:
        return mark_safe("")
    elif account.budget.budget_of_id == budget.owner():
        return format_html('<a href="{}">{}</a>',
                           mark_safe(account.get_absolute_url()),
                           account.name or "Inbox")
    elif account.kind() == 'account':
        return format_html('<i>{}</i>', account.budget.name)
    else:
        return format_html('<a href="{}"><i>{}</i></a>',
                           mark_safe(account.get_absolute_url()),
                           account.budget.name)


@register.filter
def transaction_description(value: models.Transaction,
                            account: models.BaseAccount):
    return value.auto_description(account)
