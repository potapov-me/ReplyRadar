# Настройка LM Studio

ReplyRadar использует LM Studio как локальный LLM-бэкенд. Все вызовы — через OpenAI-совместимый API, данные не покидают локальный контур.

---

## Установка и запуск LM Studio

1. Скачай LM Studio с [lmstudio.ai](https://lmstudio.ai)
2. Установи, запусти приложение
3. Перейди на вкладку **Local Server** (иконка `<->` в левом меню)
4. Нажми **Start Server** — по умолчанию поднимается на `http://localhost:1234`

---

## Рекомендуемые модели

### Classify и Extract (chat completion)

Нужна модель с хорошим следованием инструкциям и надёжным JSON-выводом.

| Модель | Размер | Комментарий |
|--------|--------|-------------|
| **Qwen2.5-7B-Instruct** | ~5 GB (Q4) | Лучший выбор для JSON-задач при ограниченной VRAM |
| **Llama-3.2-3B-Instruct** | ~2 GB (Q4) | Если мало памяти; хуже держит схему |
| **Mistral-7B-Instruct-v0.3** | ~5 GB (Q4) | Хороший вариант, стабильный JSON |
| **Phi-3.5-mini-instruct** | ~2.5 GB (Q4) | Быстрый, но иногда добавляет markdown-обёртку |

> Клиент (`llm/client.py`) автоматически вырезает markdown-обёртки ` ```json ... ``` ` — это покрыто.

### Embeddings

| Модель | Размер | Комментарий |
|--------|--------|-------------|
| **nomic-embed-text-v1.5** | ~275 MB | **Рекомендуется** — совпадает с `embedding.model` в конфиге, 768 измерений |
| text-embedding-3-small (заглушка) | — | Только если работаешь с OpenAI API вместо LM Studio |

---

## Загрузка моделей в LM Studio

1. Вкладка **Discover** → поиск по имени (например `Qwen2.5-7B-Instruct`)
2. Нажми **Download** на нужный вариант квантизации
3. После загрузки — вкладка **Local Server** → **Select a model to load** → выбери модель → **Load**
4. Для embeddings: загрузи `nomic-embed-text-v1.5` в отдельном слоте (LM Studio поддерживает одновременно chat + embedding модель)

---

## Конфигурация ReplyRadar

В `config/default.yaml` уже настроены значения по умолчанию:

```yaml
llm:
  base_url: http://host.docker.internal:1234/v1  # внутри Docker
  model: local-model   # LM Studio игнорирует имя модели — используется загруженная
  api_key: lm-studio   # произвольная строка, LM Studio не проверяет

embedding:
  provider: lmstudio
  model: text-embedding-nomic-embed-text-v1.5
  base_url: http://host.docker.internal:1234/v1
```

При запуске **вне Docker** (например `uvicorn` напрямую) замени `host.docker.internal` на `localhost` в `.env`:

```env
LLM__BASE_URL=http://localhost:1234/v1
EMBEDDING__BASE_URL=http://localhost:1234/v1
```

---

## Проверка соединения

```bash
# Должен вернуть {"lm_studio": "reachable", ...}
curl http://localhost:8000/status | python -m json.tool
```

Если `"lm_studio": "unreachable"` — убедись, что:
- LM Studio Server запущен (кнопка **Start Server**)
- Модель загружена в слот
- `base_url` в конфиге указывает на правильный адрес

---

## Поведение при недоступности LM Studio

- Сообщения из ingestion **не теряются** — они остаются в таблице `messages` с `classified_at = NULL`
- Processing Engine переходит в режим ожидания — backfill-loop спит и проверяет каждые 5 секунд
- При восстановлении LM Studio обработка возобновляется автоматически без перезапуска приложения
- `GET /status` покажет `"lm_studio": "unreachable"` для мониторинга
