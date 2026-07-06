import json
import os
import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Wardrobe Stylist Server")

DB_FILE = "wardrobe.json"

def init_db():
    if not os.path.exists(DB_FILE):
        default_items = [
            {"id": 1, "name": "Classic Blue Denim Jeans", "category": "bottom", "color": "blue", "material": "denim", "wear_count": 5},
            {"id": 2, "name": "White Cotton T-Shirt", "category": "top", "color": "white", "material": "cotton", "wear_count": 12},
            {"id": 3, "name": "Black Leather Boots", "category": "shoes", "color": "black", "material": "leather", "wear_count": 8},
            {"id": 4, "name": "Beige Wool Trench Coat", "category": "jacket", "color": "beige", "material": "wool", "wear_count": 3},
            {"id": 5, "name": "Floral Summer Dress", "category": "dress", "color": "floral", "material": "silk", "wear_count": 1}
        ]
        with open(DB_FILE, "w") as f:
            json.dump(default_items, f, indent=4)

def read_db():
    init_db()
    with open(DB_FILE, "r") as f:
        return json.load(f)

def write_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

@mcp.tool()
def list_wardrobe_items() -> str:
    """Lists all the clothing items in the wardrobe database."""
    items = read_db()
    return json.dumps(items, indent=2)

@mcp.tool()
def add_wardrobe_item(name: str, category: str, color: str, material: str) -> str:
    """Adds a new clothing item to the wardrobe inventory.
    
    Args:
        name: Name or description of the clothing item (e.g. 'Red Silk Blouse').
        category: Clothing category (e.g. 'top', 'bottom', 'shoes', 'jacket', 'dress').
        color: Color of the item.
        material: Material/fabric of the item.
    """
    items = read_db()
    new_id = max([item["id"] for item in items], default=0) + 1
    new_item = {
        "id": new_id,
        "name": name,
        "category": category,
        "color": color,
        "material": material,
        "wear_count": 0
    }
    items.append(new_item)
    write_db(items)
    return f"Successfully added item: {new_item}"

@mcp.tool()
def log_wear_frequency(item_id: int) -> str:
    """Increments the wear frequency count of a specific clothing item.
    
    Args:
        item_id: The ID of the item being worn.
    """
    items = read_db()
    for item in items:
        if item["id"] == item_id:
            item["wear_count"] += 1
            write_db(items)
            return f"Logged wear for '{item['name']}'. New wear count: {item['wear_count']}"
    return f"Error: Clothing item with ID {item_id} not found."

@mcp.tool()
def get_weather_forecast(city: str) -> str:
    """Gets the simulated current weather and temperature for a given city to plan appropriate outfits.
    
    Args:
        city: The name of the city (e.g., 'San Francisco', 'New York', 'Tokyo').
    """
    city_lower = city.lower()
    if "sf" in city_lower or "san francisco" in city_lower:
        return json.dumps({"city": "San Francisco", "weather": "foggy and cool", "temperature": "60 F", "condition": "cool"})
    elif "new york" in city_lower or "ny" in city_lower:
        return json.dumps({"city": "New York", "weather": "rainy and brisk", "temperature": "55 F", "condition": "rainy"})
    elif "tokyo" in city_lower:
        return json.dumps({"city": "Tokyo", "weather": "sunny and hot", "temperature": "85 F", "condition": "hot"})
    else:
        return json.dumps({"city": city, "weather": "clear skies", "temperature": "72 F", "condition": "mild"})

if __name__ == "__main__":
    mcp.run()
