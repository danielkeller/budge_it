from django.db import transaction
from django.db.utils import IntegrityError
from django.core.management.base import BaseCommand
from budget.models import *

from collections import defaultdict
import datetime
import pandas as pd
import re

ynab_transfer_prefix = "Transfer : "

class Command(BaseCommand):
    help = "Import a YNAB budget"

    def handle(self, *args: Any, **options: Any):
        user = User.objects.get(username = "admin")
        target_budget, _ = Budget.objects.get_or_create(name="ynabimport", budget_of = user) 

        register_filename = "../Swiss Budget as of 2023-04-22 21-35 - Register.csv"
        register_df = pd.read_csv(register_filename)[::-1]
        register_df.drop(columns = ["Flag"], inplace = True)

        register_df["TotalInflow"] = ((register_df["Inflow"] - register_df["Outflow"])*100).astype(int) #TODO how to get currency unit?
        register_df.drop(columns = ["Inflow", "Outflow"], inplace = True)

        it = register_df.iterrows()
        raw_transaction_parts = []
        for it, raw_transaction_part in it:
            raw_transaction_parts.append(raw_transaction_part)
            if iscomplete(raw_transaction_part):
                self.save(target_budget, raw_transaction_parts)
                raw_transaction_parts = []
            

    @transaction.atomic
    def save(self, target_budget, raw_transaction_parts):
        first_raw_transaction_part = raw_transaction_parts[0]
        date = YNAB_string_to_date(first_raw_transaction_part["Date"]) #filter for past dates

        kind = Transaction.Kind.TRANSACTION
        description = join_memos(raw_transaction_parts)

        transaction = Transaction(date = date, kind = kind, description = description)

        transaction_account_parts = defaultdict(lambda: 0)
        transaction_category_parts = defaultdict(lambda: 0)
        for raw_transaction_part in raw_transaction_parts:
            raw_transaction_part_inflow = raw_transaction_part["TotalInflow"]
            raw_transaction_part_outflow = -raw_transaction_part_inflow

            raw_account = raw_transaction_part["Account"]
            account, _ = Account.objects.get_or_create(
                    budget_id = target_budget.id, 
                    name = raw_account
                    )
            transaction_account_parts[account] += raw_transaction_part_inflow

            raw_payee = raw_transaction_part["Payee"]
            raw_payee = raw_payee if isinstance(raw_payee, str) else "BLANK"
            if raw_payee.startswith(ynab_transfer_prefix):
                raw_transfer_account = raw_payee.removeprefix(ynab_transfer_prefix)
                if raw_account == raw_transfer_account:
                    raise Exception(f'Account "{raw_account}" and Transfer Account "{raw_transfer_account}" are identical')
                elif raw_account < raw_transfer_account: #don't want to duplicate transfers: skip these ones
                    return None

                transfer_account, _ = Account.objects.get_or_create(
                        budget_id = target_budget.id, 
                        name = raw_transfer_account
                        )
                transaction_account_parts[transfer_account] += raw_transaction_part_outflow

            else:
                payee, _ = Budget.objects.get_or_create(
                        name = raw_payee,
                        payee_of = target_budget.budget_of
                        )
                payee_account = payee.get_hidden(Account, currency = "")
                transaction_account_parts[payee_account] += raw_transaction_part_outflow

                category, _ = Category.objects.get_or_create(
                        budget_id = target_budget.id, 
                        name = raw_transaction_part["Category Group/Category"]
                        )
                transaction_category_parts[category] = raw_transaction_part_inflow
                payee_category = payee.get_hidden(Category, currency = "")
                transaction_category_parts[payee_category] += raw_transaction_part_outflow

        transaction.save()
        try:
            transaction.set_parts(accounts = transaction_account_parts, categories = transaction_category_parts, in_budget = target_budget)
        except IntegrityError:
            print(raw_transaction_parts)
            exit()
        transaction.save()

        return None

def YNAB_string_to_date(ynab_string):
    return datetime.date(*[int(i) for i in ynab_string.split('.')][::-1])

def iscomplete(raw_transaction_part):
    raw_memo = raw_transaction_part["Memo"]
    return not(isinstance(raw_memo, str)) or not(raw_memo.startswith("Split")) or raw_memo.startswith("Split (1/") 

def join_memos(raw_transaction_parts):
    return ", ".join([re.sub("Split \(.*\) ", "", x.Memo) for x in raw_transaction_parts if isinstance(x.Memo, str)])
