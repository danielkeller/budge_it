from dataclasses import dataclass
from typing import Optional, Any, cast
from datetime import date, timedelta
from urllib.parse import urlparse

from django.shortcuts import render
from django.http import (HttpRequest, HttpResponse, HttpResponseRedirect,
                         HttpResponseBadRequest, Http404)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic
from django.contrib.auth.decorators import login_required
from django.urls import reverse, resolve
from django.forms import BoundField
from render_block import render_block_to_string
import cProfile

from .models import (sum_by, date_range, months_between,
                     BaseAccount, Account, Category, Budget,
                     Transaction, Cleared,
                     accounts_overview,  category_balance,
                     Balance, Total, budgeting_transaction,
                     prior_budgeting_transaction)
from .forms import (TransactionForm,
                    BudgetingForm, rename_form, BudgetForm,
                    OnTheGoForm,
                    ReorderingFormSet, AccountManagementFormSet,
                    CategoryManagementFormSet, CurrencyManagementFormSet)


def profileit(func: Any):
    def wrapper(*args: Any, **kwargs: Any):
        datafn = func.__name__ + ".profile"  # Name the data file sensibly
        prof = cProfile.Profile()
        retval = prof.runcall(func, *args, **kwargs)
        prof.dump_stats(datafn)
        return retval

    return wrapper


def hx_current_url(request: HttpRequest):
    """Adds to the context the URL that the user is actually looking at"""
    return {'current_url':
            request.headers.get('HX-Current-URL') or request.get_full_path()}


@login_required
def index(request: HttpRequest):
    # type: ignore
    return HttpResponseRedirect(request.user.budget.get_absolute_url())


def _get_allowed_budget_or_404(request: HttpRequest, id: int):
    budget = get_object_or_404(Budget, id=id)
    if not budget.view_permission(request.user):
        raise Http404()
    return budget


def _get_allowed_account_or_404(request: HttpRequest, id: int):
    try:
        account = BaseAccount.get(id)
    except BaseAccount.DoesNotExist:
        raise Http404()
    if not account.budget.view_permission(request.user):
        raise Http404()
    return account


def _get_allowed_object_or_404(request: HttpRequest, budget: Budget,
                               name: str | int):
    try:
        id = int(name)
    except ValueError:
        return Total(budget, cast(str, name))
    return _get_allowed_account_or_404(request, id)


def _get_allowed_transaction_or_404(budget: Budget,
                                    transaction_id: int | str | None):
    if not transaction_id:
        return None
    budget = budget.main_budget()
    transaction = Transaction.objects.get_for(budget, int(transaction_id))
    if not transaction:
        raise Http404()
    return transaction


def reverse_all(budget_id: int, account_id: str | int | None = None,
                transaction_id: str | int | None = None):
    return reverse('all', args=[arg for arg in (
        budget_id, account_id, transaction_id) if arg])


@login_required
def all(request: HttpRequest, budget_id: int,
        account_id: str | int | None = None,
        transaction_id: str | int | None = None):
    budget = _get_allowed_budget_or_404(request, budget_id)
    context = {'budget': budget, 'today': date.today()}

    transaction_id = transaction_id or request.GET.get('transaction')
    transaction = _get_allowed_transaction_or_404(budget, transaction_id)
    form = TransactionForm(budget, prefix="tx", instance=transaction)
    context |= {'transaction_id': transaction_id, 'form': form}

    if request.headers.get('HX-Target') == 'transaction':
        response = render(request, 'budget/partials/edit.html', context)
        response['HX-Replace-Url'] = reverse_all(
            budget_id, account_id, transaction_id)
        return response

    if account_id:
        account = _get_allowed_object_or_404(request, budget, account_id)
        entries, balance = account.transactions()
        context |= {'account': account, 'entries': entries, 'balance': balance}

    if request.headers.get('HX-Target') == 'account':
        return render(request, 'budget/partials/account.html', context)

    accounts, categories, debts = accounts_overview(budget)
    totals = sum_by((category.currency, category.balance)
                    for category in categories)
    context |= {'accounts': accounts, 'categories': categories,
                'debts': debts, 'totals': totals,
                'edit': _edit_context(budget)}

    return render(request, 'budget/all.html', context)


