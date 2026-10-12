"""Lease rent labels and the availability status, for listing pages and data.json.

Sites, D-1009-77 (2026-10-09). The file is byte-identical in the three listing
repos (realestategander-site, avalonrealestate-site, goosebayrealestate-site);
tools/tests/listings-review-test.py checks it and runs it on real feed rows.

Why: 56 Queens Road, St. John's (MLS 1303923) is a rental at $5,000 a month. It
showed "$5,000", a mortgage estimate and closing-cost links because the only
lease test was "list price under $5,000 plus a lease word". NLAR puts the rent
in ListPrice on a lease listing, and the feed's own SALE/LEASE flag
(TransactionType) was not kept (denylisted 2026-05-07 as "redundant, rentals
out of scope").

Detection, in order:
  1. TransactionType (overlaid as idx_transaction_type). A value naming lease
     and not sale makes the row a lease; a value naming sale and not lease
     makes it a sale. Authoritative once the next scheduled ingest fills it.
  2. Fallback for rows ingested before that field arrived (counted and printed
     on every build by the generator, always-on #8):
       floor   - the pre-2026-10-09 rule: list price under $5,000 plus a lease
                 sign (commercial type, lease subtype, lease words in remarks);
       remarks - list price under $25,000 and the listing's own remarks state
                 that same amount per month ("Lease rate is $5000/month").

Rent and its basis (never assumed):
  rent  = LeasePrice (idx_lease_price) when present and above 0, else the lease
          row's list price (NLAR's lease rate).
  basis = from Leasetype (idx_lease_type) when its value names the period
          ("month", "square foot", "year"); otherwise from the remarks, only
          when they state that same amount with the period ("$17.50 per sq. ft",
          "$2,250 per month"). Anything else: no basis.
  label = "$5,000/month", "$17.50/sq ft", "$12,000/year", "$2,175 (lease)" when
          the basis is not stated, "Contact for rent" when there is no rent.
"""
import html
import re

LEASE_PRICE_FLOOR = 5000          # the pre-2026-10-09 rule: no NL sale under $5K
REMARKS_FALLBACK_CEILING = 25000  # the remarks rule never looks above this

_LEASE_REMARKS_RE = re.compile(
    r"\b(?:lease|leasing|for rent|rental|net rent|nnn|triple net|"
    r"per sq\.? ?ft|/sq\.? ?ft|per square|build-to-suit|build to suit|"
    r"tenant fitup|tenant fit-up|tenant fit up|monthly rent)\b",
    re.IGNORECASE,
)

# An amount followed by its period: "$5000/month", "$2,250 per month",
# "$1,700 monthly", "$17.50 per sq. ft", "$24.00/sf", "$12,000 per year".
_AMOUNT_PERIOD_RE = re.compile(
    r"(?P<d>\$)?\s?(?P<n>\d{1,3}(?:,\d{3})+|\d+)(?P<c>\.\d{1,2})?\s*"
    r"(?:(?P<sep>/|per\b|an?\b)\s*)?"
    r"(?P<u>month\b|mo\b|monthly\b|"
    r"sq\.?\s?ft\b\.?|sq\.?\s?feet\b|square\s+f(?:oo|ee)t\b|sf\b|psf\b|"
    r"year\b|yr\b|annum\b|annually\b)",
    re.IGNORECASE,
)


def _num(v):
    try:
        f = float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _period(word):
    w = word.lower()
    if w.startswith("mo"):
        return "month"
    if w.startswith(("y", "an")):
        return "year"
    return "sqft"


def stated_periods(remarks, amount):
    """Periods the remarks state for exactly this amount ({'month', 'sqft', 'year'})."""
    out = set()
    if not remarks or not amount:
        return out
    for m in _AMOUNT_PERIOD_RE.finditer(remarks):
        val = _num(m.group("n") + (m.group("c") or ""))
        if val is None or abs(val - float(amount)) >= 0.005:
            continue
        period = _period(m.group("u"))
        # "1,800 sq ft" is a size, not a rate: a per-sq-ft or yearly rate
        # needs a "$" or a "/" / "per" before the unit.
        if period != "month" and not (m.group("d") or (m.group("sep") or "").lower() in ("/", "per")):
            continue
        out.add(period)
    return out


def transaction_kind(listing):
    """'lease' | 'sale' | None from TransactionType (None = not present or mixed)."""
    tt = str(listing.get("idx_transaction_type") or "").strip().lower()
    if not tt:
        return None
    lease = ("lease" in tt) or ("rent" in tt)
    sale = ("sale" in tt) or ("sell" in tt)
    if lease and not sale:
        return "lease"
    if sale and not lease:
        return "sale"
    return None


