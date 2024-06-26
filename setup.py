from setuptools import setup, find_packages

setup(name='budge_it',
      version='0.1',
      packages=find_packages(include=['budget', 'budget.*', 'budge_it']),
      py_modules=['manage'],
      include_package_data=True,
      install_requires=[
          'Django==4.2.3',
          'Jinja2==3.1.3',
          'django-render-block',
          'psycopg[binary]==3.1.18',
          'gunicorn',
          'python-dateutil',
      ],
      zip_safe=True)
