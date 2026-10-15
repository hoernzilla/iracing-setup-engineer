"""Ende-zu-Ende-Tests gegen synthetische IBT-Dateien mit bekannter Wahrheit.

Start:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from setup_engineer.analysis import analyze_file  # noqa: E402
from setup_engineer.compare import ab_compare  # noqa: E402
from setup_engineer.ibt import IbtError, IbtFile  # noqa: E402
from setup_engineer.report import session_json, session_markdown  # noqa: E402
from setup_engineer.setup import CarSetup, diff, parse_value  # noqa: E402
from setup_engineer.synth import SynthConfig, make_file  # noqa: E402


class SynthCase(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.file = make_file(cls.dir / "base.ibt", SynthConfig(seed=3))
        cls.analysis = analyze_file(cls.file)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()


class TestReader(SynthCase):
    def test_header_and_channels(self) -> None:
        ibt = IbtFile.open(self.file)
        self.assertEqual(ibt.tick_rate, 60)
        self.assertTrue(ibt.has("Speed"))
        self.assertEqual(ibt.channel("LFshockVel").shape[1], 6)
        self.assertTrue(ibt.is_hi_res("LFshockVel"))
        self.assertEqual(ibt.channel_hi_res("LFshockVel").size, ibt.record_count * 6)
        self.assertEqual(ibt.get("LFshockVel").shape, (ibt.record_count,))

    def test_session_info_with_tricky_name(self) -> None:
        ibt = IbtFile.open(self.file)
        self.assertEqual(ibt.car_name, "Synth GT3")
        self.assertIn("Synth Ring", ibt.track_name)
        self.assertAlmostEqual(ibt.track_length_m or 0, 2740, delta=20)

    def test_rejects_garbage(self) -> None:
        bad = self.dir / "bad.ibt"
        bad.write_bytes(b"\x00" * 500)
        with self.assertRaises(IbtError):
            IbtFile.open(bad)

    def test_truncated_file_still_readable(self) -> None:
        cut = self.dir / "cut.ibt"
        raw = self.file.read_bytes()
        cut.write_bytes(raw[: len(raw) - 50_000])
        ibt = IbtFile.open(cut)
        self.assertLess(ibt.record_count, IbtFile.open(self.file).record_count)
        self.assertTrue(any("abgebrochene" in w for w in ibt.warnings))


class TestSetup(SynthCase):
    def test_parse_value(self) -> None:
        v = parse_value("Chassis.LeftFront.SpringRate", "180 N/mm")
        self.assertEqual((v.value, v.unit), (180.0, "N/mm"))
        self.assertIsNone(parse_value("x", "Soft").value)
        self.assertEqual(parse_value("x", "-3,5 deg").value, -3.5)

    def test_setup_from_file(self) -> None:
        s = self.analysis.setup
        self.assertEqual(s["Chassis.LeftFront.SpringRate"].value, 180.0)
        self.assertTrue(s["Chassis.LeftFront.CornerWeight"].likely_read_only)

    def test_diff_ignores_read_only(self) -> None:
        a = CarSetup.from_session_info({"CarSetup": {"C": {"LF": {"SpringRate": "180 N/mm", "CornerWeight": "3000 N"}}}})
        b = CarSetup.from_session_info({"CarSetup": {"C": {"LF": {"SpringRate": "200 N/mm", "CornerWeight": "3100 N"}}}})
        changes = diff(a, b)
        self.assertEqual([c.path for c in changes], ["C.LF.SpringRate"])
        self.assertEqual(changes[0].delta, 20.0)


class TestSegmentation(SynthCase):
    def test_laps(self) -> None:
        laps = self.analysis.laps
        self.assertEqual(len(laps.laps), 10)
        self.assertEqual(len(laps.valid), 8)
        reasons = {r for lap in laps.laps for r in lap.reasons}
        self.assertIn("unvollständig", reasons)
        self.assertTrue(any("Boxengasse" in r for r in reasons))

    def test_corners(self) -> None:
        cs = self.analysis.corners
        self.assertEqual([c.direction for c in cs], ["rechts", "links", "rechts", "links"])
        for c in cs:
            self.assertLessEqual(c.brake_start, c.start)
            self.assertTrue(c.start <= c.apex <= c.end)
        radii = [c.min_radius_m for c in cs]
        for got, want in zip(radii, [60, 120, 80, 200]):
            self.assertAlmostEqual(got, want, delta=want * 0.15)


class TestDiagnosis(SynthCase):
    def verdicts(self, corner: str) -> set[str]:
        return {b.verdict for b in self.analysis.balance if b.corner == corner}

    def test_car_understeer_detected(self) -> None:
        self.assertIn("Auto", self.verdicts("T2"))

    def test_driver_understeer_detected(self) -> None:
        self.assertIn("Fahrer", self.verdicts("T3"))
        self.assertNotIn("Auto", self.verdicts("T3"))

    def test_no_false_alarms(self) -> None:
        self.assertEqual(self.verdicts("T1"), {"neutral"})
        self.assertEqual(self.verdicts("T4"), {"neutral"})

    def test_platform(self) -> None:
        p = self.analysis.platform
        assert p is not None
        self.assertTrue(p.ride_height)
        self.assertEqual({d.wheel for d in p.dampers}, {"LF", "RF", "LR", "RR"})
        self.assertEqual(p.dampers[0].source, "LFshockVel")
        front = {r.wheel: r for r in p.bump_stops}
        self.assertGreater(front["LF"].contact_share, 0)
        self.assertEqual(front["LR"].contact_share, 0)

    def test_reports_render(self) -> None:
        md = session_markdown(self.analysis)
        self.assertIn("## Balance", md)
        import json

        data = json.loads(session_json(self.analysis))
        self.assertEqual(data["car"], "Synth GT3")


class TestAB(unittest.TestCase):
    def test_detects_real_effect_and_not_noise(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            a = analyze_file(make_file(d / "a.ibt", SynthConfig(seed=10, laps=10)))
            same = analyze_file(make_file(d / "s.ibt", SynthConfig(seed=11, laps=10, spring_front="200 N/mm")))
            fast = analyze_file(make_file(d / "f.ibt", SynthConfig(seed=12, laps=10, lat_g=1.85)))
            r_same, r_fast = ab_compare(a, same), ab_compare(a, fast)
        self.assertEqual(r_same.verdict, "nicht entscheidbar")
        self.assertEqual([c.path for c in r_same.setup_changes][:1], ["Chassis.LeftFront.SpringRate"])
        self.assertEqual(r_fast.verdict, "B ist schneller")
        self.assertLess(r_fast.effect_s, -0.2)
        self.assertTrue(np.isfinite(r_fast.p_value))


REAL_GTP = Path(__file__).resolve().parents[1] / "data" / "gtp1.ibt"


@unittest.skipUnless(REAL_GTP.exists(), "echte GTP-Datei (data/gtp1.ibt) nicht vorhanden")
class TestRealGTP(unittest.TestCase):
    """Regressionstest mit echter Porsche-963-Session (Watkins Glen, 15.10.2026)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.a = analyze_file(REAL_GTP)

    def test_basics(self) -> None:
        self.assertEqual(self.a.ibt.car_name, "Porsche 963 GTP")
        self.assertEqual(len(self.a.laps.valid), 8)
        self.assertAlmostEqual(self.a.laps.best.time_s, 91.993, places=2)
        self.assertGreaterEqual(len(self.a.corners), 11)

    def test_travel_matches_setup_display(self) -> None:
        rows = {t.channel: t for t in self.a.platform.travel}
        self.assertTrue(rows["LRshockDefl"].matched_static)
        self.assertTrue(rows["HFshockDefl"].matched_static)

    def test_high_speed_understeer(self) -> None:
        sb = self.a.speed_balance
        self.assertIsNotNone(sb.finding)
        self.assertGreater(sb.high - sb.low, 0.10)

    def test_pit_only_tire_channels(self) -> None:
        self.assertIn("LFtempCM", self.a.tires.pit_only)
        self.assertNotIn("LFtempL", self.a.tires.pit_only)


