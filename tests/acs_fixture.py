"""Fake ACS labels and rows in the Census API's own format, for offline tests."""

E = "Estimate!!"
INC = "Median household income in the past 12 months (in 2024 inflation-adjusted dollars)"
COST_BINS = ["Less than $50", "$50 to $99", "$100 to $149", "$150 to $199", "$200 to $249", "$250 or more"]
INCOME_BINS = ["Less than $5,000", "$5,000 to $9,999", "$10,000 to $14,999", "$15,000 to $19,999",
               "$20,000 to $24,999", "$25,000 to $34,999", "$35,000 to $49,999", "$50,000 to $74,999",
               "$75,000 to $99,999", "$100,000 to $149,999", "$150,000 or more"]
AGES = ["15 to 24", "25 to 34", "35 to 44", "45 to 54", "55 to 59", "60 to 64", "65 to 74", "75 to 84"]


def _table(code: str, labels: list[str]) -> dict:
    out = {}
    for i, lab in enumerate(labels, 1):
        out[f"{code}_{i:03d}E"] = E + lab
        out[f"{code}_{i:03d}M"] = "Margin of Error!!" + lab
    return out


def _cost(code: str, what: str) -> dict:
    return _table(code, ["Total:", "Total:!!Not charged, not used, or payment included in other fees",
                         f"Total:!!Charged for {what}:"] + [f"Total:!!Charged for {what}:!!{b}" for b in COST_BINS])


NH = "Total:!!Not Hispanic or Latino:!!"
LABELS = {
    "B19013": _table("B19013", [INC]),
    "B25119": _table("B25119", [f"{INC} --!!Total:", f"{INC} --!!Total:!!Owner occupied (dollars)",
                                f"{INC} --!!Total:!!Renter occupied (dollars)"]),
    "B25003": _table("B25003", ["Total:", "Total:!!Owner occupied", "Total:!!Renter occupied"]),
    "B25010": _table("B25010", ["Average household size --!!Total:", "Average household size --!!Total:!!Owner occupied",
                                "Average household size --!!Total:!!Renter occupied"]),
    "B25007": _table("B25007", ["Total:", "Total:!!Owner occupied:"]
                     + [f"Total:!!Owner occupied:!!Householder {a} years" for a in AGES]
                     + ["Total:!!Owner occupied:!!Householder 85 years and over", "Total:!!Renter occupied:"]
                     + [f"Total:!!Renter occupied:!!Householder {a} years" for a in AGES]
                     + ["Total:!!Renter occupied:!!Householder 85 years and over"]),
    "B03002": _table("B03002", ["Total:", "Total:!!Not Hispanic or Latino:", NH + "White alone",
                                NH + "Black or African American alone", NH + "American Indian and Alaska Native alone",
                                NH + "Asian alone", NH + "Native Hawaiian and Other Pacific Islander alone",
                                NH + "Some other race alone", NH + "Two or more races:",
                                NH + "Two or more races:!!Two races including Some other race",
                                NH + "Two or more races:!!Two races excluding Some other race, and three or more races",
                                "Total:!!Hispanic or Latino:"]),
    "B25118": _table("B25118", ["Total:", "Total:!!Owner occupied:"]
                     + [f"Total:!!Owner occupied:!!{b}" for b in INCOME_BINS] + ["Total:!!Renter occupied:"]
                     + [f"Total:!!Renter occupied:!!{b}" for b in INCOME_BINS]),
    "B25132": _cost("B25132", "electricity"),
    "B25133": _cost("B25133", "gas"),
    "B25134": _cost("B25134", "water and sewer"),
}


def row(tract: str = "000100", county: str = "055", households: int = 100, renters: int = 40) -> dict:
    """A tract where every estimate is 10 except the ones set below; MOEs are 5."""
    r = {"NAME": f"Census Tract {tract}", "state": "31", "county": county, "tract": tract}
    for tab in LABELS.values():
        for var in tab:
            r[var] = "5" if var.endswith("M") else "10"
    r.update({"B19013_001E": "60000", "B25119_002E": "80000", "B25119_003E": "35000",
              "B25003_001E": str(households), "B25003_002E": str(households - renters),
              "B25003_003E": str(renters), "B03002_001E": "250", "B03002_012E": "-666666666"})
    return r
