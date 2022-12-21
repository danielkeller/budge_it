from typing import Optional

from django.db.models import Q
from django.shortcuts import render
from django.http import (HttpRequest, HttpResponse, HttpResponseRedirect,
                         HttpResponseBadRequest)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic

from .models import (
    transactions_for_budget, transactions_for_balance, entries_for,
    accounts_overview,
    Account, Category, Budget, Transaction)
from .forms import TransactionForm, TransactionPartFormSet


def index(request: HttpRequest):
    return HttpResponse("TODO")


def overview(request: HttpRequest, budget_id: int):
    get_object_or_404(Budget, id=budget_id)
    accounts, categories, debts = accounts_overview(budget_id)
    context = {'accounts': accounts, 'categories': categories, 'debts': debts,
               'budget_id': budget_id}
    return render(request, 'budget/overview.html', context)


def budget(request: HttpRequest, budget_id: int):
    transactions = transactions_for_budget(budget_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)


def account(request: HttpRequest, account_id: int):
    account = get_object_or_404(Account, id=account_id)
    data = {'budget': account.budget_id}
    context = {'entries': entries_for(
        account), 'account': account, 'data': data}
    return render(request, 'budget/account.html', context)


def category(request: HttpRequest, category_id: int):
    category = get_object_or_404(Category, id=category_id)
    data = {'budget': category.budget_id}
    context = {'entries': entries_for(
        category), 'account': category, 'data': data}
    return render(request, 'budget/account.html', context)


def balance(request: HttpRequest, budget_id_1: int, budget_id_2: int):
    get_object_or_404(Budget, id=budget_id_1)
    get_object_or_404(Budget, id=budget_id_2)
    transactions = transactions_for_balance(budget_id_1, budget_id_2)
    context = {'transactions': transactions, 'budget_id': budget_id_1}
    return render(request, 'budget/budget.html', context)


def edit(request: HttpRequest, budget_id: int,
         transaction_id: Optional[int] = None):
    budget = get_object_or_404(Budget, id=budget_id)
    if transaction_id == None:
        transaction = None
    else:
        transaction = get_object_or_404(Transaction, id=transaction_id)

    if request.method == 'POST':
        form = TransactionForm(instance=transaction, data=request.POST)
        formset = TransactionPartFormSet(
            budget, prefix="tx", instance=transaction, data=request.POST)
        if form.is_valid() and formset.is_valid():
            with atomic():
                instance = form.save()
                formset.save(instance=instance)
            return HttpResponseRedirect(request.GET['back'])
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


def delete(request: HttpRequest, transaction_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    get_object_or_404(Transaction, id=transaction_id).delete()
    return HttpResponseRedirect(request.GET['next'])
