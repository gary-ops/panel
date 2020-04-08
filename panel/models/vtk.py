# coding: utf-8
"""
Defines custom VTKPlot bokeh model to render VTK objects.
"""
from bokeh.core.properties import (String, Bool, Dict, Any, Override,
                                   Instance, Int, Float, PositiveInt, Enum)
from bokeh.core.has_props import abstract
from bokeh.core.enums import enumeration
from bokeh.models import HTMLBox, Model, ColumnDataSource

vtk_cdn = "https://unpkg.com/vtk.js"
jszip_cdn = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.1.5/jszip.js"


@abstract
class AbstractVTKPlot(HTMLBox):
    """
    Abstract Bokeh model for vtk plots that wraps around a vtk-js library and
    renders it inside a Bokeh plot.
    """

    __javascript__ = [vtk_cdn]

    __js_skip__ = {'vtk': [vtk_cdn]}

    __js_require__ = {
        "paths": {"vtk": vtk_cdn[:-3]},
        "exports": {"vtk": None},
        "shim": {
            "vtk": {"exports": "vtk"}
        }
    }

    renderer_el = Any(readonly=True)

    orientation_widget = Bool(default=False)

    camera = Dict(String, Any)

    height = Override(default=300)

    width = Override(default=300)


class VTKSynchronizedPlot(AbstractVTKPlot):
    """
    TODO
    """

    __javascript__ = [vtk_cdn, jszip_cdn]

    __js_skip__ = {'vtk': [vtk_cdn, jszip_cdn]}

    __js_require__ = {
        "paths": {"vtk": vtk_cdn[:-3],
                  "jszip": jszip_cdn[:-3]},
        "exports": {"vtk": None, "jszip": None},
        "shim": {
            "vtk": {"exports": "vtk"},
            "jszip": {"exports": "jszip"}
        }
    }

    scene = Dict(String, Any, help="""The serialized vtk.js scene on json format""")

    arrays = Dict(String, Any)

    enable_keybindings = Bool(default=False)

    context_name = String(default='', help="""Name of the synchronized context""")

    one_time_reset = Bool(default=False)


class VTKAxes(Model):
    """
    A Bokeh model for axes
    """

    xticker = Dict(String, Any)

    yticker = Dict(String, Any)

    zticker = Dict(String, Any)

    origin = Any()

    digits = Int(default=1)

    show_grid = Bool(default=True)

    grid_opacity = Float(default=0.1)

    axes_opacity = Float(default=1)

    fontsize = PositiveInt(default=12)



class VTKPlot(AbstractVTKPlot):
    """
    Bokeh model dedicated to plot a vtk render window with only 3D geometry objects
    (Volumes are not suported)
    """

    data = String(help="""The serialized vtk.js data""")

    axes = Instance(VTKAxes)

    enable_keybindings = Bool(default=False)


class VTKVolumePlot(AbstractVTKPlot):
    """
    Bokeh model dedicated to plot a volumetric object with the help of vtk-js
    (3D geometry objects are not suported)
    """

    data = Dict(String, Any)

    colormap = String(help="Colormap Name")

    rescale = Bool(default=False)

    shadow = Bool(default=True)

    sampling = Float(default=0.4)

    edge_gradient = Float(default=0.2)

    ambient = Float(default=0.2)

    diffuse = Float(default=0.7)

    specular = Float(default=0.3)

    specular_power = Float(default=8.)

    slice_i = Int(default=0)

    slice_j = Int(default=0)

    slice_k = Int(default=0)

    display_volume = Bool(default=True)

    display_slices = Bool(default=False)

    render_background = String(default='#52576e')

    interpolation = Enum(enumeration('fast_linear','linear','nearest'))

    mapper = Dict(String, Any)
