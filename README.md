# api_offer

API for supermarket offers and promotions scraping and management.

## Stack

- **Framework:** FastAPI
- **Database:** PostgreSQL (async via SQLAlchemy + asyncpg)
- **Scraping:** httpx + BeautifulSoup4 + Playwright
- **Migrations:** Alembic
- **Server:** Gunicorn + Uvicorn workers

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

Copy `.env.example` to `.env` and fill in the required values.

```bash
alembic upgrade head
```

## Running

```bash
gunicorn app.main:app -c gunicorn.conf.py
```

## URL

Served at `https://raquel.pibico.es/offer/`

## License

MIT - see [LICENSE](LICENSE)