REAL_GTP2 = REAL_GTP.with_name("gtp2.ibt")


@unittest.skipUnless(REAL_GTP.exists() and REAL_GTP2.exists(), "echte GTP-Dateien nicht vorhanden")
class TestRealGTPRepeat(unittest.TestCase):
    """Zwei Runs mit identischem Setup. Früher kippte das Modell, weil die
    Streckentemperatur pro Run konstant war (Ergebnis: angeblich 2,7 s schneller)."""

    def test_confounded_temperature_not_used(self) -> None:
        r = ab_compare(analyze_file(REAL_GTP), analyze_file(REAL_GTP2))
        self.assertNotIn("Streckentemperatur", r.covariates)
        self.assertGreater(r.effect_s, 0)  # B war im Schnitt langsamer
        self.assertLess(abs(r.effect_s - (r.mean_b - r.mean_a)), 0.3)
        # Garage-Setup identisch, aber Front-Stabi im Auto von 1 auf 3 verstellt
        self.assertEqual(
            [(c.path, c.before, c.after) for c in r.setup_changes],
            [("Im Auto: Stabilisator vorne", "1", "3")],
        )
        self.assertTrue(any(c.name == "Luftdichte" and c.warn for c in r.conditions))
        self.assertAlmostEqual(sum(s.delta for s in r.sections), r.mean_b - r.mean_a, delta=0.4)


if __name__ == "__main__":
    unittest.main()
