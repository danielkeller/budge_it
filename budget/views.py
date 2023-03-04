from typing import Optional, Type, Any
from datetime import date, timedelta

from django.db.models import Q, Min, Max
from django.shortcuts import render
from django.http import (HttpRequest, HttpResponse, HttpResponseRedirect,
                         HttpResponseBadRequest, Http404)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic
from django.contrib.auth.decorators import login_required

from .models import (
    transactions_for_budget, transactions_for_balance, entries_for,
    accounts_overview, category_history,
    BaseAccount, Account, Category, Budget, Transaction)
from .forms import (TransactionForm, TransactionPartFormSet,
                    BudgetingFormSet, rename_form)


def index(request: HttpRequest):
    return HttpResponse("TODO")


def _get_allowed_budget_or_404(request: HttpRequest, budget_id: int):
    budget = get_object_or_404(Budget, id=budget_id)
    if request.user != budget.owner:
        raise Http404()
    return budget


@login_required
def overview(request: HttpRequest, budget_id: int):
    _get_allowed_budget_or_404(request, budget_id)
    accounts, categories, debts = accounts_overview(budget_id)
    total = sum(category.balance for category in categories)
    context = {'accounts': accounts, 'categories': categories, 'debts': debts,
               'total': total, 'budget_id': budget_id}
    return render(request, 'budget/overview.html', context)


@login_required
def budget(request: HttpRequest, budget_id: int):
    transactions = transactions_for_budget(budget_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)


@login_required
def balance(request: HttpRequest, budget_id_1: int, budget_id_2: int):
    _get_allowed_budget_or_404(request, budget_id_1)
    get_object_or_404(Budget, id=budget_id_2)
    # FIXME: Display other people's transaction parts as a total instead of using
    # account_in_budget
    transactions = transactions_for_balance(budget_id_1, budget_id_2)
    context = {'transactions': transactions, 'budget_id': budget_id_1}
    return render(request, 'budget/budget.html', context)


@login_required
def account(request: HttpRequest, account_id: int):
    return _base_account(request, Account, account_id)


@login_required
def category(request: HttpRequest, category_id: int):
    return _base_account(request, Category, category_id)


def _base_account(request: HttpRequest, type: Type[BaseAccount], id: int):
    account = get_object_or_404(type, id=id)
    if request.user != account.budget.owner:
        raise Http404()
    if request.method == 'POST':
        form = rename_form(instance=account, data=request.POST)
        if form.is_valid():
            form.save()
        return HttpResponseRedirect(request.get_full_path())
    form = rename_form(instance=account)
    data = {'budget': account.budget_id}
    context = {'entries': entries_for(account), 'account': account,
               'form': form, 'data': data}
    return render(request, 'budget/account.html', context)


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
    if transaction_id == None:
        transaction = None
    else:
        transaction = get_object_or_404(Transaction, id=transaction_id)
        if not transaction.visible_from(budget_id):
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

    accounts = [(account.name_in_budget(budget_id), str(account.id))
                for account in Account.objects.filter(
                    Q(budget_id=budget_id) | Q(name=""))]
    categories = [(category.name_in_budget(budget_id), str(category.id))
                  for category in Category.objects.filter(
        Q(budget_id=budget_id) | Q(name=""))]
    data = {
        'budget': budget_id,
        'accounts': accounts, 'categories': categories,
        'category_budget': dict(
            Category.objects.values_list('id', 'budget_id')),
        'account_budget': dict(
            Account.objects.values_list('id', 'budget_id')),
        'budget': {budget.id: budget.name for budget in Budget.objects.all()},
        'external': {account.id: account.budget.get_hidden(Category).id
                     for account
                     in Account.objects.filter(name='')
                     .prefetch_related('budget__category_set')}
    }
    context = {'formset': formset, 'form': form,
               'transaction_id': transaction_id, 'data': data}
    return render(request, 'budget/edit.html', context)


@login_required
def delete(request: HttpRequest, transaction_id: int):
    # FIXME: Delete from the perspective of one budget
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    get_object_or_404(Transaction, id=transaction_id).delete()
    return HttpResponseRedirect(request.GET.get('back', '/'))


def _months_between(start: date, end: date):
    start = start.replace(day=1)
    while start <= end:
        yield start
        start = (start + timedelta(days=31)).replace(day=1)


@login_required
def history(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    inbox = budget.category_set.get(name='')

    history = category_history(budget_id)
    categories = budget.category_set.order_by('name')
    range = (Transaction.objects
             .filter(categories__budget=budget)
             .aggregate(Max('date'), Min('date')))
    months = list(_months_between(range['date__min'], range['date__max']))
    prev_month = (months[0] - timedelta(days=1)).replace(day=1)
    next_month = (months[-1] + timedelta(days=31)).replace(day=1)

    # Initial is supposed to be the same between GET and POST, so there is
    # theoretically a race condition here if someone adds a transaction. At
    # worst it will create a new empty budgeting transaction though.
    if request.method == 'POST':
        formset = BudgetingFormSet(budget, dates=months, data=request.POST)
        if formset.is_valid():
            formset.save()
            return HttpResponseRedirect(
                request.GET.get('back', request.get_full_path()))
    else:
        formset = BudgetingFormSet(budget, dates=months)

    cells = {(entry['month'], entry['to']): entry['total']
             for entry in history}
    grid = [(category,
             [(formset.forms_by_date[month][str(category.id)],
               cells.get((month, category.id)))
              for month in months])
            for category in categories]

    data = {'prev_month': prev_month, 'next_month': next_month,
            'inbox': str(inbox.id)}
    context: 'dict[str, Any]'
    context = {'budget_id': budget_id, 'formset': formset,
               'months': months, 'grid': grid, 'data': data}
    return render(request, 'budget/history.html', context)
