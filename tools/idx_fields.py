"""Shared NLAR RETS field selection for idx-ingest.py (fleet: Gander, Avalon, Goose Bay).

Why this file exists (sites, D-1009-29, 2026-10-09): the three listing repos
each kept their own copy of SAFE_FIELDS_ACTIVE / NEVER_PROJECT inside
tools/idx-ingest.py, and the copies drifted. Gander kept 122 feed fields;
Avalon 97 and Goose Bay 95, and both also denylisted PendingDate, Possession
and SignYN. The generators on all three sites already read those fields, so
on Avalon and Goose Bay the sold "Under contract" timeline was silently empty
(Goose Bay sold data 2026-10-08: 0 of 156 rows with a pending date).

The two sets below are copied verbatim from realestategander-site
tools/idx-ingest.py on origin/main 0e81cdd5b2 (2026-10-09). They must stay
byte-identical in every repo that carries this file (tier-1 shared file), and
equal to Gander's lists: tools/tests/idx-fields-parity-test.py pins both
sets and, when a sibling Gander checkout is present, compares against it.

RETS request size: every Property search sends no Select parameter (fields
"*", COMPACT-DECODED), so the server already returns every column and this
allowlist is applied client-side in project_record(). Adding names here does
not change the request, the RETS Select length or the row count; it only
changes which columns are kept in tools/idx-cache/*.json.

SOLD_DISPLAY_HOLD (below the Gander block) is not part of Gander's file: it
lists the fields that Avalon / Goose Bay now STORE but do not yet SHOW. The
sold-data emitter in ddf-generate-pages.py strips them before building the
VOW sold rows, so those pages render exactly as before. Showing them is a
later design call; removing a name from SOLD_DISPLAY_HOLD is the switch.
PendingDate is deliberately not held: filling the "Under contract" row is
the point of this change.

Lease fields (sites, D-1009-77, 2026-10-09): TransactionType, LeasePrice and
Leasetype are kept, and TransactionType is no longer denylisted. It was
dropped on 2026-05-07 as "SALE/LEASE -- redundant for our pipeline" while
rentals were out of scope; D-1009-77 puts rentals in scope (rent per month,
no mortgage estimate on a lease). Gander now imports this same file too, so
the three repos carry one byte-identical copy. First full use comes after the
next scheduled ingest; rows ingested before then fall back to the counted
rules in tools/_listing_terms.py.
"""

