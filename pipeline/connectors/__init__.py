"""Registro de conectores: cada uno es independiente y expone fetch(source_key, start)."""
from . import ams, eia, fred, nyfed, noaa, worldbank

CONNECTORS = {
    "fred": fred.fetch,
    "worldbank": worldbank.fetch,
    "nyfed": nyfed.fetch,
    "eia": eia.fetch,
    "ams": ams.fetch,
    "noaa_oni": noaa.fetch_oni,
}

SOURCE_LABELS = {
    "fred": "FRED — Federal Reserve Bank of St. Louis",
    "worldbank": "Banco Mundial — Pink Sheet",
    "nyfed": "Federal Reserve Bank of New York",
    "eia": "U.S. Energy Information Administration",
    "ams": "USDA AMS — MyMarketNews",
    "noaa_oni": "NOAA Climate Prediction Center",
}
