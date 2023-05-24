from dataclasses import dataclass
from typing import Optional, Type, Any
from datetime import date

from django.shortcuts import render
from django.http import (HttpRequest, HttpResponseRedirect,
                         HttpResponseBadRequest, Http404)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic
from django.contrib.auth.decorators import login_required
from django.forms import BoundField
import cProfile

from .models import (sum_by,
                     BaseAccount, Account, Category, Budget, Transaction,
                     accounts_overview, entries_for, category_balance,
                     Balance, entries_for_balance, budgeting_transaction)
from .forms import (TransactionForm, TransactionPartFormSet,
                    BudgetingForm, rename_form, BudgetForm,
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
    accounts, categories, debts = accounts_overview(budget)
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
        budget_form = BudgetForm(instance=budget, data=request.POST,
                                 prefix="budget")
        category_formset = CategoryManagementFormSet(
            queryset=categories, data=request.POST, prefix="category")
        account_formset = AccountManagementFormSet(
            queryset=accounts, data=request.POST, prefix="accounts")
        if (category_formset.is_valid() and account_formset.is_valid()
                and budget_form.is_valid()):
            category_formset.save()
            account_formset.save()
            budget_form.save()
            return HttpResponseRedirect(budget.get_absolute_url())
    else:
        budget_form = BudgetForm(instance=budget, prefix="budget")
        category_formset = CategoryManagementFormSet(
            queryset=categories, prefix="category")
        account_formset = AccountManagementFormSet(
            queryset=accounts, prefix="accounts")
    context = {'budget_form': budget_form,
               'category_formset': category_formset,
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
        transaction = Transaction.objects.get_for(budget, transaction_id)
        if not transaction:
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


@dataclass
class BudgetRow:
    category: Category
    field: BoundField
    spent: int

    @property
    def total(self):
        return self.category.balance + self.spent


@login_required
def budget(request: HttpRequest, budget_id: int, year: int, month: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    currencies = budget.category_set.values_list('currency').distinct()
    # Make sure these are created before creating the form
    inboxes = [budget.get_inbox(Category, currency).id
               for currency, in currencies]
    before, during = category_balance(budget, year, month)
    spent = dict(during.values_list('id', 'balance'))
    transaction = budgeting_transaction(budget, year, month)
    if request.method == 'POST':
        form = BudgetingForm(
            budget=budget, instance=transaction, data=request.POST)
        if form.is_valid():
            with atomic():
                form.save()
            return HttpResponseRedirect(request.GET.get('back', '/'))
    else:
        form = BudgetingForm(budget=budget, instance=transaction)
    rows = [BudgetRow(category, form[str(category.id)],
                      spent.get(category.id, 0))
            for category in before]
    data = {'inboxes': inboxes}
    context = {'rows': rows, 'form': form, 'budget': budget, 'data': data}
    return render(request, 'budget/budget.html', context)
