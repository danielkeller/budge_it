from django.shortcuts import render
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse

from .models import transactions_for_budget, transactions_for_account
from .models import transactions_for_category, Account, Category, Budget
from .forms import PurchaseForm

def index(request: HttpRequest):
    return HttpResponse("Hello, world.")

def budget(request: HttpRequest, budget_id: int):
    transactions = transactions_for_budget(budget_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)

def account(request: HttpRequest, account_id: int):
    budget_id = Account.objects.get(id=account_id).budget_id
    transactions = transactions_for_account(account_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)

def category(request: HttpRequest, category_id: int):
    budget_id = Category.objects.get(id=category_id).budget_id
    transactions = transactions_for_category(category_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)

def purchase(request: HttpRequest, budget_id: int):
    budget = get_object_or_404(Budget, id=budget_id)
    if request.method == 'POST':
        form = PurchaseForm(budget, data=request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(
                reverse('budget', kwargs={'budget_id': budget_id}))
    else:
        form = PurchaseForm(budget)
    context = {'form': form, 'budget_id': budget_id}
    return render(request, 'budget/purchase.html', context)
