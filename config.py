# -*- coding: utf-8 -*-
"""إعدادات النظام - SQLite (schema.db)"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, 'database')
os.makedirs(DB_DIR, exist_ok=True)

# يمكن تغييره عبر متغير البيئة DB_PATH
DB_PATH = os.environ.get('DB_PATH', os.path.join(DB_DIR, 'schema.db'))

# مفتاح تشفير الجلسات
SECRET_KEY = os.environ.get('SECRET_KEY', 'construction-management-secret-key-2026')

# رمز العملة المحلية
DEFAULT_LOCAL_CURRENCY_CODE = 'YER'
