"""Anomaly detection: duplicates, first-time vendors, spend spikes."""

from bookkeeper.anomaly import detect_anomalies
from bookkeeper.models import Transaction


def _t(txn_id, date, amount, vendor):
    return Transaction(
        id=txn_id,
        txn_date=date,
        amount=amount,
        description="",
        vendor_name=vendor,
        current_account_id=None,
        current_account_name=None,
        source="imported",
    )


def test_duplicate_detected_within_3_days():
    txns = [
        _t("a", "2026-05-20", 100.0, "Comcast"),
        _t("b", "2026-05-21", 100.0, "Comcast"),
    ]
    flags = detect_anomalies(txns)
    dup_flags = [f for f in flags if f.flag_type == "duplicate"]
    assert len(dup_flags) == 1
    assert dup_flags[0].transaction_id == "b"


def test_duplicate_not_flagged_beyond_3_days():
    txns = [
        _t("a", "2026-05-20", 100.0, "Comcast"),
        _t("b", "2026-05-28", 100.0, "Comcast"),  # 8 days apart
    ]
    flags = detect_anomalies(txns)
    assert not [f for f in flags if f.flag_type == "duplicate"]


def test_duplicate_not_flagged_different_vendors():
    txns = [
        _t("a", "2026-05-20", 100.0, "Comcast"),
        _t("b", "2026-05-21", 100.0, "Verizon"),
    ]
    flags = detect_anomalies(txns)
    assert not [f for f in flags if f.flag_type == "duplicate"]


def test_first_time_vendor_over_threshold_flagged():
    txns = [
        _t("a", "2026-05-20", 750.0, "Brand New Vendor"),
    ]
    flags = detect_anomalies(txns)
    new_flags = [f for f in flags if f.flag_type == "first_time_vendor"]
    assert len(new_flags) == 1


def test_first_time_vendor_below_threshold_ignored():
    txns = [
        _t("a", "2026-05-20", 50.0, "Brand New Vendor"),
    ]
    flags = detect_anomalies(txns)
    assert not [f for f in flags if f.flag_type == "first_time_vendor"]


def test_first_time_vendor_not_flagged_when_seen_twice():
    txns = [
        _t("a", "2026-05-20", 600.0, "Repeat Vendor"),
        _t("b", "2026-05-21", 700.0, "Repeat Vendor"),
    ]
    flags = detect_anomalies(txns)
    assert not [f for f in flags if f.flag_type == "first_time_vendor"]


def test_spike_flagged():
    txns = [
        _t("a", "2026-05-01", 10.0, "Coffee"),
        _t("b", "2026-05-02", 10.0, "Coffee"),
        _t("c", "2026-05-03", 100.0, "Coffee"),  # >2x average
    ]
    flags = detect_anomalies(txns)
    spike_flags = [f for f in flags if f.flag_type == "spike"]
    assert any(f.transaction_id == "c" for f in spike_flags)


def test_spike_not_flagged_with_single_charge():
    txns = [_t("a", "2026-05-01", 999.0, "Solo Vendor")]
    flags = detect_anomalies(txns)
    assert not [f for f in flags if f.flag_type == "spike"]


def test_empty_input():
    flags = detect_anomalies([])
    assert flags == []


def test_invalid_date_skipped_gracefully():
    txns = [
        _t("a", "not-a-date", 100.0, "X"),
        _t("b", "2026-05-20", 100.0, "X"),
    ]
    # Should not crash; dup check skips the unparseable row
    flags = detect_anomalies(txns)
    assert isinstance(flags, list)
