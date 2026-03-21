"""Keyword-based product category classifier for supermarket offers."""

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Lácteos": [
        "leche", "yogur", "queso", "nata", "mantequilla", "kefir", "kéfir",
        "cuajada", "requesón", "flan", "natilla", "batido", "petit suisse",
        "skyr", "quesito", "margarina", "crema de queso",
    ],
    "Carnes": [
        "pollo", "ternera", "cerdo", "jamón", "jamon", "salchich", "chorizo",
        "filete", "pechuga", "lomo", "costilla", "carne", "hamburguesa",
        "albondiga", "albóndiga", "bacon", "panceta", "morcilla", "pavo",
        "cordero", "chuleta", "solomillo", "entrecot", "chuletón",
        "secreto ibérico", "secreto iberico", "magro",
    ],
    "Pescados y mariscos": [
        "merluza", "salmón", "salmon", "atún", "atun", "bacalao", "gamba",
        "langostino", "sardina", "trucha", "lubina", "dorada", "calamar",
        "pulpo", "mejillon", "mejillón", "anchoa", "boquerón", "boqueron",
        "rape", "pez espada", "sepia", "surimi", "pescado", "marisco",
    ],
    "Frutas y verduras": [
        "manzana", "plátano", "platano", "tomate", "lechuga", "fresa",
        "naranja", "limón", "limon", "kiwi", "uva", "melón", "melon",
        "sandía", "sandia", "piña", "pimiento", "cebolla", "ajo",
        "zanahoria", "pepino", "calabacín", "calabacin", "brócoli", "brocoli",
        "espinaca", "champiñón", "champiñon", "seta", "patata", "batata",
        "aguacate", "mango", "cereza", "ciruela", "pera", "melocotón",
        "melocoton", "fruta", "verdura", "ensalada", "rúcula", "rucula",
        "canónigo", "berza", "col", "repollo", "coliflor", "apio",
        "puerro", "remolacha", "nabo", "fresón", "freson",
    ],
    "Bebidas": [
        "agua", "zumo", "cerveza", "vino", "refresco", "cola", "fanta",
        "aquarius", "tónica", "tonica", "sprite", "nestea", "limonada",
        "sangría", "sangria", "sidra", "cava", "champán", "champan",
        "vermouth", "vermut", "ron", "ginebra", "vodka", "whisky",
        "bourbon", "licor", "café", "cafe", "infusión", "infusion",
        "cacao soluble", "colacao", "nesquik", "bebida",
    ],
    "Panadería y bollería": [
        "pan ", "pan de", "baguette", "croissant", "bollería", "bolleria",
        "galleta", "magdalena", "bizcocho", "tostada", "rosquilla",
        "donut", "muffin", "brioche", "panecillo", "chapata", "molde",
        "integral", "centeno", "barra de pan",
    ],
    "Conservas y despensa": [
        "conserva", "aceite", "vinagre", "legumbre", "garbanzo", "lenteja",
        "alubia", "judía", "judia", "arroz", "pasta", "macarrón", "macarron",
        "espagueti", "fideos", "harina", "azúcar", "azucar", "sal ",
        "especia", "salsa", "tomate frito", "ketchup", "mayonesa",
        "mostaza", "miel", "mermelada", "caldo", "sopa", "puré", "pure",
        "cereales", "muesli", "avena", "oliva", "girasol",
        "atún en lata", "sardina en lata", "pimentón",
    ],
    "Congelados": [
        "congelad", "helado", "pizza congelada", "croqueta", "empanada",
        "nugget", "palito de pescado", "verdura congelada",
        "menestra", "guisante congelado",
    ],
    "Charcutería y embutidos": [
        "jamón serrano", "jamon serrano", "jamón york", "jamon york",
        "salami", "mortadela", "fuet", "longaniza", "sobrasada",
        "paté", "pate", "chopped", "fiambre",
    ],
    "Snacks y aperitivos": [
        "patata frita", "chip", "fruto seco", "almendra", "nuez",
        "cacahuete", "pistacho", "anacardo", "palomita", "snack",
        "aperitivo", "aceituna", "pepinillo", "corteza",
    ],
    "Dulces y chocolates": [
        "chocolate", "bombón", "bombon", "chuche", "golosina", "turrón",
        "turron", "caramelo", "regaliz", "chicle", "tableta de chocolate",
    ],
    "Limpieza y hogar": [
        "detergente", "lejía", "lejia", "suavizante", "lavavajilla",
        "fregasuelo", "limpiador", "estropajo", "bayeta", "papel higiénico",
        "papel higienico", "servilleta", "rollo de cocina", "bolsa de basura",
        "ambientador", "insecticida",
    ],
    "Higiene y cuidado personal": [
        "champú", "champu", "gel de ducha", "jabón", "jabon", "desodorante",
        "pasta de dientes", "dentífrico", "cepillo de dientes", "crema hidratante",
        "protector solar", "pañal", "panal", "compresa", "tampón", "tampon",
        "maquinilla", "cuchilla de afeitar", "toallita",
    ],
    "Alimentación infantil": [
        "potito", "papilla", "leche infantil", "biberón", "biberon",
        "hero baby", "nestlé baby", "nestle baby",
    ],
}


def classify(producto_nombre: str) -> str:
    """Classify a product name into a food/household category.

    Returns the category string or "Otros" if no match.
    """
    name_lower = producto_nombre.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return category
    return "Otros"
