from django.templatetags.static import static
from django.urls import reverse
from datetime import date, timedelta

from jinja2 import Environment


def url(view: str, *args):
    return reverse(view, args=args)


def end_of_month(value: date):
    return (value + timedelta(days=31)).replace(day=1) - timedelta(days=1)


def environment(**options):
    env = Environment(**options)
    env.globals.update(
        {
            "static": static,
            "url": url,
            "end_of_month": end_of_month,
        }
    )
    return env
