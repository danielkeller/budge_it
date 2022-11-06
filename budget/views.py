from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from .models import transactions_for_budget, transactions_for_account, Account

def index(request: HttpRequest):
    return HttpResponse("Hello, world.")

def budget(request: HttpRequest, budget_id: int):
    transactions = transactions_for_budget(budget_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)

def account(request: HttpRequest, account_id: int):
    budget_id = Account.objects.get(id=account_id).budget_id
    transactions = transactions_for_account(account_id)
    context = {'transactions': transactions,
               'budget_id': budget_id, 'account_id': account_id}
    return render(request, 'budget/account.html', context)