def _floor_rule(listing):
    lp = listing.get("list_price")
    if not isinstance(lp, (int, float)) or lp <= 0 or lp >= LEASE_PRICE_FLOOR:
        return False
    ptype = (listing.get("property_type") or "").lower()
    psub = (listing.get("property_sub_type") or listing.get("property_subtype") or "").lower()
    btype = (listing.get("business_type") or "").lower()
    if "lease" in psub or "lease" in btype or "rental" in psub or "rental" in btype:
        return True
    if "commercial" in ptype:
        return True
    return bool(_LEASE_REMARKS_RE.search(listing.get("public_remarks") or ""))


def detect_lease(listing):
    """(is_lease, source); source is 'transaction_type', 'floor', 'remarks' or None."""
    kind = transaction_kind(listing)
    if kind == "lease":
        return True, "transaction_type"
    if kind == "sale":
        return False, None
    if _floor_rule(listing):
        return True, "floor"
    lp = listing.get("list_price")
    if (isinstance(lp, (int, float)) and 0 < lp < REMARKS_FALLBACK_CEILING
            and "month" in stated_periods(listing.get("public_remarks") or "", lp)):
        return True, "remarks"
    return False, None


def _basis_from_lease_type(value):
    v = str(value or "").strip().lower()
    if not v:
        return ""
    if "month" in v:
        return "month"
    if "sq" in v or "square" in v or "foot" in v or "feet" in v or re.search(r"\bsf\b|\bpsf\b", v):
        return "sqft"
    if "year" in v or "annu" in v:
        return "year"
    return ""


def rent_and_basis(listing):
    """(rent or None, basis '' | 'month' | 'sqft' | 'year') for a lease row.

    Reads lease_rate (the list price kept by the generator's normalize step)
    or list_price when the row has not been normalized yet.
    """
    rent = _num(listing.get("idx_lease_price"))
    if rent is None:
        rent = _num(listing.get("lease_rate"))
    if rent is None:
        rent = _num(listing.get("list_price"))
    if rent is None:
        return None, ""
    basis = _basis_from_lease_type(listing.get("idx_lease_type"))
    if not basis:
        periods = stated_periods(listing.get("public_remarks") or "", rent)
        if len(periods) == 1:
            basis = next(iter(periods))
    return rent, basis


def money(v):
    v = round(float(v), 2)
    return f"${v:,.2f}" if v != int(v) else f"${int(v):,}"


def rent_label(rent, basis):
    if not rent:
        return "Contact for rent"
    suffix = {"month": "/month", "sqft": "/sq ft", "year": "/year"}.get(basis or "")
    return money(rent) + suffix if suffix else money(rent) + " (lease)"


def apply(listings):
    """Mark lease rows in place; return the build heartbeat counts.

    A lease row gets is_lease=True, lease_rate (the rent), lease_source,
    rent, rent_basis, and list_price=None (so no mortgage, budget, all-in or
    closing-cost block can use a rent as a purchase price).
    """
    counts = {"lease": 0, "transaction_type": 0, "floor": 0, "remarks": 0,
              "month": 0, "sqft": 0, "year": 0, "not_stated": 0, "no_rent": 0,
              "lease_type_values": {}}
    for lst in listings:
        if lst.get("is_lease") and lst.get("lease_source"):
            pass  # already applied (idempotent)
        else:
            is_lease, source = detect_lease(lst)
            if not is_lease:
                continue
            lst["lease_rate"] = lst.get("list_price") if lst.get("list_price") is not None else lst.get("lease_rate")
            lst["list_price"] = None
            lst["is_lease"] = True
            lst["lease_source"] = source
        rent, basis = rent_and_basis(lst)
        lst["rent"] = rent
        lst["rent_basis"] = basis
        counts["lease"] += 1
        counts[lst["lease_source"]] += 1
        if rent is None:
            counts["no_rent"] += 1
        else:
            counts[basis or "not_stated"] += 1
        lt = str(lst.get("idx_lease_type") or "").strip()
        if lt:
            counts["lease_type_values"][lt] = counts["lease_type_values"].get(lt, 0) + 1
    return counts


