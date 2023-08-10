from django.urls import path, include

from . import views

urlpatterns = [
    # Placeholder stuff
    path('', views.index, name='index'),
    path('accounts/', include('django.contrib.auth.urls')),

    # Real pages
    path('<int:budget_id>', views.all, name='all-o'),
    path('<int:budget_id>/<int:account_id>/', views.all, name='all-a'),
    path('<int:budget_id>/<int:account_id>/<int:transaction_id>/',
         views.all, name='all-t'),
    path('<int:budget_id>/<int:account_id>/panel',
         views.account_panel, name='account-panel'),
    path('<int:budget_id>/<int:account_id>/tpanel',
         views.transaction_panel, name='transaction-panel'),

    path('overview/<int:budget_id>/', views.overview, name='overview'),

    path('manage/<int:budget_id>/', views.manage_accounts, name='manage'),

    path('otg/<int:budget_id>/', views.onthego, name='otg'),

    path('account/<int:account_id>/', views.account, name='account'),
    path('balance/<str:currency>/<int:budget_id_1>/to/<int:budget_id_2>/',
         views.balance, name='balance'),

    path('budget/<int:budget_id>/<int:year>/<int:month>/',
         views.budget, name='budget'),

    path('transaction/<int:budget_id>/',
         views.edit, name='create'),
    path('transaction/<int:budget_id>/<int:transaction_id>/',
         views.edit, name='edit'),

    # POST-only paths
    path('reorder/<int:budget_id>/', views.reorder, name='reorder'),
    path('account/<int:account_id>/add/<int:transaction_id>/',
         views.add_to_account, name='add_to_account'),
    path('account/<int:account_id>/clear/<int:transaction_id>/',
         views.clear, name='clear'),
    path('transaction/<int:budget_id>/<int:transaction_id>/delete/',
         views.delete, name='delete'),
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
