from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from config.samples import make_invoice, sample_config
from matching.models import CarrierAlias, Carrier, FlagType, MatchResult
from matching.names import charge_key, names_match
from matching.services import evaluate, override, save_match
from tms.factory import get_tms_client
from tms.simulated import SimulatedTms, close_ids
from tms.turvo_format import parse_shipment


class NameTests(SimpleTestCase):
    def test_legal_suffixes_and_dba_are_handled(self):
        self.assertTrue(names_match(["OTR Capital, LLC d/b/a OTR Solutions"], "OTR Solutions")[0])
        self.assertTrue(names_match(["Northwind Freight Lines LLC"], "Northwind Freight Lines")[0])
        self.assertFalse(names_match(["Northwind Freight Lines"], "Pacific Coast Logistics")[0])

    def test_charge_keys(self):
        self.assertEqual(charge_key("Fuel Surcharge"), "fuel")
        self.assertEqual(charge_key("FSC"), "fuel")
        self.assertEqual(charge_key("Freight - flat"), "freight")
        self.assertEqual(charge_key("Base line haul / transportation"), "freight")
        self.assertEqual(charge_key(None), "freight")
        self.assertEqual(charge_key("Lumper fee"), "fee lumper")

    def test_close_ids(self):
        known = ["31000-00014", "31999-00001"]
        self.assertEqual(close_ids("31000-00004", known), ["31000-00014"])
        self.assertEqual(close_ids("31433-32559", ["31433-32595"]), ["31433-32595"])  # swapped neighbors
        self.assertEqual(close_ids("31433-32959", ["31433-32595"]), [])  # too different to guess
        self.assertEqual(close_ids("31000-00004", ["31000-00014"][:0]), [])


class TmsTests(SimpleTestCase):
    def test_fixture_parses_like_the_turvo_response(self):
        client = SimulatedTms([sample_config().tms_fixture_dirs[0]])
        shipment = client.find_shipment("31000-00001")
        order = shipment.carrier_orders[0]
        self.assertEqual(order.carrier_name, "Northwind Freight Lines")
        self.assertEqual(order.total, Decimal("1587.5"))
        self.assertEqual(order.currency, "USD")
        self.assertEqual(shipment.container_number, "TEST1234567")
        self.assertEqual(len(order.lines), 3)
        self.assertIsNone(client.find_shipment("31000-99999"))
        self.assertIn("4 shipment fixture", client.check())

    def test_parse_ignores_deleted_lines(self):
        shipment = parse_shipment({"details": {"customId": "31000-00009", "carrierOrder": [{"carrier": {"name": "X"}, "costs": {"lineItem": [
            {"code": {"value": "Freight"}, "amount": 10}, {"code": {"value": "Old"}, "amount": 5, "deleted": True}]}}]}})
        self.assertEqual(len(shipment.carrier_orders[0].lines), 1)
        self.assertEqual(shipment.carrier_orders[0].total, Decimal("10"))


