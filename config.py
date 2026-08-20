# -*- coding: utf-8 -*-
"""إعدادات النظام مع دعم التشغيل المحلي وRender."""
import os
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_DB_PATH = os.path.join(BASE_DIR, 'database', 'schema.db')
BUNDLED_UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')

DEFAULT_RUNTIME_DIR = '/var/data' if os.path.isdir('/var/data') else os.path.join(BASE_DIR, 'runtime_data')
APP_DATA_DIR = os.environ.get('APP_DATA_DIR', DEFAULT_RUNTIME_DIR)
DB_PATH = os.environ.get('DB_PATH', os.path.join(APP_DATA_DIR, 'schema.db'))
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(APP_DATA_DIR, 'uploads'))

SECRET_KEY = os.environ.get('SECRET_KEY', 'construction-management-secret-key-2026')
DEFAULT_LOCAL_CURRENCY_CODE = 'YER'
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '5000'))
DEBUG = os.environ.get('FLASK_DEBUG', '0').lower() in {'1', 'true', 'yes', 'on'}


def bootstrap_runtime():
    """يجهّز المسارات القابلة للكتابة وينسخ قاعدة البيانات الافتراضية أول مرة."""
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    if not os.path.exists(DB_PATH) and os.path.exists(BUNDLED_DB_PATH):
        shutil.copy2(BUNDLED_DB_PATH, DB_PATH)

    if os.path.isdir(BUNDLED_UPLOADS_DIR):
        for name in os.listdir(BUNDLED_UPLOADS_DIR):
            src = os.path.join(BUNDLED_UPLOADS_DIR, name)
            dst = os.path.join(UPLOAD_FOLDER, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    return {
        'app_data_dir': APP_DATA_DIR,
        'db_path': DB_PATH,
        'upload_folder': UPLOAD_FOLDER,
    }
