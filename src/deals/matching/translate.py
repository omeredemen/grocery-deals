"""English -> German for common shopping list items.

The offers are German, so English list items are translated before matching:
"milk" -> "Milch", "chicken breast" -> "Hähnchenbrust". Unknown words are left
unchanged (they might be German, or brand names like "Nutella").
Keys are lowercase singular; plurals are handled by translate().
"""

EN_DE: dict[str, str] = {
    # dairy & eggs
    "milk": "Milch", "whole milk": "Vollmilch", "skimmed milk": "fettarme Milch", "oat milk": "Haferdrink",
    "soy milk": "Sojadrink", "coconut milk": "Kokosmilch", "egg": "Eier", "butter": "Butter",
    "cheese": "Käse", "cream cheese": "Frischkäse", "sliced cheese": "Käse", "grated cheese": "Reibekäse",
    "gouda": "Gouda", "mozzarella": "Mozzarella", "feta": "Feta", "parmesan": "Parmesan",
    "cheddar": "Cheddar", "camembert": "Camembert", "yogurt": "Joghurt", "yoghurt": "Joghurt",
    "quark": "Quark", "cream": "Sahne", "whipping cream": "Schlagsahne", "cooking cream": "Kochsahne",
    "sour cream": "Schmand", "margarine": "Margarine",
    # bakery & breakfast
    "bread": "Brot", "toast": "Toastbrot", "roll": "Brötchen", "bread roll": "Brötchen",
    "croissant": "Croissant", "cake": "Kuchen", "waffle": "Waffeln", "wrap": "Wraps",
    "tortilla": "Wraps", "oat": "Haferflocken", "oatmeal": "Haferflocken", "porridge": "Porridge",
    "muesli": "Müsli", "granola": "Müsli", "cereal": "Müsli", "cornflake": "Cornflakes",
    "honey": "Honig", "jam": "Konfitüre", "peanut butter": "Peanut Butter",
    # drinks
    "coffee": "Kaffee", "coffee bean": "Kaffee", "ground coffee": "Kaffee", "espresso": "Espresso",
    "tea": "Tee", "green tea": "Grüner Tee", "water": "Mineralwasser", "mineral water": "Mineralwasser",
    "sparkling water": "Mineralwasser", "juice": "Saft", "orange juice": "Orangensaft",
    "apple juice": "Apfelsaft", "beer": "Bier", "wine": "Wein", "red wine": "Rotwein",
    "white wine": "Weißwein", "sparkling wine": "Sekt", "cola": "Cola", "lemonade": "Limonade",
    # baking & pantry
    "sugar": "Zucker", "flour": "Mehl", "salt": "Salz", "pepper": "Pfeffer", "oil": "Öl",
    "olive oil": "Olivenöl", "sunflower oil": "Sonnenblumenöl", "vinegar": "Essig",
    "yeast": "Hefe", "baking powder": "Backpulver", "rice": "Reis", "pasta": "Pasta",
    "noodle": "Nudeln", "spaghetti": "Spaghetti", "chickpea": "Kichererbsen", "lentil": "Linsen",
    "bean": "Bohnen", "pea": "Erbsen", "corn": "Mais", "tofu": "Tofu", "ketchup": "Ketchup",
    "mustard": "Senf", "mayonnaise": "Mayonnaise", "mayo": "Mayonnaise", "tomato paste": "Tomatenmark",
    "pesto": "Pesto", "soy sauce": "Sojasauce",
    # snacks
    "chocolate": "Schokolade", "chip": "Chips", "crisp": "Chips", "cookie": "Kekse", "biscuit": "Kekse",
    "nut": "Nüsse", "almond": "Mandeln", "popcorn": "Popcorn", "ice cream": "Eis", "gummy bear": "Fruchtgummi",
    # vegetables
    "tomato": "Tomaten", "potato": "Kartoffeln", "onion": "Zwiebeln", "red onion": "rote Zwiebeln",
    "spring onion": "Lauchzwiebeln", "garlic": "Knoblauch", "carrot": "Möhren", "cucumber": "Gurke",
    "bell pepper": "Paprika", "lettuce": "Salat", "salad": "Salat",
    "spinach": "Spinat", "broccoli": "Brokkoli", "cauliflower": "Blumenkohl", "zucchini": "Zucchini",
    "courgette": "Zucchini", "mushroom": "Champignons", "leek": "Porree", "pumpkin": "Kürbis",
    "avocado": "Avocado", "ginger": "Ingwer", "cabbage": "Kohl", "aubergine": "Aubergine",
    "eggplant": "Aubergine", "sweet potato": "Süßkartoffeln", "radish": "Radieschen",
    # fruit
    "apple": "Äpfel", "banana": "Bananen", "pear": "Birnen", "grape": "Trauben", "orange": "Orangen",
    "lemon": "Zitronen", "lime": "Limetten", "strawberry": "Erdbeeren", "blueberry": "Heidelbeeren",
    "raspberry": "Himbeeren", "kiwi": "Kiwi", "mango": "Mango", "pineapple": "Ananas",
    "melon": "Melone", "watermelon": "Wassermelone", "plum": "Pflaumen", "mandarin": "Mandarinen",
    "clementine": "Clementinen",
    # meat & fish
    "minced meat": "Hackfleisch", "mince": "Hackfleisch", "ground beef": "Hackfleisch",
    "ground meat": "Hackfleisch", "chicken": "Hähnchen", "chicken breast": "Hähnchenbrust",
    "chicken leg": "Hähnchenschenkel", "turkey": "Pute", "pork": "Schweinefleisch", "beef": "Rindfleisch",
    "steak": "Steak", "sausage": "Würstchen", "bacon": "Bacon", "ham": "Schinken", "salami": "Salami",
    "salmon": "Lachs", "smoked salmon": "Räucherlachs", "tuna": "Thunfisch", "fish": "Fisch",
    "shrimp": "Garnelen", "prawn": "Garnelen",
    # household & drugstore
    "toilet paper": "Toilettenpapier", "toilet roll": "Toilettenpapier", "kitchen roll": "Küchentücher",
    "paper towel": "Küchentücher", "dish soap": "Spülmittel", "washing up liquid": "Spülmittel",
    "dishwasher tab": "Spülmaschinentabs", "detergent": "Waschmittel", "laundry detergent": "Waschmittel",
    "shampoo": "Shampoo", "toothpaste": "Zahnpasta", "soap": "Seife", "deodorant": "Deo",
    "diaper": "Windeln", "nappy": "Windeln", "tissue": "Taschentücher", "trash bag": "Müllbeutel",
    "bin bag": "Müllbeutel", "pizza": "Pizza", "frozen pizza": "Pizza",
}

# English filter words -> the filter the matcher understands.
FILTERS_EN_DE = {"organic": "bio", "lactose-free": "laktosefrei", "lactose free": "laktosefrei",
                 "vegan": "vegan", "decaf": "entkoffeiniert"}


def _singular_forms(word: str) -> list[str]:
    forms = [word]
    if word.endswith("ies"):
        forms.append(word[:-3] + "y")       # strawberries -> strawberry
    if word.endswith("oes"):
        forms.append(word[:-2])             # tomatoes -> tomato
    if word.endswith("es"):
        forms.append(word[:-1])             # sausages -> sausage (via "s" below too)
    if word.endswith("s"):
        forms.append(word[:-1])             # eggs -> egg
    return forms


def translate(query: str) -> str | None:
    """German translation of an English item, or None if it's not in the dictionary."""
    words = query.lower().strip().split()
    if not words:
        return None
    # Make the last word singular: "chicken breasts" -> "chicken breast".
    for last in _singular_forms(words[-1]):
        key = " ".join(words[:-1] + [last])
        if key in EN_DE:
            return EN_DE[key]
    return None
