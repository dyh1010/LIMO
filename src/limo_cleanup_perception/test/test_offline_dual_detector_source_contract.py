"""Static fail-closed model-identity checks for offline inference."""

from pathlib import Path


SOURCE = (
    Path(__file__).parents[1]
    / 'limo_cleanup_perception/offline_dual_detector.py'
).read_text(encoding='utf-8')


def test_offline_detector_rejects_swapped_or_mislabeled_weights():
    assert 'require_single_class_model' in SOURCE
    assert "bottle_model.names, 'plastic_bottle'" in SOURCE
    assert "bin_model.names, 'trash_bin'" in SOURCE
    assert 'EXPECTED_MODEL_SHA256' in SOURCE
    assert 'model SHA-256 mismatch' in SOURCE


if __name__ == '__main__':
    test_offline_detector_rejects_swapped_or_mislabeled_weights()
    print('1 offline-detector source-contract check passed')
