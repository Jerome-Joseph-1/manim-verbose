"""
Scene files to pictures and videos. This is the API the CLI and the editor's server use;
nothing outside this package should need to know how rendering works.

OWNER: steps/render agent. Keep these signatures; the server is being built against them.

    Quality = Literal["low", "medium", "hd", "uhd"]
        low 854x480 at 15 fps, medium 1280x720, hd the document's resolution (1920x1080 by
        default), uhd 3840x2160; all but low at the document's fps.

    @dataclass ObjectBox:
        id: str
        bbox: tuple[float, float, float, float]        # pixels x0, y0, x1, y1; origin top left
        frame_bbox: tuple[float, float, float, float]  # manim units xmin, ymin, xmax, ymax

    @dataclass StillResult:
        path: Path; width: int; height: int
        objects: list[ObjectBox]                       # everything registered and on screen, drawn order

    @dataclass StepTiming:
        step_id: str; index: int; start: float; duration: float   # seconds from the start of its scene

    timeline(doc, scene_id) -> list[StepTiming]         # top level steps; no rendering involved
    scene_duration(doc, scene_id) -> float
    document_duration(doc) -> float

    render_still(doc, scene_id, step_index, out_png, width=960, base_dir=None) -> StillResult
        The frame once step `step_index` has finished; -1 for before the first step.
    render_clip(doc, scene_id, out_mp4, start_step=0, end_step=None, quality="low", base_dir=None) -> Path
        Steps start_step..end_step inclusive, starting from the state the earlier steps left.
    render_video(doc, out_mp4, quality="hd", scene_ids=None, jobs=None, base_dir=None,
                 progress=None, cancel=None) -> Path
        Every scene, rendered separately (in parallel up to `jobs`) and joined in order.
        progress(fraction, message) is called as it goes; cancel() returning True stops it,
        raising RenderCancelled.

    class RenderError(Exception): problems: list[Problem]   # LaTeX failures and the like, reworded
    class RenderCancelled(Exception)
"""
from __future__ import annotations
