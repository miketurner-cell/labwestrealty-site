"""Synthetic NLAR-shaped rows for the Lab West tests (sites, D-1012-34). Invented streets and prices; no real listing or sale.

sold_full_rows(): about 120 sold rows closing 2024-01 .. 2026-10 in Labrador City and Wabush, plus out-of-scope rows,
deterministic (no randomness), shaped like tools/idx-cache/sold-listings-full.json. The close dates, prices and days on
market are generated from the row index, so a test can recompute any statistic from the same rows.
"""
import datetime


def sold_full_rows(today=datetime.date(2026, 10, 11)):
    rows = []
    towns = [("Labrador City", "A2V 2T1", "Walsh River"), ("Wabush", "A0R 1B0", "Grenfell Drive"), ("Labrador City", "A2V 1W5", "Canning"),
             ("Labrador City", "A2V 2K3", "Hudson Avenue"), ("Wabush", "A0R 1B0", "Birch Drive")]
    start = datetime.date(2024, 1, 8)
    n = 0
    d = start
    while d <= today - datetime.timedelta(days=4):
        town, postal, street = towns[n % len(towns)]
        lp = 140000 + (n % 17) * 9000
        cp = lp - ((n * 7) % 11) * 1500 + (3000 if n % 5 == 0 else 0)
        rows.append({
            "MLSNumber": str(1280000 + n), "StreetNumber": str(1 + (n * 3) % 90), "StreetName": street, "CityText": town, "City": "",
            "PostalCode": postal, "ListPrice": f"{lp}.00", "ClosePrice": f"{cp}.00", "OriginalListPrice": f"{lp + 4000}.00",
            "CloseDate": d.isoformat(), "ListingContractDate": (d - datetime.timedelta(days=20 + (n * 5) % 70)).isoformat(),
            "DaysOnMarket": str(20 + (n * 5) % 70), "Latitude": "52.94", "Longitude": "-66.91", "BedroomsTotal": str(2 + n % 3),
            "BathroomsTotal": "2", "LivingArea": str(1000 + (n % 9) * 80), "PropertyType": "Residential", "PropertySubType": "Single Family",
            "Status": "Sold", "PublishToInternetSitesYN": "1", "PublishToPublicSitesYN": "1", "TransactionType": "SALE",
            "Subdistrict": "Labrador City / Wabush", "YearBuilt": str(1965 + (n % 40)), "ListOfficeName": "Century 21 Big Land Realty Limited - Labrador City",
            "PhotoCount": "3",
        })
        n += 1
        d += datetime.timedelta(days=8 + (n % 3))
    # out of scope: must never reach a Lab West number
    for i in range(6):
        rows.append(dict(rows[i], MLSNumber=str(1270000 + i), CityText="Happy Valley-Goose Bay", PostalCode="A0P 1E0",
                         Subdistrict="Happy Valley / Goose Bay", ClosePrice="999000.00"))
    return rows