def save(request: HttpRequest, budget_id: int, account_id: str | int,
         transaction_id: str | int | None = None):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    budget = _get_allowed_budget_or_404(request, budget_id)
    transaction = _get_allowed_transaction_or_404(budget, transaction_id)
    form = TransactionForm(budget, prefix="tx", instance=transaction,
                           data=request.POST)
    if not form.is_valid():
        raise ValueError(form.errors, form.formset.non_form_errors())
    transaction = form.save()
    transaction_id = transaction.id
    if transaction_id:
        budget.initial_currency = transaction.first_currency()
        budget.save()
    response = all(request, budget_id, account_id, transaction_id)
    response['HX-Replace-Url'] = reverse_all(
        budget_id, account_id, transaction_id)
    return response


def add_to_account(request: HttpRequest, account_id: int, transaction_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    account = _get_allowed_account_or_404(request, account_id)
    transaction = Transaction.objects.get_for(
        account.budget, transaction_id)
    if not transaction:
        raise Http404()
    transaction.change_inbox_to(account)
    context = {'entries': account.transactions(), 'account': account}
    return HttpResponse(render_block_to_string(
        'budget/partials/account.html', 'list-contents', context, request))


def _edit_context(budget: Budget):
    friends = dict(budget.friends.values_list('id', 'name'))
    payees = dict(Budget.objects.filter(payee_of=budget.owner())
                                .values_list('id', 'name'))
    # Closed?
    accounts = budget.account_set.exclude(name='')
    categories = budget.category_set.exclude(name='')
    data = {
        'budget': budget.id,
        'accounts': (dict(accounts.values_list('id', 'currency'))
                     | dict(categories.values_list('id', 'currency'))),
        'budgets': {budget.id: budget.name, **friends, **payees},
        'friends': friends,
    }
    return {'friends': friends, 'payees': payees,
            'accounts': accounts, 'categories': categories,
            'data': data}


@login_required
def overview(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    accounts, categories, debts = accounts_overview(budget)
    totals = sum_by((category.currency, category.balance)
                    for category in categories)
    formset = ReorderingFormSet(queryset=categories)
    context = {'accounts': accounts, 'categories': categories, 'debts': debts,
               'today': date.today(),
               'totals': totals, 'formset': formset, 'budget': budget}
    return render(request, 'budget/overview.html', context)


@login_required
def reorder(request: HttpRequest, budget_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    budget = _get_allowed_budget_or_404(request, budget_id)
    formset = ReorderingFormSet(queryset=budget.category_set.all(),
                                data=request.POST)
    if formset.is_valid():
        formset.save()
    else:
        raise ValueError(formset.errors())
    return HttpResponseRedirect(budget.get_absolute_url())


@login_required
def onthego(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    if request.method == 'POST':
        form = OnTheGoForm(budget=budget, data=request.POST)
        if form.is_valid():
            transaction = form.save()
            return HttpResponseRedirect(reverse('otg', args=(budget_id,))
                                        + f'?confirm={transaction.id}')
    else:
        form = OnTheGoForm(budget=budget)
    context = {'budget': budget, 'form': form}
    return render(request, 'budget/onthego.html', context)


@login_required
def balance(request: HttpRequest, currency: str, budget_id_1: int, budget_id_2: int):
    budget = _get_allowed_budget_or_404(request, budget_id_1)
    # FIXME: This leaks the existence of budget ids
    other = get_object_or_404(Budget, id=budget_id_2)
    account = Balance(budget, other, currency)
    context = {'entries': account.transactions(), 'account': account,
               'form': None}
    return render(request, 'budget/account.html', context)


# @profileit
@login_required
def account(request: HttpRequest, account_id: int):
    account = _get_allowed_account_or_404(request, account_id)
    if request.method == 'POST':
        form = rename_form(instance=account, data=request.POST)
        if form and form.is_valid():
            form.save()
        return HttpResponseRedirect(request.get_full_path())
    form = rename_form(instance=account)
    data = {'budget': account.budget_id}
    entries, balance = account.transactions()
    context = {'entries': entries, 'account': account, 'balance': balance,
               'form': form, 'data': data}
    return render(request, 'budget/account.html', context)


@login_required
def clear(request: HttpRequest, account_id: int, transaction_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    account = _get_allowed_account_or_404(request, account_id)
    if not isinstance(account, Account) or not account.clearable:
        return HttpResponseBadRequest('Wrong kind of account')
    transaction = Transaction.objects.get_for(
        account.budget, transaction_id)
    if not transaction:
        raise Http404()
    if 'clear' in request.POST:
        transaction.cleared_account.add(account)
    else:
        transaction.cleared_account.remove(account)
    entries, balance = account.transactions()
    context = {'entries': entries, 'balance': balance, 'account': account}
    return render(request, 'budget/partials/account_sums.html', context)


@login_required
def reconcile(request: HttpRequest, account_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    account = _get_allowed_account_or_404(request, account_id)
    if not isinstance(account, Account) or not account.clearable:
        return HttpResponseBadRequest('Wrong kind of account')
    Cleared.objects.filter(account=account).update(reconciled=True)
    entries, balance = account.transactions()
    context = {'entries': entries, 'balance': balance, 'account': account}
    return render(request, 'budget/partials/account_sums.html', context)


def account_form(request: HttpRequest, budget_id: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    queryset = Account.objects.none()
    formset = AccountManagementFormSet(
        instance=budget, queryset=queryset, prefix="accounts")
    formset.min_num = number + 1  # type: ignore
    context = {'budget': budget,
               'account_formset': formset, 'form': formset.forms[number]}
    return HttpResponse(render_block_to_string('budget/manage.html', 'account-form', context, request))


def category_form(request: HttpRequest, budget_id: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    queryset = Category.objects.none()
    formset = CategoryManagementFormSet(
        instance=budget, queryset=queryset, prefix="categories")
    formset.min_num = number + 1  # type: ignore
    context = {'budget': budget,
               'category_formset': formset, 'form': formset.forms[number]}
    return HttpResponse(render_block_to_string('budget/manage.html', 'category-form', context, request))


def currency_form(request: HttpRequest, number: int):
    formset = CurrencyManagementFormSet(prefix="currencies")
    formset.min_num = number + 1  # type: ignore
    context = {'currency_formset': formset, 'form': formset.forms[number]}
    return HttpResponse(render_block_to_string('budget/manage.html', 'currency-form', context, request))


def manage_accounts(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    categories = (budget.category_set.exclude(name='')
                  .order_by('order', 'group', 'name'))
    accounts = (budget.account_set.exclude(name='')
                .order_by('order', 'group', 'name'))
    currencies = budget.category_set.filter(name='', closed=False)
    if request.method == 'POST':
        budget_form = BudgetForm(instance=budget, data=request.POST,
                                 prefix="budget")
        category_formset = CategoryManagementFormSet(
            instance=budget, queryset=categories, data=request.POST,
            prefix="categories")
        account_formset = AccountManagementFormSet(
            instance=budget, queryset=accounts, data=request.POST,
            prefix="accounts")
        currency_formset = CurrencyManagementFormSet(
            instance=budget, queryset=currencies, data=request.POST,
            prefix="currencies")
        if (category_formset.is_valid() and account_formset.is_valid()
                and budget_form.is_valid() and currency_formset.is_valid()):
            category_formset.save()
            account_formset.save()
            currency_formset.save()
            budget_form.save()
            return HttpResponseRedirect(request.get_full_path())
    else:
        budget_form = BudgetForm(instance=budget, prefix="budget")
        category_formset = CategoryManagementFormSet(
            instance=budget, queryset=categories, prefix="categories")
        account_formset = AccountManagementFormSet(
            instance=budget, queryset=accounts, prefix="accounts")
        currency_formset = CurrencyManagementFormSet(
            instance=budget, queryset=currencies, prefix="currencies")
    context = {'budget': budget, 'budget_form': budget_form,
               'category_formset': category_formset,
               'account_formset': account_formset,
               'currency_formset': currency_formset}
    return render(request, 'budget/manage.html', context)


def part_form(request: HttpRequest, budget_id: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    budget = budget.main_budget()
    form = TransactionForm(budget, prefix="tx")
    form.formset.min_num = number + 1  # type: ignore
    context = {'budget': budget,
               'part': form.formset.forms[number], 'part_index': number,
               'form': form}
    return HttpResponse(render_block_to_string(
        'budget/edit.html', 'edit-part', context, request))


def row_form(request: HttpRequest, budget_id: int,
             part_index: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    budget = budget.main_budget()
    form = TransactionForm(budget, prefix="tx")
    form.formset.min_num = part_index + 1  # type: ignore
    part = form.formset.forms[part_index]
    # Extra is 1
    part.formset.min_num = number + 1 - 1  # type: ignore
    context = {'budget': budget,
               'row': part.formset.forms[number],
               'part': part, 'part_index': part_index}
    return HttpResponse(render_block_to_string(
        'budget/edit.html', 'edit-row', context, request))


@login_required
def edit(request: HttpRequest, budget_id: int,
         transaction_id: Optional[int] = None):
    budget = _get_allowed_budget_or_404(request, budget_id)
    budget = budget.main_budget()
    if transaction_id == None:
        transaction = None
    else:
        transaction = Transaction.objects.get_for(budget, transaction_id)
        if not transaction:
            raise Http404()

    if transaction and transaction.kind == Transaction.Kind.BUDGETING:
        return HttpResponseRedirect(reverse(
            'budget',
            args=(budget_id, transaction.date.year, transaction.date.month)))

    if request.method == 'POST':
        form = TransactionForm(budget, prefix="tx", instance=transaction,
                               data=request.POST)
        if form.is_valid():
            instance: Transaction = form.save()
            if instance.id:
                budget.initial_currency = instance.first_currency()
                budget.save()
            if 'back' in request.GET:
                if instance.id:
                    back = f"{request.GET['back']}?t={instance.id}"
                else:
                    back = f"{request.GET['back']}"
            else:
                back = '/'
            return HttpResponseRedirect(back)
    else:
        form = TransactionForm(budget, prefix="tx", instance=transaction)

    friends = dict(budget.friends.values_list('id', 'name'))
    payees = dict(Budget.objects.filter(payee_of=budget.owner())
                                .values_list('id', 'name'))
    # Closed?
    accounts = budget.account_set.exclude(name='')
    categories = budget.category_set.exclude(name='')
    data = {
        'budget': budget.id,
        'transaction': transaction_id,
        'accounts': (dict(accounts.values_list('id', 'currency'))
                     | dict(categories.values_list('id', 'currency'))),
        'budgets': {budget.id: budget.name, **friends, **payees},
        'friends': friends,
    }
    context = {'form': form,
               'budget': budget, 'friends': friends, 'payees': payees,
               'accounts': accounts, 'categories': categories,
               'transaction_id': transaction_id,
               'data': data}
    return render(request, 'budget/edit.html', context)


@login_required
def delete(request: HttpRequest, budget_id: int, transaction_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    budget = _get_allowed_budget_or_404(request, budget_id)
    transaction = get_object_or_404(Transaction, id=transaction_id)
    with atomic():
        if not any([part.set_entries(budget, {}, {})
                    for part in transaction.parts.all()]):
            transaction.delete()
    return HttpResponseRedirect(request.GET.get('back') or '/')


@dataclass
class BudgetRow:
    category: Category
    field: BoundField

    @property
    def total(self):
        return self.category.balance + self.category.change


@login_required
def budget(request: HttpRequest, budget_id: int, year: int, month: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    try:
        budget_date = date(year, month, 1)
    except ValueError:
        raise Http404()

    min_date, max_date = date_range(budget)
    years = range(min_date.year, max_date.year + 2)
    months = months_between(date(year, 1, 1), date(year, 12, 31))

    end_date = (budget_date + timedelta(days=31)
                ).replace(day=1) - timedelta(days=1)

    # Make sure these exist first
    for currency, in budget.category_set.values_list('currency').distinct():
        budget.get_inbox(Category, currency)

    # Factor out into models.py?
    balances = category_balance(budget, budget_date)
    transaction = budgeting_transaction(budget, budget_date)
    if transaction:
        entries = transaction.parts.get().categoryentry_set.entries()
    else:
        entries = {}

    shown = {category for category in balances
             if category.balance or category.change or category in entries
             or (not category.is_inbox() and not category.closed)}
    currencies = {category.currency for category in shown}
    inboxes = {category for category in balances
               if category.is_inbox() and category.currency in currencies}
    shown |= inboxes

    initial = {'date': budget_date}
    if request.method == 'POST':
        form = BudgetingForm(categories=shown, instance=transaction,
                             data=request.POST)
        if form.is_valid():
            with atomic():
                form.save_entries(budget)
            return HttpResponseRedirect(
                request.GET.get('back', request.get_full_path()))
    else:
        form = BudgetingForm(categories=shown, instance=transaction,
                             initial=initial)
    rows = [BudgetRow(category, form[str(category.id)])
            for category in balances if category in shown]

    prior = prior_budgeting_transaction(budget, budget_date)

    data = {'inboxes': [inbox.id for inbox in inboxes]}
    context = {'rows': rows, 'form': form, 'budget': budget,
               'current_year': year, 'current_month': month,
               'budget_date': budget_date, 'end_date': end_date,
               'years': years, 'months': months,
               'prior': prior,
               'data': data}
    return render(request, 'budget/budget.html', context)


@login_required
def copy_budget(request: HttpRequest, budget_id: int, transaction_id: int,
                year: int, month: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    budget = _get_allowed_budget_or_404(request, budget_id)
    prior = Transaction.objects.get_for(budget, transaction_id)
    if not prior:
        raise Http404()
    try:
        budget_date = date(year, month, 1)
    except ValueError:
        raise Http404()
    prior.copy_to(budget_date)
    return HttpResponseRedirect(reverse('budget', args=(budget_id, year, month)))
