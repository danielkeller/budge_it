from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('overview/<int:budget_id>/', views.overview, name='overview'),
    path('budget/<int:budget_id>/', views.budget, name='budget'),
    path('account/<int:account_id>/', views.account, name='account'),
    path('category/<int:category_id>/', views.category, name='category'),
    path('balance/<int:budget_id_1>/to/<int:budget_id_2>/', views.balance,
         name='balance'),
    path('transaction/<int:budget_id>/<int:transaction_id>/',
         views.edit, name='edit'),
    path('transaction/<int:budget_id>/',
         views.edit, name='create'),
    path('budget/<int:budget_id>/purchase/', views.purchase, name='purchase'),
]
