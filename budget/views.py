from dataclasses import dataclass
from typing import Optional, Any
from datetime import date, timedelta

from django.shortcuts import render
from django.http import (HttpRequest, HttpResponseRedirect,
                         HttpResponseBadRequest, Http404)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.forms import BoundField
import cProfile

from .models import (sum_by, date_range, months_between,
                     BaseAccount, Account, Category, Budget,
                     Transaction,
                     accounts_overview, entries_for, category_balance,
                     Balance, entries_for_balance, budgeting_transaction,
                     prior_budgeting_transaction, copy_budgeting)
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
            return HttpResponseRedirect(reverse(
                'edit', args=(budget_id, transaction.id)))
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
    entries = entries_for_balance(account)
    data = {'budget': budget.id}
    context = {'entries': entries, 'account': account,
               'form': None, 'data': data}
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
    context = {'entries': entries_for(account), 'account': account,
               'form': form, 'data': data}
    return render(request, 'budget/account.html', context)


@login_required
def add_to_account(request: HttpRequest, account_id: int, transaction_id: int):
    account = _get_allowed_account_or_404(request, account_id)
    transaction = Transaction.objects.get_for(
        account.budget, transaction_id)
    if not transaction:
        raise Http404()
    transaction.change_inbox_to(account)
    return HttpResponseRedirect(f"{account.get_absolute_url()}?t={transaction.id}")


def account_form(request: HttpRequest, budget_id: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    queryset = Account.objects.none()
    formset = AccountManagementFormSet(
        instance=budget, queryset=queryset, prefix="accounts")
    formset.min_num = number + 1  # type: ignore
    context = {'budget': budget,
               'account_formset': formset, 'form': formset.forms[number]}
    return render(request, 'budget/partials/manage_new_account.html', context)


def category_form(request: HttpRequest, budget_id: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    queryset = Category.objects.none()
    formset = CategoryManagementFormSet(
        instance=budget, queryset=queryset, prefix="categories")
    formset.min_num = number + 1  # type: ignore
    context = {'budget': budget,
               'category_formset': formset, 'form': formset.forms[number]}
    return render(request, 'budget/partials/manage_new_category.html', context)


def currency_form(request: HttpRequest, number: int):
    formset = CurrencyManagementFormSet(prefix="currencies")
    formset.min_num = number + 1  # type: ignore
    context = {'currency_formset': formset, 'form': formset.forms[number]}
    return render(request, 'budget/partials/currency_new.html', context)


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
    return render(request, 'budget/partials/edit_part_new.html', context)


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
    return render(request, 'budget/partials/edit_row_new.html', context)


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
                part = instance.parts.first()
                entry = (part.accountentry_set.first()
                         or part.categoryentry_set.first())
                budget.initial_currency = entry.sink.currency
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
    spent: int

    @property
    def total(self):
        return self.category.balance + self.spent


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

    currencies = budget.category_set.values_list('currency').distinct()
    # Make sure these are created before creating the form
    # TODO: Show only the appropriate inboxes
    inboxes = [budget.get_inbox(Category, currency).id
               for currency, in currencies]
    before, during = category_balance(budget, budget_date)
    spent = dict(during.values_list('id', 'balance'))
    transaction = budgeting_transaction(budget, budget_date)
    initial = {'date': budget_date}
    if request.method == 'POST':
        form = BudgetingForm(budget=budget, instance=transaction,
                             data=request.POST)
        if form.is_valid():
            with atomic():
                form.save()
            return HttpResponseRedirect(
                request.GET.get('back', request.get_full_path()))
    else:
        form = BudgetingForm(budget=budget, instance=transaction,
                             initial=initial)
    rows = [BudgetRow(category, form[str(category.id)],
                      spent.get(category.id, 0))
            for category in before
            if form[str(category.id)].value() or spent.get(category.id, 0)
            or category.balance or not category.closed]

    prior = prior_budgeting_transaction(budget, budget_date)

    data = {'inboxes': inboxes}
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
    prior = get_object_or_404(Transaction, id=transaction_id)
    try:
        budget_date = date(year, month, 1)
    except ValueError:
        raise Http404()
    copy_budgeting(budget, prior, budget_date)
    return HttpResponseRedirect(reverse('budget', args=(budget_id, year, month)))
