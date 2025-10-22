#!/usr/bin/env bash
set -e

# Переходим в папку с ботом
cd Bot

# Обновляем pip и ставим зависимости
python -m pip install --upgrade pip
pip install -r requirements.txt

# Запускаем бота
python main.py