# ─── Begin: verbatim from realestategander-site tools/idx-ingest.py ───
# SAFE_FIELDS allowlist — only these fields are projected to the cache.
# Anything else is excluded by default (cleaner than a redact denylist
# which would fail open when Matrix adds new internal-only fields).
#
# Validated against live Matrix Property:Listing schema 2026-05-07.
SAFE_FIELDS_ACTIVE = {
    # Identifiers
    "MLSNumber", "Matrix_Unique_ID",
    # Status + lifecycle
    "Status", "ListingContractDate", "ExpirationDate",
    "OriginalEntryTimestamp", "MatrixModifiedDT",
    "PhotoModificationTimestamp", "PriceChangeTimestamp",
    "LastChangeTimestamp", "LastChangeType", "LastStatus", "LastListPrice",
    "DOM", "CDOM",
    # Pricing
    "ListPrice", "OriginalListPrice", "CurrentPrice",
    # Address
    "AddressLine", "StreetNumber", "StreetName", "StreetSuffix",
    "UnitNumber", "StreetNumberNumeric",
    "City", "CityText", "PostalCode", "Subdistrict", "District", "Area",
    "StateOrProvince", "Latitude", "Longitude",
    # Property characteristics
    "PropertyType", "PropertySubType", "BuildingType", "AttachedDetached",
    "StyleOfDwelling", "TitleOfUnderlying",
    "BedsTotal", "BdrmAboveGrade", "BdrmBelowGrade",
    "BathsFull", "BathsHalf", "BathsTotal",
    "TotalLivingAreaSqFt", "BasementAreaSqFt",
    "YearBuilt", "YearBuiltDesc", "NewConstructionOnly", "Lotsize", "TreedAcres", "WorkableAcres",
    "PropertySize",
    # Construction details (Track A.1 enrichment 2026-05-07)
    # NL-specific consumer concerns: heating type, foundation, garage,
    # rear access. Surfaced on listing-detail Property Details section.
    "HeatingCooling",          # Oil/electric/heat pump/wood — NL energy concern
    "Foundation",              # Slab/poured concrete/piers — insurability + reno
    "GarageYN", "GarageType", "GarageAreaSqFt",  # 2-car attached / single / none
    # Vendor — NLAR Matrix builder/developer field (Mike-confirmed 2026-05-26;
    # sample value "JOB Construction"). Display GATED to new-construction
    # lifecycle only — on resale homes Vendor may contain homeowner name
    # (PIPEDA / CREA Rule 6 privacy concern). Convention #15 propagation from
    # Avalon canonical 24cdba8c4 2026-05-26.
    "Vendor",
    "RearFieldAccess",         # Yes/No — backyard access (NL-specific)
    # Description (consumer-safe)
    "PublicRemarks",
    # Agent + office (display-allowed; redact phone/email per VOW rules)
    "ListAgentFullName", "ListOfficeName",
    # Sold-specific (only populated on Status=S)
    "ClosePrice", "CloseDate",
    "PendingDate",        # Added 2026-05-18 bike-window — feeds days_to_pending
                          # + "Under contract X" timeline row per Mike directive.
                          # Was previously denylisted; T&C clarification clears it.
    "SellingAgentFullName", "SellingOfficeName",
    # Photo + media metadata
    "PhotoCount",
    # Features list
    "Access", "Road", "Sewer", "Water", "Services", "LandFeatures",
    "Waterfrontyn",
    # VOW eligibility flags
    "IDXOptInYN", "PublishToInternetSitesYN", "PublishToPublicSitesYN",
    "DDFIncludeYN", "ReleaseCREAFlagYN",
    # Tax + fees (Track A.1 enrichment 2026-05-07 — operating cost transparency)
    "Taxamount", "Taxyear",
    "CondoFee",                # Monthly condo fee — conditional on listing type
    "MobileLeasedLandFees",    # Mobile/trailer park land lease — niche but important
    # Operating cost transparency (Track A.1 enrichment 2026-05-07)
    # When listing agents fill these in, they're a real consumer differentiator
    # — no NL competitor surfaces them. Consent-bound: agent-entered values only.
    "HeatingBill", "WaterBill", "ElectricBill",
    # School zones (Track A.1 enrichment 2026-05-07)
    # NOTE: lowercase 's' is the actual RETS schema spelling — verified
    # against tools/idx-cache/idx-metadata.json on 2026-05-07.
    "Elementaryschool", "Secondaryschool",
    "Driveway", "Drivewaydetails",
    # Virtual tour (consumer-safe)
    "VirtualTourURL",
    "VirtualTourURL2Unbranded",  # Unbranded backup URL
    "VtourPublicAccessYN",       # Boolean gate for public VTour link
    "DDFMoreInfoURL",            # Agent "more info" field — common YouTube
                                  # tour location (Mike 2026-05-23 MLS 1297950
                                  # had YouTube video here, iGuide in
                                  # VirtualTourURL). Generator filters by
                                  # video-host allowlist at render time so
                                  # non-video URLs (PDFs etc) skip safely.
    # ─── Client Full parity expansion (2026-05-11 Decision A: big-bang ship) ───
    # Per _research/Client_Full_Parity_Design_Spec_2026-05-11.md
    # Mike sign-off 2026-05-11. All consumer-safe; Possession + SignYN moved
    # OUT of NEVER_PROJECT for L1 layout's Disclosures section.
    "SideOfRoad",          # "North", "South", "East", "West" — NL niche
    "Title",               # "Freehold" / "Leasehold" — Title to Land
    "Zoning",              # "RES", "C1", "M2" etc. — Title to Land
    "Possession",          # "Immediate", "30 days", "Negotiable" etc.
    "NumberOfFloors",      # "1.5", "2", "Bungalow", etc. — informational
    # Per-floor area breakdown — Main is base in TotalLivingAreaSqFt minus
    # higher floors; surface 2nd/3rd/4th separately when populated.
    "SecondFloorAreaSqFt", "ThirdFloorAreaSqFt", "FourthFloorAreaSqFt",
    # Features (appliances list + interior features)
    "Features",            # Comma-list: "Fridge, Microwave, Stove, Washer, Dryer"
    "InteriorFeatures",    # "Hardwood floors, vaulted ceiling, fireplace" etc.
    # Exterior + roof + flooring + foundation details
    "Exterior",            # "Vinyl", "Brick", "Aluminum" etc.
    "ExteriorMaintenance", # Maintenance condition descriptor
    "Roof",                # "Shingle - Asphalt", "Metal" etc.
    "Flooring",            # "Hardwood, Laminate" etc.
    # Disclosure flags — Decision D sign-off (show in Disclosures section)
    "Uffi",                # "Yes", "No", "Unknown" — Urea-formaldehyde foam insulation
    "SignYN",              # Sign installed at property — consumer-relevant
    # Rental income fields — Decision E sign-off (conditional render when multi-family)
    "Rentalincome",        # "Yes" / "No" / dollar figure
    "TotalRentalIncome",   # Total annual rental income
    "NumberRentalUnits",   # Count of rental units
    "RentalAreaCount",
    "UnitsOneBedroom", "UnitsTwoBedroom",
    "UnitsThreeBedroom", "UnitsFourBedroom",
    # Tax + assessment
    "Watertax",            # Annual water tax — separate from property taxes
    # Lease listings (sites, D-1009-77, 2026-10-09). Metadata 2026-05-07:
    # TransactionType = Lookup "Transaction Type" (SALE/LEASE);
    # LeasePrice = Decimal(16,2) "Lease Price"; Leasetype = Lookup "LeaseType".
    "TransactionType", "LeasePrice", "Leasetype",
}

