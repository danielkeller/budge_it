
from django.db import transaction
from django.core.management.base import BaseCommand, CommandParser
from django.core.exceptions import ObjectDoesNotExist
from budget.models import *
import pandas as pd
import datetime


class Command(BaseCommand):
    help = "Import a YNAB budget"

    def handle(self, *args: Any, **options: Any):
        user = User.objects.get(username = "admin")
        target_budget, _ = Budget.objects.get_or_create(name="ynabimport", budget_of = user) 

        register_filename = "../Swiss Budget as of 2023-04-22 21-35 - Register.csv"
        register_df = pd.read_csv(register_filename)[::-1]

        it = register_df.iterrows()
        for it, raw_transaction in it: #TODO make a generator that combines split transactions from ynab into a single budge-it transaction
            raw_transactions = [raw_transaction]
            self.save(target_budget, raw_transactions)

    @transaction.atomic
    def save(self, target_budget, raw_transactions):
        raw_transaction = raw_transactions[0]

        date = YNAB_string_to_date(raw_transaction["Date"]) #filter for past dates
        kind = Transaction.Kind.TRANSACTION

        description = raw_transaction["Memo"] if isinstance(raw_transaction["Memo"], str) else "" #combine?

        transaction = Transaction(date = date, kind = kind, description = description)

        transaction_account_parts = {}
        transaction_category_parts = {}
        for raw_transaction in raw_transactions:
            account, _ = Account.objects.get_or_create(
                    budget_id = target_budget.id, 
                    name = raw_transaction["Account"]
            )
            transaction_account_parts[account] = raw_transaction["Inflow"] - raw_transaction["Outflow"]

            payee, _ = Budget.objects.get_or_create(
                    name = raw_transaction["Payee"],
                    payee_of = target_budget.budget_of
            )
            payee_account = payee.get_hidden(Account, currency = "")
            transaction_account_parts[payee_account] = raw_transaction["Outflow"] - raw_transaction["Inflow"]

            category, _ = Category.objects.get_or_create(
                    budget_id = target_budget.id, 
                    name = raw_transaction["Category Group/Category"]
            )
            transaction_category_parts[category] = raw_transaction["Inflow"] - raw_transaction["Outflow"]
            payee_category = payee.get_hidden(Category, currency = "")
            transaction_category_parts[payee_category] = raw_transaction["Outflow"] - raw_transaction["Inflow"]

        transaction.set_parts(accounts = transaction_account_parts, categories = transaction_category_parts, in_budget = target_budget)
        transaction.save()

        return None

def YNAB_string_to_date(ynab_string):
    return datetime.date(*[int(i) for i in ynab_string.split('.')][::-1])