class EvaluateTests(TestCase):
    def setUp(self):
        self.config = sample_config()
        self.tms = get_tms_client(self.config)

    def run_eval(self, **values):
        invoice = make_invoice(**{k: v for k, v in values.items() if k != "lines"}, lines=values.get("lines"))
        return invoice, evaluate(invoice, self.tms, self.config)

    def codes(self, result):
        return {flag.code for flag in result.flags}

    def test_exact_match_is_ready(self):
        _, result = self.run_eval()
        self.assertEqual(result.flags, [])
        self.assertEqual(result.outcome, "ready")

    def test_amount_over_tolerance(self):
        _, result = self.run_eval(total_amount=Decimal("1700.00"), lines=[("Linehaul", "1362.50"), ("Fuel Surcharge", "187.50"), ("Detention", "150.00")])
        self.assertIn("amount_over_tolerance", self.codes(result))
        self.assertEqual(result.outcome, "needs_review")

    def test_small_difference_within_tolerance_passes(self):
        _, result = self.run_eval(total_amount=Decimal("1590.00"), lines=[("Linehaul", "1252.50"), ("Fuel Surcharge", "187.50"), ("Detention", "150.00")])
        self.assertEqual(result.flags, [])

    def test_unknown_accessorial(self):
        _, result = self.run_eval(total_amount=Decimal("1637.50"), lines=[*[("Linehaul", "1250.00"), ("Fuel Surcharge", "187.50"), ("Detention", "150.00")], ("Lumper fee", "50.00")])
        self.assertIn("unknown_accessorial", self.codes(result))

    def test_currency_mismatch_and_missing_currency(self):
        _, mismatch = self.run_eval(currency="CAD")
        self.assertIn("currency_mismatch", self.codes(mismatch))
        _, missing = self.run_eval(currency="")
        self.assertEqual(missing.flags, [])
        self.assertTrue(any("assumed" in note for note in missing.notes))

    def test_carrier_mismatch_and_factoring_company(self):
        _, wrong = self.run_eval(carrier_name="Pacific Coast Logistics")
        self.assertIn("carrier_mismatch", self.codes(wrong))
        _, factored = self.run_eval(carrier_name="Some Trucking Co", factoring_company="Northwind Freight Lines LLC")
        self.assertNotIn("carrier_mismatch", self.codes(factored))

    def test_carrier_alias_table_is_used(self):
        carrier = Carrier.objects.create(name="Northwind Freight Lines")
        CarrierAlias.objects.create(carrier=carrier, alias="nwfl")
        _, result = self.run_eval(carrier_name="NWFL")
        self.assertNotIn("carrier_mismatch", self.codes(result))

    def test_shipment_not_found_offers_suggestion(self):
        invoice, result = self.run_eval(shipment_id="31000-00004", carrier_name="Sunrise Cargo Movers", total_amount=Decimal("450.00"), lines=[("Drayage", "450.00")])
        self.assertIn("no_matching_shipment", self.codes(result))
        self.assertEqual(result.suggestions, ["31000-00014"])
        confirmed = evaluate(invoice, self.tms, self.config, shipment_id_override="31000-00014")
        self.assertEqual(confirmed.outcome, "ready")
        self.assertTrue(confirmed.shipment_confirmed)

    def test_suggestion_from_other_references(self):
        _, result = self.run_eval(shipment_id="", other_references=[{"label": "BOL", "value": "31000-00001"}])
        self.assertIn("missing_required_field", self.codes(result))
        self.assertEqual(result.suggestions, ["31000-00001"])

    def test_missing_required_field_and_low_confidence(self):
        _, missing = self.run_eval(invoice_number="")
        self.assertIn("missing_required_field", self.codes(missing))
        invoice = make_invoice(confidence=0.5)
        self.assertIn("low_confidence", self.codes(evaluate(invoice, self.tms, self.config)))

    def test_math_mismatch(self):
        _, result = self.run_eval(lines=[("Linehaul", "1250.00"), ("Fuel Surcharge", "187.50")])
        self.assertIn("math_mismatch", self.codes(result))

    def test_container_mismatch_flags_wrong_shipment(self):
        _, result = self.run_eval(other_references=[{"label": "Container Number", "value": "ZZZZ9999999"}])
        self.assertIn("no_matching_shipment", self.codes(result))

    def test_duplicate_invoice_number(self):
        make_invoice(invoice_number="DUP-1")
        second = make_invoice(invoice_number="DUP-1")
        self.assertIn("duplicate_invoice", {f.code for f in evaluate(second, self.tms, self.config).flags})

    def test_same_shipment_and_amount_is_a_possible_duplicate(self):
        first = make_invoice(invoice_number="A-1")
        save_match(first, evaluate(first, self.tms, self.config))
        second = make_invoice(invoice_number="B-2")
        result = evaluate(second, self.tms, self.config)
        self.assertIn("duplicate_invoice", {f.code for f in result.flags})

    def test_save_match_stores_flags_snapshot_and_override(self):
        invoice, result = self.run_eval(currency="CAD")
        match = save_match(invoice, result)
        self.assertEqual(match.outcome, "needs_review")
        self.assertEqual(match.flags.get().flag_type.code, "currency_mismatch")
        self.assertEqual(match.shipment.shipment_id, "31000-00001")
        self.assertTrue(match.comparison)
        self.assertFalse(match.can_process)
        override(match, "Carrier confirmed by phone")
        match.refresh_from_db()
        self.assertTrue(match.can_process)
        self.assertEqual(match.override_note, "Carrier confirmed by phone")
        self.assertEqual(FlagType.objects.count(), 10)


class FakeTty:
    def isatty(self):
        return True


@override_settings(APP=sample_config())
class MatchCommandTests(TestCase):
    def run_match(self, answers=()):
        out = StringIO()
        with mock.patch("config.ui.sys.stdin", FakeTty()), mock.patch("builtins.input", side_effect=list(answers)):
            call_command("match", stdout=out)
        return out.getvalue()

    def test_match_reports_flags_and_saves_results(self):
        make_invoice()
        make_invoice(currency="CAD")
        output = self.run_match()
        self.assertIn("1 ready, 1 need review", output)
        self.assertIn("Currency mismatch", output)
        self.assertEqual(MatchResult.objects.count(), 2)

    def test_user_can_accept_a_suggested_shipment(self):
        make_invoice(shipment_id="31000-00004", carrier_name="Sunrise Cargo Movers", total_amount=Decimal("450.00"), lines=[("Drayage", "450.00")])
        output = self.run_match(["y"])
        self.assertIn("was chosen by a person", output)
        match = MatchResult.objects.get()
        self.assertEqual(match.outcome, "ready")
        self.assertTrue(match.shipment_confirmed_by_user)

    def test_declining_the_suggestion_leaves_it_for_review(self):
        make_invoice(shipment_id="31000-00004", carrier_name="Sunrise Cargo Movers", total_amount=Decimal("450.00"), lines=[("Drayage", "450.00")])
        self.run_match(["n"])
        self.assertEqual(MatchResult.objects.get().outcome, "needs_review")
