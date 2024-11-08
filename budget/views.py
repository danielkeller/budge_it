from typing import Any, Callable, Literal, Collection
from datetime import date
from collections import defaultdict
from urllib.parse import urlparse

from django.views.decorators.http import require_http_methods
from django.shortcuts import render
from django.http import (HttpRequest, HttpResponse, HttpResponseRedirect,
                         HttpResponseBadRequest, Http404, QueryDict)
from django.shortcuts import get_object_or_404
from django.db.transaction import atomic
from django.contrib.auth.decorators import login_required
from django.urls import reverse, resolve
from render_block import render_block_to_string
import cProfile

from .models import (date_range, months_between,
                     BaseAccount, Account, Category, Budget,
                     Transaction, MultiTransaction, Cleared,
                     accounts_overview, budgeting_transaction,
                     Balance, Total, AccountLike,
                     prior_budgeting_transaction)
from .forms import (QuickAddForm, TransactionForm,
                    BudgetingForm, BudgetForm, MultiFormSet,
                    AccountManagementFormSet,
                    CategoryManagementFormSet, CurrencyManagementFormSet)


def profileit(func: Any):
    def wrapper(*args: Any, **kwargs: Any):
        datafn = func.__name__ + ".profile"  # Name the data file sensibly
        prof = cProfile.Profile()
        retval = prof.runcall(func, *args, **kwargs)
        prof.dump_stats(datafn)
        return retval

    return wrapper


def post_data(get_response: Callable[[HttpRequest], HttpResponse]):
    def middleware(request: HttpRequest):
        if not request.POST and request.content_type == "application/x-www-form-urlencoded":
            request.POST = QueryDict(request.body, encoding=request.encoding)
        response = get_response(request)
        return response
    return middleware


@login_required
def index(request: HttpRequest):
    # type: ignore
    return HttpResponseRedirect(request.user.budget.get_absolute_url())


def _get_allowed_budget_or_404(request: HttpRequest, id: int):
    budget = get_object_or_404(Budget, id=id)
    if not budget.view_permission(request.user):
        raise Http404()
    return budget


def _get_allowed_account_or_404(request: HttpRequest, id: int | str):
    try:
        account = BaseAccount.get(int(id))
    except (ValueError, BaseAccount.DoesNotExist):
        raise Http404()
    if not account.budget.view_permission(request.user):
        raise Http404()
    return account


def _get_account_like_or_404(request: HttpRequest, budget: Budget,
                             name: str | int) -> AccountLike:
    if isinstance(name, str):
        if name.startswith('all-'):
            return Total(budget, name.removeprefix('all-'))
        if name.startswith('owed-'):
            _, currency, other_id = name.split('-')
            other = Budget.objects.filter(
                id=other_id).first() or Budget(id=int(other_id))
            return Balance(budget, other, currency)
    return _get_allowed_account_or_404(request, name)


def _get_allowed_transactions_or_404(
        budget: Budget, transaction_ids: Collection[int] | Literal['new']):
    if not transaction_ids or transaction_ids == 'new':
        return None
    budget = budget.main_budget()
    transaction = Transaction.objects.get_for_multi(budget, transaction_ids)
    if not transaction:
        raise Http404()
    return transaction


def parse_transaction_ids(ids: str | list[str]) -> set[int] | Literal['new']:
    if not ids:
        return set()
    if isinstance(ids, list):
        if 'new' in ids:
            return 'new'
        try:
            return set(int(id) for id in ids)
        except ValueError:
            raise Http404()
    else:
        return parse_transaction_ids(ids.split(','))


@login_required
def all(request: HttpRequest, budget_id: int,
        account_id: str | None = None,
        transaction_id: str | None = None):
    account_id = account_id or request.GET.get('account')
    transaction_ids = parse_transaction_ids(
        transaction_id or request.GET.getlist('transaction'))

    budget = get_object_or_404(Budget, id=budget_id)
    if not budget.view_permission(request.user):
        return redirect_to_own_url(request, budget, transaction_ids)

    if request.method == 'PUT':
        # A bit of a hack to use the method like this. TODO: Use update_all_view approach.
        transaction_ids = quick_save(request, budget, account_id)
    elif request.method == 'POST':
        transaction_ids = save(request, budget, transaction_ids)
    elif request.method == 'DELETE':
        transaction_ids = delete(budget, transaction_ids)

    return all_view(request, budget, account_id, transaction_ids)

