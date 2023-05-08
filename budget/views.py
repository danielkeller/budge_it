from typing import Optional, Type, Any
from datetime import date, timedelta

from django.db.models import Min, Max
from django.shortcuts import render
from django.http import (HttpRequest, HttpResponseRedirect,
                         HttpResponseBadRequest, Http404)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic
from django.contrib.auth.decorators import login_required
import cProfile

from .models import (
    entries_for_balance, entries_for,
    accounts_overview, category_history, sum_by,
    BaseAccount, Account, Category, Budget, Transaction, Balance)
from .forms import (TransactionForm, TransactionPartFormSet,
                    BudgetingFormSet, rename_form,
                    ReorderingFormSet, AccountManagementFormSet,
                    CategoryManagementFormSet)


def profileit(func: Any):
    def wrapper(*args: Any, **kwargs: Any):
        datafn = func.__name__ + ".profile"  # Name the data file sensibly
        prof = cProfile.Profile()
        retval = prof.runcall(func, *args, **kwargs)
        prof.dump_stats(datafn)
        return retval

    return wrapper


@login_required
def index(request: HttpRequest):
    # type: ignore
    return HttpResponseRedirect(request.user.budget.get_absolute_url())


def _get_allowed_budget_or_404(request: HttpRequest, budget_id: int):
    budget = get_object_or_404(Budget, id=budget_id)
    if not budget.view_permission(request.user):
        raise Http404()
    return budget