# Internal-only fields explicitly NEVER project (defensive denylist
# overlay — even if accidentally added to SAFE_FIELDS, these get redacted)
NEVER_PROJECT = {
    "RealtorRemarks",          # Internal-only commentary
    "Seller1LastNam", "Seller1isCompanyYN",  # Seller PII
    "CooperatingCommission",   # Commission split
    "ListAgentEmail", "ListAgentDirectWorkPhone",  # Agent PII
    "ListAgentMLSID", "ListAgent_MUI",  # Internal IDs
    "ListOfficeMLSID", "ListOffice_MUI",  # Internal IDs
    "ListOfficePhone",         # Office direct line (varies by site policy)
    "ShowingService",          # Internal routing
    # NOTE: Possession + SignYN MOVED out of denylist 2026-05-11 per Client
    # Full parity Decision D sign-off. They surface in the L1 Disclosures section.
    "Documents", "SupplementCount", "SupplementModificationTimestamp",
    "StatusContractualSearchDate",
    "ParcelNumber",            # Could be useful for property-history join,
                               # but excluded from public cache by default
    # PendingDate REMOVED from denylist 2026-05-18 bike-window per Mike's
    # T&C clarification: only close_price is strictly VOW-gated; all other
    # fields can ship to the cache. emit_sold_data() reads PendingDate to
    # compute days_to_pending + "Under contract X" timeline row.
    "GeocodeSource",           # Internal data-quality marker
    "MLS",                     # Always "NLAR" — redundant
    # TransactionType REMOVED from the denylist 2026-10-09 (sites, D-1009-77):
    # the SALE/LEASE flag is how a lease is told from a sale (it was dropped
    # 2026-05-07 as "redundant" while rentals were out of scope).
}

# ─── End: verbatim from realestategander-site tools/idx-ingest.py ───


# Stored on Avalon / Goose Bay from 2026-10-09 but held back from the sold
# pages until the display design call (see module docstring). These are the
# fields Gander kept and Avalon / Goose Bay did not, minus PendingDate.
# Vendor and DDFMoreInfoURL are listed because Goose Bay did not keep them;
# Avalon already kept and showed both, so ddf-generate-pages.py there passes
# a site-specific exemption for them (SOLD_DISPLAY_HOLD_EXEMPT).
SOLD_DISPLAY_HOLD = frozenset({
    "Driveway", "Drivewaydetails",
    "Exterior", "ExteriorMaintenance", "Flooring", "Roof",
    "NumberOfFloors",
    "SecondFloorAreaSqFt", "ThirdFloorAreaSqFt", "FourthFloorAreaSqFt",
    "Possession", "SideOfRoad", "SignYN", "Title", "Uffi", "Watertax",
    "Rentalincome", "TotalRentalIncome", "NumberRentalUnits",
    "RentalAreaCount",
    "UnitsOneBedroom", "UnitsTwoBedroom",
    "UnitsThreeBedroom", "UnitsFourBedroom",
    "DDFMoreInfoURL", "Vendor",
})


def hold_sold_display_fields(record, exempt=frozenset()):
    """Return a copy of a raw cache row without the held display fields.

    Used by the sold-data emitter so newly stored fields do not reach the
    VOW sold pages before the display decision. `exempt` names fields a site
    already showed before the parity change (Avalon: Vendor, DDFMoreInfoURL).
    """
    held = SOLD_DISPLAY_HOLD - frozenset(exempt)
    return {k: v for k, v in record.items() if k not in held}
