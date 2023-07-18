from django.urls import path, include

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('overview/<int:budget_id>/', views.overview, name='overview'),
    path('reorder/<int:budget_id>/', views.reorder, name='reorder'),
    path('manage/<int:budget_id>/', views.manage_accounts, name='manage'),
    path('otg/<int:budget_id>/', views.onthego, name='otg'),
    path('account/<int:account_id>/', views.account, name='account'),
    path('account/<int:account_id>/add/<int:transaction_id>/',
         views.add_to_account, name='add_to_account'),
    path('budget/<int:budget_id>/<int:year>/<int:month>/',
         views.budget, name='budget'),
    path('balance/<str:currency>/<int:budget_id_1>/to/<int:budget_id_2>/',
         views.balance, name='balance'),
    path('transaction/<int:budget_id>/',
         views.edit, name='create'),
    path('transaction/<int:budget_id>/<int:transaction_id>/',
         views.edit, name='edit'),
    path('transaction/<int:budget_id>/<int:transaction_id>/delete/',
         views.delete, name='delete'),
    path('partial/edit/<int:budget_id>/part/<int:number>/',
         views.part_form, name='part_form'),
    path('partial/edit/<int:budget_id>/row/<int:part_index>/<int:number>/',
         views.row_form, name='row_form'),
]
