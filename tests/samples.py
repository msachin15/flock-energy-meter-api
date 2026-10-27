"""Small synthetic portal records. These are not the bulk export."""


def meter_record(**overrides):
    """One synthetic export meter. Pass overrides to drop geo or blank a hierarchy code."""

    record = {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Installed",
        "installType": "Whole Current",
        "build": "legacy",
        "dtCode": "DT-001",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "Circle 1", "code": "C-01"},
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "Feeder 1", "code": "F-001"},
            "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
        },
        "geo": {"lat": 26.9, "lng": 75.8},
    }
    record.update(overrides)
    return record


def transformer_record(**overrides):
    """One synthetic transformer. Pass overrides to break capacity or the code."""

    record = {
        "code": "DT-001",
        "name": "Malviya Nagar DT 1",
        "feederCode": "F-001",
        "capacityKva": 100,
    }
    record.update(overrides)
    return record
