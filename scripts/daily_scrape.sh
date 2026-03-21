#!/bin/bash
# Daily scrape of all supermarkets for api_offer
# Run via cron: 0 6 * * * /home/erpnext/.services/api_offer/scripts/daily_scrape.sh
#
# Scrapes all 8 supermarkets sequentially, then triggers:
# - Category classification
# - NutriScore enrichment
# - Image enrichment

set -o pipefail

API="http://127.0.0.1:6958/offer/api/v1"
source /home/erpnext/.services/api_offer/.env
KEY="$ADMIN_API_KEY"
LOG="/var/log/api_offer/daily_scrape.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') === Daily scrape started ===" >> "$LOG"

for SUPER in mercadona carrefour masymas alimerka aldi alcampo familia gadis; do
    echo "$(date '+%H:%M:%S') Scraping $SUPER..." >> "$LOG"
    RESULT=$(curl -s --max-time 600 -X POST "$API/offers/scrape/$SUPER" -H "X-API-Key: $KEY" 2>&1)
    echo "  $SUPER: $RESULT" >> "$LOG"
    sleep 5
done

# Post-scrape enrichments
echo "$(date '+%H:%M:%S') Classifying categories..." >> "$LOG"
curl -s --max-time 60 -X POST "$API/offers/classify-categories" -H "X-API-Key: $KEY" >> "$LOG" 2>&1
echo "" >> "$LOG"

echo "$(date '+%H:%M:%S') Enriching NutriScore..." >> "$LOG"
curl -s --max-time 10 -X POST "$API/offers/enrich-nutriscore" -H "X-API-Key: $KEY" >> "$LOG" 2>&1
echo "" >> "$LOG"

echo "$(date '+%H:%M:%S') Enriching images..." >> "$LOG"
curl -s --max-time 10 -X POST "$API/offers/enrich-images" -H "X-API-Key: $KEY" >> "$LOG" 2>&1
echo "" >> "$LOG"

# Non-food police: deactivate any non-food that slipped through
echo "$(date '+%H:%M:%S') Running non-food cleanup..." >> "$LOG"
cd /home/erpnext/.services/api_offer
/home/erpnext/api_offer_env/bin/python -c "
import asyncio
from src.db.session import AsyncSessionLocal
from src.services.oferta_service import _is_non_food
from sqlalchemy import select, update
from src.models.oferta import Oferta

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Oferta).where(Oferta.activo == True))
        active = list(result.scalars().all())
        ids = [o.id for o in active if _is_non_food(o.producto_nombre)]
        if ids:
            await db.execute(update(Oferta).where(Oferta.id.in_(ids)).values(activo=False))
            await db.commit()
        print(f'Non-food cleanup: {len(ids)} removed')

asyncio.run(main())
" >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') === Daily scrape finished ===" >> "$LOG"
