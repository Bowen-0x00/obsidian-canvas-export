"""Consumer-boundary checks for TeX geometry and safe panel configuration."""
from __future__ import annotations

import copy
import math
import unittest

from canvas_export.errors import ExportError
from canvas_export.latex import graphics_tex, panel_position, tex_escape


def anchor(logical_id="heading", *, x=120, y=95, **extra):
    return {
        "id": "native-element-id",
        "x": x,
        "y": y,
        "angle": 0,
        "customData": {"agentDiagram": {"logicalId": logical_id}},
        **extra,
    }


def export_metadata():
    return {
        "bounds": {"x": 100, "y": 80, "width": 200, "height": 100},
        "width": 240,
        "height": 140,
        "padding": 20,
    }


def panel(**changes):
    return {
        "anchor": "heading",
        "label": "fig:example_panel-a",
        "title": "A panel heading",
        "dx": 5,
        "dy": 10,
        **changes,
    }


def figure(**changes):
    return {
        "macro": "ExampleGraphic",
        "panel_scope": "example",
        "panels": [panel()],
        **changes,
    }


def state():
    return {"elements": [anchor()], "pdf": export_metadata()}


class PanelPositionTests(unittest.TestCase):
    def assertPosition(self, actual, expected):
        self.assertAlmostEqual(actual[0], expected[0])
        self.assertAlmostEqual(actual[1], expected[1])

    def test_positions_use_padded_width_and_bottom_origin_for_both_axes(self):
        # The non-square image deliberately catches accidental division by height.
        self.assertPosition(
            panel_position(panel(), [anchor()], export_metadata()),
            (45 / 240 * 100, 95 / 240 * 100),
        )

    def test_translating_source_and_its_bounds_preserves_heading_alignment(self):
        original = panel_position(panel(), [anchor()], export_metadata())
        shifted = anchor(x=120 - 800, y=95 + 250)
        exported = export_metadata()
        exported["bounds"]["x"] -= 800
        exported["bounds"]["y"] += 250
        self.assertPosition(panel_position(panel(), [shifted], exported), original)

    def test_uniform_source_rescale_preserves_heading_alignment(self):
        original = panel_position(panel(), [anchor()], export_metadata())
        factor = 2.5
        exported = export_metadata()
        exported["bounds"] = {key: value * factor for key, value in exported["bounds"].items()}
        for key in ("width", "height", "padding"):
            exported[key] *= factor
        self.assertPosition(
            panel_position(
                panel(dx=5 * factor, dy=10 * factor),
                [anchor(x=120 * factor, y=95 * factor)],
                exported,
            ),
            original,
        )

    def test_new_negative_origin_uses_current_export_bounds(self):
        exported = export_metadata()
        exported.update(
            bounds={"x": -80, "y": -40, "width": 380, "height": 220},
            width=420,
            height=260,
        )
        self.assertPosition(
            panel_position(panel(), [anchor()], exported),
            (225 / 420 * 100, 95 / 420 * 100),
        )

    def test_duplicate_logical_ids_are_not_disambiguated_by_native_id(self):
        with self.assertRaisesRegex(ExportError, "matched 2 undeleted"):
            panel_position(panel(), [anchor(), anchor(id="different-native-id")], export_metadata())

    def test_deleted_duplicate_does_not_change_position(self):
        elements = [anchor(), anchor(isDeleted=True, x=-999, y=-999)]
        self.assertPosition(
            panel_position(panel(), elements, export_metadata()),
            panel_position(panel(), [anchor()], export_metadata()),
        )

    def test_missing_or_deleted_anchor_has_actionable_error(self):
        for elements in ([], [anchor(isDeleted=True)]):
            with self.subTest(elements=elements):
                with self.assertRaisesRegex(ExportError, "heading.*matched 0.*logicalId"):
                    panel_position(panel(), elements, export_metadata())

    def test_native_element_id_is_not_an_anchor_alias(self):
        with self.assertRaisesRegex(ExportError, "native element IDs are not anchor aliases"):
            panel_position(panel(anchor="native-element-id"), [anchor()], export_metadata())

    def test_rotated_anchor_is_rejected_instead_of_silently_misplacing_title(self):
        for angle in (0.1, -math.pi, 1e-12):
            with self.subTest(angle=angle):
                with self.assertRaisesRegex(ExportError, "rotated.*unrotated"):
                    panel_position(panel(), [anchor(angle=angle)], export_metadata())

    def test_offsets_must_be_finite_real_numbers_not_booleans(self):
        for key in ("dx", "dy"):
            for value in (True, False, "2", None, math.nan, math.inf, -math.inf):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ExportError, "finite real number"):
                        panel_position(panel(**{key: value}), [anchor()], export_metadata())

    def test_bad_export_geometry_is_rejected(self):
        for key, value in (("width", 0), ("width", math.inf), ("padding", -1), ("padding", True)):
            exported = export_metadata()
            exported[key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(ExportError):
                    panel_position(panel(), [anchor()], exported)

    def test_source_elements_and_export_metadata_are_not_modified(self):
        elements, exported, configured = [anchor()], export_metadata(), panel()
        before = copy.deepcopy((elements, exported, configured))
        panel_position(configured, elements, exported)
        self.assertEqual((elements, exported, configured), before)


class GraphicsTexTests(unittest.TestCase):
    def test_special_title_characters_are_escaped_once_as_literal_text(self):
        title = r"A&B 50% #1_x $v$ {ok} \path ~ ^ /"
        escaped = (
            r"A\&B 50\% \#1\_x \$v\$ \{ok\} "
            r"\textbackslash{}path \textasciitilde{} \textasciicircum{} /"
        )
        self.assertEqual(tex_escape(title), escaped)



    def test_reused_scope_cannot_produce_duplicate_hyperlink_ids(self):
        figures = {
            "first": figure(macro="FirstGraphic"),
            "second": figure(macro="SecondGraphic", panels=[panel(label="fig:second")]),
        }
        with self.assertRaisesRegex(ExportError, "duplicate panel scope.*hyperlink"):
            graphics_tex(figures, {"first": state(), "second": state()})

    def test_duplicate_macros_and_labels_fail_at_consumer_boundary(self):
        with self.assertRaisesRegex(ExportError, "duplicate.*TeX macro"):
            graphics_tex({"a": figure(panels=[]), "b": figure(panels=[])}, {})
        figures = {
            "a": figure(),
            "b": figure(macro="OtherGraphic", panel_scope="other"),
        }
        with self.assertRaisesRegex(ExportError, "duplicate TeX panel label"):
            graphics_tex(figures, {"a": state(), "b": state()})

    def test_macro_label_and_scope_syntax_is_checked(self):
        invalid_figures = (
            figure(macro=r"Bad\command"),
            figure(macro="Figure2"),
            figure(panel_scope="example-1"),
            figure(panels=[panel(label=r"fig:x}\input{bad")]),
        )
        for configured in invalid_figures:
            with self.subTest(configured=configured):
                with self.assertRaises(ExportError):
                    graphics_tex({"example": configured}, {"example": state()})


    def test_generation_does_not_modify_configuration_or_source_states(self):
        figures, states = {"example": figure()}, {"example": state()}
        before = copy.deepcopy((figures, states))
        graphics_tex(figures, states)
        self.assertEqual((figures, states), before)


if __name__ == "__main__":
    unittest.main()
