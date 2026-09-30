"""
Every kind of step

Generated from a scene file. Every scene is a class; render one with
    manimgl <this file> <SceneName> -w
"""
from manimlib import *
from manim_verbose.scenefile.runtime import *


class Basics(DocScene):
    """Showing, moving and changing"""
    scene_id = "basics"
    caption_style = CaptionStyle(font_size=28)

    def construct(self):
        title = self.obj("title", Text("Every step", font_size=48).set_x(0).to_edge(UP, buff=0.25))
        eq = self.obj("eq", Tex("a^2 + b^2 = c^2", font_size=48, t2c={"c^2": YELLOW}))
        eq2 = self.obj("eq2", Tex("c^2 = a^2 + b^2", font_size=48).move_to([0, -1.5, 0]))
        ring = self.obj("ring", Circle(radius=1).set_color(BLUE).move_to([-4, 0, 0]))
        box = self.obj("box", Square(side_length=1.5).set_color(GREEN).set_fill(GREEN, opacity=0.5).move_to([4, 0, 0]))
        pair = self.obj("pair", VGroup(ring, box))
        dot = self.obj("dot", Dot([0, 2, 0], radius=0.08).set_color(RED))
        self.add(dot)

        with self.step("s_show", caption="Showing things"):
            self.play(Write(title), run_time=1.5)
        with self.step("s_show_many"):
            self.play(LaggedStart(ShowCreation(ring, run_time=1), ShowCreation(box, run_time=1), lag_ratio=0.5), run_time=2.25)
        with self.step("s_add"):
            self.add(eq)
        with self.step("s_highlight"):
            self.play(Indicate(eq["c^2"]), run_time=1)
        with self.step("s_recolor"):
            self.play(eq["a^2"].animate.set_color(RED), run_time=1)
        with self.step("s_move_by"):
            self.play(pair.animate.shift([0, -1, 0]), run_time=1)
        with self.step("s_move_to"):
            self.play(title.animate.move_to(place(title.copy(), edge="bottom_left")), run_time=1)
        with self.step("s_change", caption="Changing things"):
            ring_new = Circle(radius=0.6).set_color(ORANGE).move_to([-4, 0, 0])
            ring_new.move_to(ring)
            self.play(Transform(ring, ring_new), run_time=1)
        with self.step("s_transform"):
            self.play(TransformMatchingTex(eq, eq2), run_time=1.5)
        with self.step("s_wait"):
            self.wait(0.5)
        with self.step("s_remove"):
            self.remove(dot)
        with self.step("s_hide"):
            self.play(FadeOut(title, shift=0.5 * DOWN), run_time=1)
        with self.step("s_clear", caption=""):
            self.play(FadeOut(self.everything_on_screen()), run_time=1)


class PlaneView(DocScene):
    scene_id = "plane_view"
    caption_style = CaptionStyle(font_size=28)

    def construct(self):
        plane = self.obj("plane", NumberPlane(x_range=[-8, 8, 1], y_range=[-4, 4, 1]))
        v = self.obj("v", Arrow(plane.c2p(0, 0), plane.c2p(1, 2), buff=0).set_color(YELLOW))
        w = self.obj("w", Arrow(plane.c2p(0, 0), plane.c2p(2, -1), buff=0).set_color(TEAL))
        self.add(plane)

        with self.step("p_together", caption="Two vectors"):
            self.play(LaggedStart(Grow(v, run_time=1), FadeIn(w, run_time=1), lag_ratio=0.5), run_time=1.5)
        with self.step("p_matrix"):
            self.play(ApplyMatrixOn([[1, 1], [0, 1]], plane), ApplyMatrixOn([[1, 1], [0, 1]], v, plane), ApplyMatrixOn([[1, 1], [0, 1]], w, plane), run_time=2)
        with self.step("p_camera"):
            self.play(self.frame.animate.set_height(FRAME_HEIGHT / 2).move_to(v), run_time=2)
        with self.step("p_flash"):
            self.play(FlashOn(v), run_time=1)
        with self.step("p_reset"):
            self.play(self.frame.animate.to_default_state(), run_time=1)


SCENES_IN_ORDER = [Basics, PlaneView]
