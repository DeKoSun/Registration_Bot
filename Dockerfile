# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем системные зависимости (если понадобятся)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем только нужные файлы
COPY Bot/ ./Bot/
COPY Bot/requirements.txt ./Bot/requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r Bot/requirements.txt

# Запускаем бота
CMD ["python", "Bot/main.py"]
