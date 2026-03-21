"""Shopping list generator — NL prompt → ingredients (via Groq) → best offers (via api_offer)."""

import json
import logging
import re

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Eres un chef profesional español. Tu trabajo es generar listas de ingredientes REALISTAS para recetas.

PROCESO: Antes de responder, piensa en la receta completa paso a paso. Solo incluye ingredientes que realmente se usan en esa receta tradicional. No inventes ni añadas ingredientes que no correspondan.

FORMATO: Responde SOLO con JSON válido, sin texto adicional:
{"ingredientes": [{"nombre": "...", "cantidad": "...", "unidad": "..."}], "presupuesto": null}
El campo presupuesto es un número (float) en euros o null si no se menciona.

REGLAS:
- Solo ingredientes que REALMENTE lleva la receta. Si es sopa de marisco, lleva marisco, caldo, cebolla, ajo, vino blanco... NO lleva queso rallado ni zumo de limón.
- Entre 4 y 10 ingredientes principales. Nada de relleno.
- Nombres genéricos y cortos en español: "gambas", "mejillones", "cebolla", "tomate triturado".
- NO repitas ingredientes ni pongas variantes del mismo (no "lechuga" y "lechuga romana").
- NO incluyas sal, pimienta, aceite de oliva — son básicos que todo el mundo tiene.
- Las cantidades deben ser realistas para el número de personas indicado."""


def _best_match(ingredient: str, offers: list[dict]) -> dict | None:
    """Pick the most relevant offer for a generic ingredient name.

    Scores each offer: higher = better match.
    Prefers offers whose name is short and starts with the ingredient words,
    avoiding matches like 'huevos' → 'huevos de chocolate rellenos'.
    """
    if not offers:
        return None

    ing_words = ingredient.lower().strip().split()
    if not ing_words:
        return offers[0]

    scored = []
    for o in offers:
        name = (o.get("producto_nombre") or "").lower()
        name_words = name.split()[:5]
        score = 0

        # Check if first ingredient word appears in first 2 words of offer name
        if ing_words[0] in name_words[:2]:
            score += 10

        # Bonus: all ingredient words appear in offer name
        if all(w in name for w in ing_words):
            score += 5

        # Penalty: very long names (likely a composite product, not the raw ingredient)
        if len(name_words) > 6:
            score -= 2

        # Penalty: offer name has "sabor", "chocolate", "relleno" etc. (flavored/processed)
        processed_kw = {"sabor", "chocolate", "relleno", "rellena", "crema", "salsa"}
        if any(w in name_words for w in processed_kw):
            score -= 5

        scored.append((score, o))

    scored.sort(key=lambda x: (-x[0], x[1].get("precio_oferta") or 999))
    return scored[0][1]


async def generate_shopping_list(prompt: str) -> dict:
    """Call Groq (Llama 3.1) to generate ingredient list, then search offers for each."""
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not configured")

    # Step 1: Generate ingredients via Groq (OpenAI-compatible API)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1024,
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()
    # Parse JSON from response (handle markdown code blocks)
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Groq returned invalid JSON: %s", content[:500])
        raise ValueError("No se pudo interpretar la respuesta del asistente")

    ingredientes_raw = parsed.get("ingredientes", [])

    # Extract budget from the ORIGINAL user prompt (don't trust Groq's parsing)
    presupuesto = None
    budget_match = re.search(r"presupuesto[:\s]*(?:de\s+)?(\d+[.,]?\d*)\s*(?:€|euro|eur)?", prompt, re.IGNORECASE)
    if not budget_match:
        budget_match = re.search(r"(\d+[.,]?\d*)\s*(?:€|euros?)\b", prompt, re.IGNORECASE)
    if budget_match:
        presupuesto = float(budget_match.group(1).replace(",", "."))
    if presupuesto is None:
        presupuesto = parsed.get("presupuesto")  # fallback to Groq's parsing

    # Deduplicate ingredients by first word (e.g. "lechuga" and "lechuga romana" → keep first)
    seen_names: set[str] = set()
    ingredientes: list[dict] = []
    for ing in ingredientes_raw:
        nombre = (ing.get("nombre") or "").strip().lower()
        first_word = nombre.split()[0] if nombre else ""
        if not nombre or first_word in seen_names:
            continue
        seen_names.add(first_word)
        ingredientes.append(ing)

    # Step 2: Search best offer for each ingredient in our own DB
    results = []
    total = 0.0
    seen_offer_ids: set[int] = set()  # avoid counting same offer twice

    async with httpx.AsyncClient(timeout=10.0) as client:
        for ing in ingredientes:
            nombre = ing.get("nombre", "")
            best_offer = None
            try:
                r = await client.get(
                    "http://127.0.0.1:6958/api/v1/offers/compare",
                    params={"q": nombre, "limit": 10},
                )
                if r.status_code == 200:
                    compare_data = r.json()
                    offers = compare_data.get("results", [])
                    # Filter: prefer offers where the product is actually the ingredient
                    # (not just contains it as a sub-word, e.g. "huevos" != "huevos de chocolate")
                    best = _best_match(nombre, offers) if offers else None
                    if best:
                        offer_id = best.get("id")
                        best_offer = {
                            "producto_nombre": best.get("producto_nombre"),
                            "precio_oferta": best.get("precio_oferta"),
                            "fuente": best.get("fuente"),
                            "producto_url": best.get("producto_url"),
                            "nutriscore": best.get("nutriscore"),
                        }
                        # Only count price once per unique offer
                        if best.get("precio_oferta") and offer_id not in seen_offer_ids:
                            total += best["precio_oferta"]
                            if offer_id:
                                seen_offer_ids.add(offer_id)
            except Exception as exc:
                logger.warning("Offer search failed for '%s': %s", nombre, exc)

            results.append({
                "nombre": nombre,
                "cantidad": ing.get("cantidad", ""),
                "unidad": ing.get("unidad", ""),
                "best_offer": best_offer,
            })

    budget_ok = None
    if presupuesto is not None:
        try:
            presupuesto = float(presupuesto)
            budget_ok = total <= presupuesto
        except (TypeError, ValueError):
            presupuesto = None

    return {
        "ingredients": results,
        "total_estimated": round(total, 2) if total > 0 else None,
        "budget": presupuesto,
        "budget_ok": budget_ok,
    }
