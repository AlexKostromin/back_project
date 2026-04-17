FROM python:3.11-slim

# Устанавливаем Poetry — менеджер зависимостей
RUN pip install --no-cache-dir poetry

WORKDIR /app

# Копируем файлы зависимостей отдельно от кода
# Если pyproject.toml не менялся — Docker не переустанавливает пакеты
COPY pyproject.toml poetry.lock* ./

# Устанавливаем зависимости
# virtualenvs.create false — не нужен в контейнере
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction --no-ansi

# Копируем весь код проекта
COPY . .

EXPOSE 8000

# Запускаем FastAPI через uvicorn
# main:app — файл main.py, объект app = FastAPI()
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]