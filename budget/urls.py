from django.urls import path, include

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path("accounts/", include("django.contrib.auth.urls")),
    path('overview/<int:budget_id>/', views.overview, name='overview'),
    path('account/<int:account_id>/', views.account, name='account'),
    path('category/<int:category_id>/', views.category, name='category'),
    path('account/<int:budget_id>/new/', views.new_account, name='new_account'),
    path('category/<int:budget_id>/new/',
         views.new_category, name='new_category'),
    path('history/<int:budget_id>/', views.history, name='history'),
    path('balance/<str:currency>/<int:budget_id_1>/to/<int:budget_id_2>/',
         views.balance, name='balance'),
    path('transaction/<int:budget_id>/',
         views.edit, name='create'),
    path('transaction/<int:budget_id>/<int:transaction_id>/',
         views.edit, name='edit'),
    path('transaction/<int:budget_id>/<int:transaction_id>/delete/',
         views.delete, name='delete'),
]
