import os
dirname = os.path.dirname(__file__)

DEBUG = True

SECRET = 'secret!'

STATIC_PATH = os.path.join(dirname, 'static')
TEMPLATE_PATH = os.path.join(dirname, 'templates')

DATABASE_DSN = 'dbname=chat user=chat password=chat host=localhost port=5432'