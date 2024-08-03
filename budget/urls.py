from django.urls import path, include

from . import views

urlpatterns = [
    # Placeholder stuff
    path('', views.index, name='index'),
    path('accounts/', include('django.contrib.auth.urls')),

    # Real pages
    path('<int:budget_id>/', views.all, name='all'),
    path('<int:budget_id>/<account_id>/', views.all, name='all'),
    path('<int:budget_id>/<account_id>/<transaction_id>/',
         views.all, name='all'),

    path('<int:budget_id>/<account_id>/<int:transaction_id>/copy/',
         views.copy, name='copy'),

    path('manage/<int:budget_id>/', views.manage_accounts, name='manage'),
    path('budget/<int:budget_id>/<int:year>/<int:month>/',
         views.budgeting, name='budget'),

    # POST-only paths
    path('account/<int:account_id>/clear/<int:transaction_id>/',
         views.clear, name='clear'),
    path('account/<int:account_id>/reconcole/',
         views.reconcile, name='reconcile'),
    path('budget/copy/<int:budget_id>/<int:transaction_id>/<int:year>/<int:month>/',
         views.copy_budget, name='copy_budget'),

    # Htmx partials
    path('partial/edit/<int:budget_id>/part/<int:number>/',
         views.part_form, name='part_form'),
    path('partial/edit/<int:budget_id>/row/<int:part_index>/<int:number>/',
         views.row_form, name='row_form'),
    path('partial/manage/<int:budget_id>/account/<int:number>/',
         views.account_form, name='account_form'),
    path('partial/manage/<int:budget_id>/category/<int:number>/',
         views.category_form, name='category_form'),
    path('partial/manage/currency/<int:number>/',
         views.currency_form, name='currency_form'),
]
