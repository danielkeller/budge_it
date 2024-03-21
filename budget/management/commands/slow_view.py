from django.core.management.base import BaseCommand
from django.http import HttpRequest
from django.contrib.auth.models import User
from typing import Any

from budget import views
from budget import models


class Command(BaseCommand):
    help = "Import a YNAB budget"

    def handle(self, *args: Any, **options: Any):
        request = HttpRequest()
        request.user = User.objects.get(username='admin')
        request.method = 'GET'
        request.META['HX-Target'] = 'account'
        for _ in range(10):
            views.all(request, 72, 121)
