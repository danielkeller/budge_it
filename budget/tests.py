from django.test import TestCase

from budget.models import Budget

# Create your tests here.


class ModelTests(TestCase):
    def test_budget_creation(self):
        """Budget can be created with id"""
        budget = Budget(1)
        self.assertTrue(isinstance(budget, Budget))
