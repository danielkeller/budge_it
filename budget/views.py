from typing import Optional, TypeVar, Type

from django.db.models import Q
from django.shortcuts import render
from django.http import (HttpRequest, HttpResponse, HttpResponseRedirect,
                         HttpResponseBadRequest)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic

from .models import (
    transactions_for_budget, transactions_for_balance, entries_for,
    accounts_overview,
    BaseAccount, Account, Category, Budget, Transaction)
from .forms import (TransactionForm, TransactionPartFormSet, rename_form)


def index(request: HttpRequest):
    return HttpResponse("TODO")


def overview(request: HttpRequest, budget_id: int):
    get_object_or_404(Budget, id=budget_id)
    accounts, categories, debts = accounts_overview(budget_id)
    total = sum(account.balance for account in accounts)
    context = {'accounts': accounts, 'categories': categories, 'debts': debts,
               'total': total, 'budget_id': budget_id}
    return render(request, 'budget/overview.html', context)


def budget(request: HttpRequest, budget_id: int):
    transactions = transactions_for_budget(budget_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)


def balance(request: HttpRequest, budget_id_1: int, budget_id_2: int):
    get_object_or_404(Budget, id=budget_id_1)
    get_object_or_404(Budget, id=budget_id_2)
    transactions = transactions_for_balance(budget_id_1, budget_id_2)
    context = {'transactions': transactions, 'budget_id': budget_id_1}
    return render(request, 'budget/budget.html', context)


def account(request: HttpRequest, account_id: int):
    return account_impl(request, Account, account_id)


def category(request: HttpRequest, category_id: int):
    return account_impl(request, Category, category_id)


def account_impl(request: HttpRequest, type: Type[BaseAccount], id: int):
    account = get_object_or_404(type, id=id)
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


def new_account(request: HttpRequest, budget_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    account = Account.objects.create(budget_id=budget_id, name="New Account")
    return HttpResponseRedirect(account.get_absolute_url())


def new_category(request: HttpRequest, budget_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    category = Category.objects.create(
        budget_id=budget_id, name="New Category")
    return HttpResponseRedirect(category.get_absolute_url())


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


def delete(request: HttpRequest, transaction_id: int):
    if request.method != 'POST':
        return HttpResponseBadRequest('Wrong method')
    get_object_or_404(Transaction, id=transaction_id).delete()
    return HttpResponseRedirect(request.GET.get('back', '/'))
