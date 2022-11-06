from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from .models import transactions_for_budget

def index(request: HttpRequest):
    return HttpResponse("Hello, world.")

def budget(request: HttpRequest, budget_id: int):
    transactions = transactions_for_budget(budget_id)
    context = {'transactions': transactions, 'budget_id': budget_id}
    return render(request, 'budget/budget.html', context)