# TODO: The hx-select-oob on these is getting a little out of hand


def redirect_to_own_url(request: HttpRequest, other: Budget,
                        transaction_ids: Collection[int] | Literal['new'] = set()):
    """Try to redirect to a corresponding view that is allowed."""
    budget: Budget
    budget = request.user.budget  # type: ignore
    if other not in budget.visible_budgets():
        raise Http404()
    transaction = _get_allowed_transactions_or_404(budget, transaction_ids)
    currency = (transaction.first_currency() if transaction
                else budget.get_initial_currency())
    account = Balance(budget, other, currency)
    return HttpResponseRedirect(all_url(budget.id, account.id, transaction_ids))


def copy(request: HttpRequest, budget_id: int, account_id: str, transaction_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    transaction = Transaction.objects.get_for(budget, transaction_id)
    if not transaction:
        raise Http404()
    transaction.id = None  # type: ignore
    for part in transaction.visible_parts:
        part.id = None  # type: ignore
    form = TransactionForm(budget=budget, prefix="tx", instance=transaction)

    context = {'budget': budget, 'account_id': account_id,
               'transaction_ids': 'new',
               'transaction': transaction, 'form': form}

    response = render(request, 'budget/partials/edit.html', context)
    response['HX-Replace-Url'] = all_url(budget.id, account_id, 'new')
    return response


@require_http_methods(['POST'])
def clear(request: HttpRequest, account_id: int, transaction_id: int):
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
    return update_all_view(request, account.budget)


@require_http_methods(['POST'])
def reconcile(request: HttpRequest, account_id: int):
    account = _get_allowed_account_or_404(request, account_id)
    if not isinstance(account, Account) or not account.clearable:
        return HttpResponseBadRequest('Wrong kind of account')
    Cleared.objects.filter(account=account).update(reconciled=True)
    return update_all_view(request, account.budget)


def update_all_view(request: HttpRequest, budget: Budget):
    params = resolve(urlparse(request.headers['HX-Current-URL']).path)
    return all_view(request, budget,
                    params.kwargs.get('account_id'),
                    parse_transaction_ids(params.kwargs.get('transaction_id', '')))


def all_url(budget_id: int,  account_id: str | int | None,
            transaction_ids: Collection[int] | Literal['new']):
    ids_str = ('new' if transaction_ids == 'new'
               else ','.join(str(id) for id in transaction_ids))
    return reverse(
        'all', args=[arg for arg in (budget_id, account_id, ids_str) if arg])


def all_view(request: HttpRequest, budget: Budget,
             account_id: str | int | None = None,
             transaction_ids: Collection[int] | Literal['new'] = set()):
    prev_args = {}
    if 'HX-Current-URL' in request.headers:
        prev_args = resolve(
            urlparse(request.headers['HX-Current-URL']).path).kwargs

    def fix_url(response: HttpResponse):
        action = 'HX-Replace-Url'
        # Changing level?
        if (bool(account_id) != ('account_id' in prev_args)
                or bool(transaction_ids) != ('transaction_id' in prev_args)):
            action = 'HX-Push-Url'
        response[action] = all_url(budget.id, account_id, transaction_ids)
        return response

    account = None
    if account_id:
        account = _get_account_like_or_404(request, budget, account_id)

    transaction = _get_allowed_transactions_or_404(budget, transaction_ids)

    # I think the prefix isn't needed
    if transaction and transaction.kind == Transaction.Kind.BUDGETING:
        form = BudgetingForm(budget, prefix="tx", instance=transaction)
    elif isinstance(transaction, MultiTransaction):
        form = MultiFormSet(budget, prefix="tx", instance=transaction)
    else:
        initial = {}
        if not transaction:
            prev_ids = parse_transaction_ids(
                prev_args.get('transaction_id', ''))
            if prev_ids and prev_ids != 'new':
                prev_transaction = Transaction.objects.get_for(
                    budget, next(iter(prev_ids)))
                if prev_transaction:
                    initial = {'date': prev_transaction.date}

        form = TransactionForm(budget=budget, account=account, prefix="tx",
                               instance=transaction, initial=initial)

    context = {'budget': budget, 'account_id': account_id, 'transaction_ids': transaction_ids,
               'transaction': transaction, 'form': form}

    if request.headers.get('HX-Target') == 'transaction':
        return fix_url(render(request, 'budget/partials/edit.html', context))

    if account_id:
        entries, balance, cleared = account.transactions()
        initial = ({'date': transaction.date}
                   if isinstance(transaction, Transaction) else {})
        quick_add = QuickAddForm(account, initial=initial, prefix="qa",
                                 autofocus=request.method == 'PUT')
        context |= {'account': account, 'entries': entries,
                    'balance': balance, 'cleared': cleared,
                    'quick_add': quick_add}

    if request.headers.get('HX-Target') == 'account':
        return fix_url(render(request, 'budget/partials/account.html', context))

    accounts, categories, groups, debts, totals = accounts_overview(budget)
    context |= {'accounts': accounts, 'categories': categories,
                'groups': groups, 'debts': debts, 'totals': totals,
                'today': date.today(),
                'edit': _edit_context(budget)}

    return fix_url(render(request, 'budget/all.html', context))


def quick_save(request: HttpRequest, budget: Budget, account_id: str | None):
    account = _get_account_like_or_404(request, budget, account_id or "")
    form = QuickAddForm(account, prefix="qa", data=request.POST)
    if not form.is_valid():
        raise ValueError(form.errors)
    return {form.save().id}


def save(request: HttpRequest,
         budget: Budget, transaction_ids: Collection[int] | Literal['new']):
    transaction = _get_allowed_transactions_or_404(budget, transaction_ids)

    if transaction and transaction.kind == Transaction.Kind.BUDGETING:
        form = BudgetingForm(budget, prefix="tx",
                             instance=transaction, data=request.POST)
        if not form.is_valid():
            raise ValueError(form.errors)
        id = form.save().id
        return {id} if id else {}
    elif isinstance(transaction, MultiTransaction):
        form = MultiFormSet(budget, prefix="tx",
                            instance=transaction, data=request.POST)
        if not form.is_valid():
            raise ValueError(form.errors, form.non_form_errors())
        return form.save().id
    else:
        form = TransactionForm(budget=budget, prefix="tx",
                               instance=transaction, data=request.POST)
        if not form.is_valid():
            # This doesn't work.
            raise ValueError(form.errors, form.formset.errors,
                             form.formset.non_form_errors())
        id = form.save().id
        return {id} if id else {}


def delete(budget: Budget, transaction_ids: Collection[int] | Literal['new']):
    if len(transaction_ids) != 1:
        raise ValueError('Need exactly one transaction')
    transaction = get_object_or_404(
        Transaction, id=next(iter(transaction_ids)))
    with atomic():
        if not any([part.set_entries(budget, {}, {})
                    for part in transaction.visible_parts]):
            transaction.delete()
    return set()


def _edit_context(budget: Budget):
    friends = dict(budget.friends.values_list('id', 'name'))
    payees = dict(Budget.objects.filter(payee_of=budget.owner())
                  .values_list('id', 'name'))
    # Closed?
    own_accounts = []
    accounts = defaultdict(list)
    for account in budget.account_set.exclude(name=''):
        accounts[account.currency].append(account)
        own_accounts.append(account.id)
    categories = defaultdict(list)
    for category in budget.category_set.exclude(name=''):
        categories[category.currency].append(category)
        own_accounts.append(category.id)

    for currency in budget.currencies:
        accounts[currency]
        categories[currency]

    data = {
        'budget': budget.id,
        'budgets': {budget.id: budget.name, **friends, **payees},
        'own_accounts': own_accounts,
        'friends': friends,
    }
    return {'friends': friends, 'payees': payees,
            'accounts': accounts, 'categories': categories,
            'data': data}


def account_form(request: HttpRequest, budget_id: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    queryset = Account.objects.none()
    formset = AccountManagementFormSet(
        instance=budget, queryset=queryset, prefix="accounts")
    formset.min_num = number + 1  # type: ignore
    context = {'budget': budget,
               'account_formset': formset, 'form': formset.forms[number]}
    return HttpResponse(
        render_block_to_string('budget/manage.html',
                               'account_form', context, request)
        + render_block_to_string('budget/manage.html', 'new_account', context, request))


def category_form(request: HttpRequest, budget_id: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    queryset = Category.objects.none()
    formset = CategoryManagementFormSet(
        instance=budget, queryset=queryset, prefix="categories",
        initial=[{}] * number + [{'group': request.GET.get('groupname', '')}])
    formset.min_num = number + 1  # type: ignore
    context = {'budget': budget,
               'category_formset': formset, 'form': formset.forms[number]}
    return HttpResponse(
        render_block_to_string('budget/manage.html',
                               'category_form', context, request)
        + render_block_to_string('budget/manage.html', 'new_category', context, request))


def currency_form(request: HttpRequest, number: int):
    formset = CurrencyManagementFormSet(prefix="currencies")
    formset.min_num = number + 1  # type: ignore
    context = {'currency_formset': formset, 'form': formset.forms[number]}
    return HttpResponse(
        render_block_to_string('budget/manage.html',
                               'currency_form', context, request)
        + render_block_to_string('budget/manage.html', 'new_currency', context, request))


def manage_accounts(request: HttpRequest, budget_id: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    categories = (budget.category_set
                  .order_by('order', 'group', 'name'))
    accounts = (budget.account_set.exclude(name='')
                .order_by('order', 'group', 'name'))
    currencies = budget.category_set.filter(name='')
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

    accounts, categories, groups, debts, totals = accounts_overview(budget)
    context |= {'accounts': accounts, 'categories': categories,
                'groups': groups, 'debts': debts, 'totals': totals,
                'today': date.today(),
                'edit': _edit_context(budget)}

    return render(request, 'budget/manage.html', context)


def part_form(request: HttpRequest, budget_id: int, account_id: str, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    budget = budget.main_budget()
    account = _get_account_like_or_404(request, budget, account_id)
    form = TransactionForm(budget=budget, account=account, prefix="tx")
    form.formset.min_num = number + 1  # type: ignore
    # TODO: The currency interaction is jank.
    context = {'budget': budget, 'account_id': account_id,
               'part': form.formset.forms[number], 'part_index': number,
               'currency': 'XXX', 'form': form}
    return HttpResponse(render_block_to_string(
        'budget/partials/edit.html', 'edit_part', context, request))


def row_form(request: HttpRequest, budget_id: int,
             part_index: int, number: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    budget = budget.main_budget()
    form = TransactionForm(budget=budget, prefix="tx")
    form.formset.min_num = part_index + 1  # type: ignore
    part = form.formset.forms[part_index]
    # Extra is 1
    part.formset.min_num = number + 1 - 1  # type: ignore
    context = {'budget': budget, 'currency': 'XXX',
               'row': part.formset.forms[number], 'row_index': number,
               'part': part, 'part_index': part_index}
    return HttpResponse(render_block_to_string(
        'budget/partials/edit.html', 'edit_row', context, request))


@login_required
def budgeting(request: HttpRequest, budget_id: int, year: int, month: int):
    budget = _get_allowed_budget_or_404(request, budget_id)
    try:
        budget_date = date(year, month, 1)
    except ValueError:
        raise Http404()

    min_date, max_date = date_range(budget)
    years = range(min_date.year, max_date.year + 2)
    months = months_between(date(year, 1, 1), date(year, 12, 31))

    transaction = budgeting_transaction(budget, budget_date)

    if request.method == 'POST':
        form = BudgetingForm(budget, instance=transaction, data=request.POST)
        if form.is_valid():
            with atomic():
                form.save()
            return HttpResponseRedirect(
                request.GET.get('back', request.get_full_path()))
    else:
        form = BudgetingForm(budget, instance=transaction)

    prior = prior_budgeting_transaction(budget, budget_date)

    context = {'form': form, 'budget': budget,
               'current_year': year, 'current_month': month,
               'years': years, 'months': months,
               'prior': prior}

    accounts, categories, groups, debts, totals = accounts_overview(budget)
    context |= {'accounts': accounts, 'categories': categories,
                'groups': groups, 'debts': debts, 'totals': totals,
                'today': date.today(),
                'edit': _edit_context(budget)}

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
    # TODO returning it directly doesn't work?
    return HttpResponseRedirect(reverse('budget', args=(budget_id, year, month)))