@login_required
def overview(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    accounts, categories, debts = accounts_overview(budget_id)
    totals = sum_by((category.currency, category.balance)
                    for category in categories)
    formset = ReorderingFormSet(queryset=categories)
    context = {'accounts': accounts, 'categories': categories, 'debts': debts,
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
def balance(request: HttpRequest, currency: str, budget_id_1: int, budget_id_2: int):
    budget = _get_allowed_budget_or_404(request, budget_id_1)
    other = get_object_or_404(Budget, id=budget_id_2)
    account = Balance(budget, other, currency)
    entries = entries_for_balance(account)
    # print(account, list(entries))
    data = {'budget': budget.id}
    context = {'entries': entries, 'account': account,
               'form': None, 'data': data}
    return render(request, 'budget/account.html', context)


# @profileit
@login_required
def account(request: HttpRequest, account_id: int):
    return _base_account(request, Account, account_id)


@login_required
def category(request: HttpRequest, category_id: int):
    return _base_account(request, Category, category_id)


def _base_account(request: HttpRequest, type: Type[BaseAccount], id: int):
    account = get_object_or_404(type, id=id)
    budget = account.budget
    if not budget.view_permission(request.user):
        raise Http404()
    if request.method == 'POST':
        form = rename_form(instance=account, data=request.POST)
        if form and form.is_valid():
            form.save()
        return HttpResponseRedirect(request.get_full_path())
    form = rename_form(instance=account)
    data = {'budget': budget.id}
    context = {'entries': entries_for(account), 'account': account,
               'form': form, 'data': data}
    return render(request, 'budget/account.html', context)


def manage_accounts(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    categories = (budget.category_set.exclude(name='')
                  .order_by('order', 'group', 'name'))
    accounts = (budget.account_set.exclude(name='')
                .order_by('order', 'group', 'name'))
    if request.method == 'POST':
        category_formset = CategoryManagementFormSet(
            queryset=categories, data=request.POST, prefix="category")
        account_formset = AccountManagementFormSet(
            queryset=accounts, data=request.POST, prefix="accounts")
        if category_formset.is_valid() and account_formset.is_valid():
            category_formset.save()
            account_formset.save()
            return HttpResponseRedirect(budget.get_absolute_url())
    else:
        category_formset = CategoryManagementFormSet(
            queryset=categories, prefix="category")
        account_formset = AccountManagementFormSet(
            queryset=accounts, prefix="accounts")
    context = {'category_formset': category_formset,
               'account_formset': account_formset}
    return render(request, 'budget/manage.html', context)


@login_required
def new_account(request: HttpRequest, budget_id: int):
    _get_allowed_budget_or_404(request, budget_id)
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    account = Account.objects.create(budget_id=budget_id, name="New Account")
    return HttpResponseRedirect(account.get_absolute_url())


@login_required
def new_category(request: HttpRequest, budget_id: int):
    _get_allowed_budget_or_404(request, budget_id)
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    category = Category.objects.create(
        budget_id=budget_id, name="New Category")
    return HttpResponseRedirect(category.get_absolute_url())


@login_required
def edit(request: HttpRequest, budget_id: int,
         transaction_id: Optional[int] = None):
    budget = _get_allowed_budget_or_404(request, budget_id)
    budget = budget.main_budget()
    if transaction_id == None:
        transaction = None
    else:
        transaction = get_object_or_404(Transaction, id=transaction_id)
        if not transaction.visible_from(budget):
            raise Http404()

    if request.method == 'POST':
        form = TransactionForm(instance=transaction, data=request.POST)
        formset = TransactionPartFormSet(
            budget, prefix="tx", instance=transaction, data=request.POST)
        if form.is_valid() and formset.is_valid():
            with atomic():
                instance = form.save()
                formset.save(instance=instance)
            return HttpResponseRedirect(request.GET.get('back', '/'))
    else:
        form = TransactionForm(instance=transaction)
        formset = TransactionPartFormSet(
            budget, prefix="tx", instance=transaction)

    budgets = dict(budget.visible_budgets().values_list('id', 'name'))
    accounts = budget.account_set.exclude(name='')
    categories = budget.category_set.exclude(name='')
    data = {
        'budget': budget.id,
        'accounts': dict(accounts.values_list('id', 'currency')),
        'categories': dict(categories.values_list('id', 'currency')),
        'budgets': {budget.id: budget.name, **budgets},
    }
    context = {'formset': formset, 'form': form,
               'budget': budget, 'budgets': budgets,
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
    transaction.set_parts(budget, {}, {})
    return HttpResponseRedirect(request.GET.get('back', '/'))


def _months_between(start: date, end: date):
    start = start.replace(day=1)
    while start <= end:
        yield start
        start = (start + timedelta(days=31)).replace(day=1)


@login_required
def history(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)

    range = (Transaction.objects
             .filter(categories__budget=budget)
             .aggregate(Max('date'), Min('date')))
    months = list(_months_between(range['date__min'] or date.today(),
                                  range['date__max'] or date.today()))

    categories = budget.category_set.all()
    currencies = categories.values_list('currency', flat=True).distinct()
    # Make sure these are created before creating the form
    inboxes = [budget.get_inbox(Category, currency)
               for currency in currencies]

    # Initial is supposed to be the same between GET and POST, so there is
    # theoretically a race condition here if someone adds a transaction. I
    # don't think it will do anything bad though.
    if request.method == 'POST':
        formset = BudgetingFormSet(budget, dates=months, data=request.POST)
        if formset.is_valid():
            formset.save()
            return HttpResponseRedirect(
                request.GET.get('back', request.get_full_path()))
    else:
        formset = BudgetingFormSet(budget, dates=months)

    history = category_history(budget_id)

    cells = {(entry['month'], entry['to']): entry['total']
             for entry in history}
    grid = [(category,
             [(formset.forms_by_date[month][str(category.id)],
               cells.get((month, category.id)))
              for month in months])
            for category in categories.order_by('name')]

    prev_month = (months[0] - timedelta(days=1)).replace(day=1)
    next_month = (months[-1] + timedelta(days=31)).replace(day=1)

    data = {'prev_month': prev_month, 'next_month': next_month,
            'currencies': dict(categories.values_list('id', 'currency')),
            'inboxes': [str(inbox.id) for inbox in inboxes]}
    context: 'dict[str, Any]'
    context = {'budget_id': budget_id, 'formset': formset,
               'months': months, 'grid': grid, 'data': data}
    return render(request, 'budget/history.html', context)
