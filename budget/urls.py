from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('budget/<int:budget_id>/', views.budget, name='budget'),
    path('account/<int:account_id>/', views.account, name='account')
]

