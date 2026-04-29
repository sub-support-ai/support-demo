# ai-dataset

Генератор синтетического датасета для классификатора корпоративных тикетов
(IT / HR / финансы). Использует **Qwen** (или любой OpenAI-совместимый LLM) через
Python `openai` SDK.

## Таксономия — два уровня

Источник истины контракта с RestAPI: `RestAPI/docs/ai-lead-contract.md` §3.

- **Внутренняя (14 классов)** — на чём учится классификатор. `it_software` разбит
  на `_install` / `_error`, `it_access` — на `_grant` / `_reset`. Это даёт более
  точный сигнал на обучении и аналитику потоков обращений
  (главные потоки helpdesk: смена пароля, выдача доступа, установка ПО, ошибки
  внутренних приложений).

- **Контрактная (12 классов)** — что ai-service возвращает в RestAPI на
  `/ai/classify`. Получается схлопыванием split'ов через
  `schemas.sample.to_contract_category()`. RestAPI про 14 не знает — ему не нужно.

Маппинг и хелперы — в `schemas/sample.py`:
```python
from schemas.sample import to_contract_category, category_to_department

to_contract_category("it_access_reset")    # "it_access"
category_to_department("it_software_error") # "IT"
```

`category_to_department()` совпадает с маппингом контракта §3.3 — это инвариант
датасета, в обучающих данных нет ни одного семпла, нарушающего его.

## Что в репо

```
ai-dataset/
├── taxonomy.yaml           # 14 категорий, 4 приоритета, калибровка
├── prompts/
│   ├── generator.md        # промпт-генератор (system + user шаблон)
│   └── judge.md            # промпт-валидатор
├── schemas/
│   └── sample.py           # Pydantic-модели (Sample, GenerationBatch, JudgeVerdict)
├── scripts/
│   ├── generate.py         # синтез через Qwen
│   ├── judge.py            # LLM-as-judge валидация
│   ├── dedup.py            # TF-IDF cosine дедуп
│   ├── build_splits.py     # стратифицированный train/val/test
│   └── build_seed.py       # вытащить few-shot из существующего run
└── data/
    ├── seed/examples.jsonl # рукописные/отобранные эталоны (few-shot)
    ├── raw/manual_v2/      # 101 ручной семпл (стартовая база)
    ├── raw/<run_id>/       # сырая генерация
    ├── processed/<run_id>/ # после judge + dedup
    └── splits/<run_id>/    # train/val/test
```

## Установка

```bash
cd ai-dataset
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

cp .env.example .env
# в .env раскомментируй блок под свой провайдер (Ollama / DashScope / Together / vLLM)
```

## Конфигурация Qwen

Все скрипты читают из `.env`:

| Переменная | Зачем | Пример |
|---|---|---|
| `OPENAI_BASE_URL` | endpoint провайдера | `http://localhost:11434/v1` |
| `OPENAI_API_KEY` | API-ключ (для Ollama любая строка) | `ollama` |
| `QWEN_MODEL` | id модели | `qwen2.5:72b` |

Готовые шаблоны для Ollama / DashScope / Together / vLLM лежат в `.env.example`.

## Пайплайн

### 0. (Опционально) Перетянуть few-shot из manual_v2

В `data/seed/examples.jsonl` лежит 6 рукописных эталонов. Чтобы Qwen генерировал
ближе к стилю 101 ручного семпла из `manual_v2`, сделай новый seed по 2 семпла на
каждую из 14 категорий:

```bash
python scripts/build_seed.py --from-run manual_v2 --per-category 2
```

Старый seed бэкапится в `examples.jsonl.bak`.

### 1. Генерация

```bash
python scripts/generate.py --run-id v3 --samples-per-combo 2 --concurrency 4
```

Сетка: 14 категорий × 6 персон × 4 тона × 3 длины = **1008 комбинаций**.
При `--samples-per-combo 2` это **2016 семплов**.

Опции:
- `--samples-per-combo N` — семплов на (категория, персона, тон, длина). 1–3 разумно.
- `--concurrency N` — параллельные запросы. Для Ollama локально начни с 2–4, для облачного API можно 8–16.
- `--temperature 0.7` — управляет разнообразием. Для стабильного JSON 0.3–0.7.
- `--model qwen-max` — переопределить `QWEN_MODEL` из env.
- `--dry-run` — показать сетку без вызова API.

**Resumable:** скрипт пишет `data/raw/<run_id>/state.jsonl` и пропускает уже
сгенерированные комбинации при повторном запуске с тем же `--run-id`.

**Структурный вывод** через `response_format={"type": "json_object"}` (JSON mode).
Ответ парсится в Pydantic-схему `GenerationBatch`. При парс-ошибке скрипт
переотправляет до 2 раз перед записью в state как `error`.

### 2. Валидация (LLM-as-judge)

```bash
python scripts/judge.py --run-id v3 --concurrency 4
```

Прогоняет каждый семпл через Qwen и проверяет:
- диалог логично следует к тикету;
- `steps_tried` извлечены из диалога, не выдуманы;
- `department` / `category` / `priority` соответствуют содержанию.

Семплы с неверными метками, но качественным контентом — **переразмечаются**
(judge возвращает `corrected_labels`). Полностью бракованные уходят в
`rejected.jsonl`.

### 3. Дедупликация

```bash
python scripts/dedup.py --run-id v3 --threshold 0.92
```

TF-IDF cosine по `title + body`. Из каждой группы дубликатов оставляет самый
длинный.

### 4. Сплиты

```bash
python scripts/build_splits.py --run-id v3
```

Стратификация по `(department, priority)`. Дефолт 80/10/10.

## Что есть из коробки

В репо уже зафиксирован **`manual_v2`** — **101 ручной семпл** в новой 14-категорной
таксономии с распределением 75% IT / 12% HR / 7% finance / 7% other. Это рабочий
стартовый датасет для обучения и одновременно эталон стиля для генерации.

## Что важно проверить после первого прогона Qwen

1. **Парсабельность JSON.** Если в state.jsonl много `error` с
   `parse/validate:` — модель не держит JSON-mode стабильно. Снизь
   `--temperature` до 0.3, либо смени модель на более крупную.

2. **Открой 30 случайных семплов** из `data/raw/v3/samples.jsonl` и оцени:
   - язык, тон, разнообразие сценариев в одной категории;
   - корректность меток (особенно `priority` по бизнес-влиянию, не по эмоциям);
   - адекватность `steps_tried` (только то, что упомянуто в диалоге).

3. **Распределение** в `data/splits/v3/distribution.json` — для обучения хорошо
   относительно балансированное, для теста — реалистичное (низкий приоритет
   доминирует).

4. **% брака на judge-этапе** — норма 5–15%. Больше 25% → правь
   `prompts/generator.md`.

## Версионирование

Каждый прогон — свой `--run-id`. Меняешь промпт или таксономию — поднимай версию
(`v3`, `v4`), не перезаписывай предыдущую. `manifest.json` в каждом run-каталоге
фиксирует параметры (модель, base_url, температуру и т.д.).
