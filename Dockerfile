# Используем официальный легковесный образ Python 3.11
FROM python:3.11-slim

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта в контейнер
COPY . .

# Пробрасываем порт (согласно значению в .env или по умолчанию 8080)
EXPOSE 8080

# Команда для запуска приложения через Gunicorn
# Мы привязываем его к 0.0.0.0 и порту 8080 (или через переменную окружения PORT)
CMD gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --access-logfile - main:app
