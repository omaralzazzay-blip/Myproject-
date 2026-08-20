# -*- coding: utf-8 -*-
"""ملف التشغيل المحلي: python run.py"""
from app import app
from config import HOST, PORT, DEBUG

if __name__ == '__main__':
    app.run(debug=DEBUG, host=HOST, port=PORT)