def heartbeat(counts):
    """One line for the build log; says why a zero is a zero."""
    c = counts
    if not c["lease"]:
        return ("[GEN] lease-detect: 0 lease listings (no TransactionType=Lease row and no "
                "fallback match in this feed)")
    lt = ", ".join(f"{k}={v}" for k, v in sorted(c["lease_type_values"].items())) or "none seen yet"
    return (f"[GEN] lease-detect: {c['lease']} lease listing(s): {c['transaction_type']} by "
            f"TransactionType, fallback {c['floor'] + c['remarks']} ({c['floor']} price floor, "
            f"{c['remarks']} remarks state the monthly amount); rent shown: {c['month']} /month, "
            f"{c['sqft']} /sq ft, {c['year']} /year, {c['not_stated']} basis not stated "
            f"\"(lease)\", {c['no_rent']} \"Contact for rent\"; Leasetype values: {lt}")


# ── Availability status: one vocabulary on cards, map pins and property pages ──
# The same three keys and labels as js/listings-index.js (lrStatusKey). Read
# from the Status the generator already carries:
#   available   = "Active" (and anything unrecognised, as before)
#   conditional = "Cond Pending - Under Contract" (NLAR UC) and
#                 "Conditional - SST" (STCOS)
#   pending     = "Firm Sale - Pending" (from the deal record) and NLAR STFRM,
#                 long name "Conditional Pending" (firm: conditions removed,
#                 not closed)
# The page carries the key as data-status and the plain label; the badge
# styling and any explanation sentence are the redesign session's.
STATUS_LABELS = {"available": "Available", "conditional": "Conditional", "pending": "Pending"}
_PENDINGISH_RE = re.compile(r"pending|under contract|conditional|stfrm|stcos", re.IGNORECASE)


def status_key(status):
    s = str(status or "").strip()
    if not s or s == "Active":
        return "available"
    if (re.search(r"firm", s, re.IGNORECASE) and re.search(r"pending", s, re.IGNORECASE)) \
            or s.lower() in ("conditional pending", "stfrm"):
        return "pending"
    if _PENDINGISH_RE.search(s):
        return "conditional"
    return "available"


def status_label(status):
    return STATUS_LABELS[status_key(status)]


def status_line_html(listing, tag="p", extra_class=""):
    """The page's one availability label: <p class="lst-status"
    data-status="..."> with the plain label (no styling, no explanation
    sentence). Gander renders it as its banner chip (tag="span" plus the chip
    classes), so a page never carries two availability labels."""
    key = status_key(listing.get("status"))
    lease = ' data-lease="1"' if listing.get("is_lease") else ""
    cls = "lst-status" + (" " + extra_class if extra_class else "")
    return (f'<{tag} class="{cls}" data-status="{key}"{lease}>'
            f'{html.escape(STATUS_LABELS[key])}</{tag}>')


_LEASE_SENTENCE_RE = re.compile(r"\b(lease|leasing|leased|rent|rental|tenant|tenants)\b|per month|/month|"
                                r"\bmonthly\b|per sq\.?\s?ft|/sq\.?\s?ft|per square f", re.IGNORECASE)


def lease_terms_sentences(remarks, limit=3):
    """The remarks' own sentences about the lease (verbatim, at most `limit`)."""
    if not remarks:
        return []
    parts = re.split(r"(?<=[.!?])\s+", " ".join(str(remarks).split()))
    return [p.strip() for p in parts if _LEASE_SENTENCE_RE.search(p)][:limit]


def rental_details_html(listing):
    """Rental details section for a lease page: the rent and its basis exactly
    as the listing states them, the lease type when the feed has one, and the
    listing's own sentences about the lease. Empty for a sale row."""
    if not listing.get("is_lease"):
        return ""
    rent, basis = listing.get("rent"), listing.get("rent_basis") or ""
    rows = [("Rent", rent_label(rent, basis))]
    rows.append(("Rent is", {"month": "Per month", "sqft": "Per square foot",
                             "year": "Per year"}.get(basis, "Not stated in the listing")
                 if rent else "Not stated in the listing"))
    lt = str(listing.get("idx_lease_type") or "").strip()
    if lt:
        rows.append(("Lease type", lt))
    rows.append(("Availability", status_label(listing.get("status"))))
    body = "".join(f'<div class="lst-row"><span>{html.escape(k)}</span><span>{html.escape(v)}</span></div>'
                   for k, v in rows)
    terms = lease_terms_sentences(listing.get("public_remarks") or "")
    quote = ""
    if terms:
        quote = ('<p class="lst-rental-terms">From the listing: '
                 + html.escape(" ".join(terms)) + '</p>')
    return ('<section class="lst-section lst-rental" data-lease="1"><h2>Rental details</h2>'
            f'<div class="lst-details-grid">{body}</div>{quote}'
            '<p class="lst-rental-note">This property is offered for lease, not for sale.</p></section>')
