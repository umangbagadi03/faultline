"""
Mock tools for the demo travel-booking agent.

They behave like real APIs (validate args, return data, raise errors)
but run fully offline and deterministically. Replay uses them to
re-execute a failed step with the proposed fix.
"""

import re

from ..schema import ToolSpec


class ToolError(Exception):
    pass


PRICES = {"Mumbai": 4520, "Delhi": 6150, "Bengaluru": 3890, "Goa": 5275, "Jaipur": 4710}


def search_flights(origin: str, destination: str, date: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
        raise ToolError(f"invalid date '{date}', expected YYYY-MM-DD")
    price = PRICES.get(destination, 4999)
    return [
        {"flight_id": f"6E-{len(origin)}{len(destination)}1", "price": price, "stops": 0},
        {"flight_id": f"AI-{len(origin)}{len(destination)}7", "price": price + 830, "stops": 1},
    ]


def book_flight(flight_id: str, passengers: int):
    if not isinstance(passengers, int):
        raise ToolError(f"passengers must be an integer, got {passengers!r}")
    return {"booking_id": f"BK-{flight_id}-{passengers}", "status": "confirmed"}


def get_weather(city: str):
    return {"city": city, "forecast": "sunny", "temp_c": 31}


def get_hotel_reviews(city: str):
    return {"city": city, "reviews": ["Clean rooms, friendly staff.", "Great breakfast."]}


def send_email(to: str, body: str):
    return {"sent": True, "to": to}


MOCK_TOOLS = {
    "search_flights": search_flights,
    "book_flight": book_flight,
    "get_weather": get_weather,
    "get_hotel_reviews": get_hotel_reviews,
    "send_email": send_email,
}

TOOL_SPECS = [
    ToolSpec(name="search_flights", params={"origin": "str", "destination": "str", "date": "date"},
             required=["origin", "destination", "date"]),
    ToolSpec(name="book_flight", params={"flight_id": "str", "passengers": "int"},
             required=["flight_id", "passengers"]),
    ToolSpec(name="get_weather", params={"city": "str"}, required=["city"]),
    ToolSpec(name="get_hotel_reviews", params={"city": "str"}, required=["city"]),
    ToolSpec(name="send_email", params={"to": "str", "body": "str"}, required=["to", "body"],
             sensitive=True),
]


def call_tool(name: str, args: dict):
    """Call a mock tool the same way an agent framework would."""
    func = MOCK_TOOLS.get(name)
    if func is None:
        raise ToolError(f"tool '{name}' not found")
    try:
        return func(**args)
    except TypeError as e:
        raise ToolError(str(e))
